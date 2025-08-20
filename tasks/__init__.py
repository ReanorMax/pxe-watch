import threading
import time
import subprocess
import datetime
import logging
import re

from db_utils import get_db
from services import set_playbook_status

# Ensure background threads start only once
_tasks_started = False


def ping_host(ip: str) -> bool:
    """Ping host and return True if reachable."""
    try:
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '1', ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return result.returncode == 0
    except Exception as e:
        logging.warning(f"Ошибка при пинге {ip}: {e}")
        return False


def update_host_online_status(ip: str, is_online: bool) -> None:
    """Update online status for host in database."""
    try:
        with get_db() as db:
            db.execute(
                '''
                INSERT INTO host_status (ip, is_online, last_checked)
                VALUES (?, ?, ?)
                ON CONFLICT(ip) DO UPDATE SET
                    is_online = excluded.is_online,
                    last_checked = excluded.last_checked
                ''',
                (ip, is_online, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')),
            )
    except Exception as e:
        logging.error(f"Ошибка обновления статуса для {ip}: {e}")


def ping_hosts_background():
    """Background task that periodically pings all known hosts."""
    while True:
        time.sleep(60)
        logging.info("Начинаем фоновый пинг хостов...")
        try:
            with get_db() as db:
                rows = db.execute(
                    "SELECT DISTINCT ip FROM hosts WHERE ip != '—' AND ip IS NOT NULL"
                ).fetchall()
                ips = [row[0] for row in rows]
            for ip in ips:
                is_online = ping_host(ip)
                update_host_online_status(ip, is_online)
                time.sleep(0.1)
            logging.info(f"Фоновый пинг завершён. Проверено {len(ips)} хостов.")
        except Exception as e:
            logging.error(f"Ошибка в фоновой задаче пинга: {e}", exc_info=True)


def monitor_journal_playbook() -> None:
    """Watch systemd journal and update playbook status when summary appears."""
    summary_re = re.compile(
        r"(?P<ip>\d{1,3}(?:\.\d{1,3}){3})\s*:\s*(?P<stats>.*)"
    )
    cmd = ["journalctl", "-f", "-n", "0"]
    while True:
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            for line in iter(proc.stdout.readline, ""):
                match = summary_re.search(line)
                if not match:
                    continue
                ip = match.group("ip")
                stats = match.group("stats")
                failed = unreachable = 0
                for token in stats.split():
                    if token.startswith("failed="):
                        try:
                            failed = int(token.split("=", 1)[1])
                        except ValueError:
                            continue
                    elif token.startswith("unreachable="):
                        try:
                            unreachable = int(token.split("=", 1)[1])
                        except ValueError:
                            continue
                status = "ok" if failed == 0 and unreachable == 0 else "failed"
                set_playbook_status(ip, status)
            proc.wait()
        except FileNotFoundError:
            logging.error("journalctl not found; playbook monitoring disabled")
            return
        except Exception as e:
            logging.error(f"Ошибка чтения журнала: {e}", exc_info=True)
            time.sleep(5)

def start_background_tasks() -> None:
    """Start all background threads."""
    global _tasks_started
    if _tasks_started:
        return
    _tasks_started = True
    threading.Thread(target=ping_hosts_background, daemon=True).start()
    threading.Thread(target=monitor_journal_playbook, daemon=True).start()
