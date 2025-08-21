import threading
import time
import subprocess
import datetime
import logging
import re
import json

from db_utils import get_db
from services import set_playbook_status, set_install_status
from config import SSH_PASSWORD, SSH_USER, SSH_OPTIONS

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


def ansible_log_monitor() -> None:
    """Tail Ansible service logs and update playbook status by host."""
    pattern = re.compile(
        r"(?P<ip>(?:\d{1,3}\.){3}\d{1,3})\s*:\s*(?P<stats>.*)"
    )
    while True:
        cmd = [
            "journalctl",
            "-u",
            "ansible-api.service",
            "-f",
            "--no-pager",
            "-n",
            "0",
            "-o",
            "cat",
        ]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in iter(proc.stdout.readline, ""):
                clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
                m = pattern.search(clean)
                if not m:
                    continue
                ip = m.group("ip")
                stats = dict(re.findall(r"(\w+)=(\d+)", m.group("stats")))
                failed = int(stats.get("failed", 0))
                unreachable = int(stats.get("unreachable", 0))
                status = "ok" if failed == 0 and unreachable == 0 else "failed"
                set_playbook_status(ip, status)
        except Exception as e:
            logging.error(
                f"Ошибка в анализе логов Ansible: {e}", exc_info=True
            )
            time.sleep(5)


def fetch_install_status(ip: str) -> None:
    """Retrieve install_status.json from host and store it."""
    cmd = (
        f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} "
        "'cat /var/log/install_status.json'"
    )
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout or '{}')
                status = (data.get('status') or '').lower()
                completed_at = data.get('completed_at')
                if status:
                    set_install_status(ip, status, completed_at)
                else:
                    logging.warning(f"Пустой статус установки от {ip}")
            except json.JSONDecodeError as e:
                logging.warning(
                    f"Некорректный JSON install_status от {ip}: {e}"
                )
        else:
            if 'No such file' in result.stderr:
                set_install_status(ip, 'pending', None)
            else:
                logging.warning(
                    f"SSH ошибка при получении install_status от {ip}: {result.stderr.strip()}"
                )
    except subprocess.TimeoutExpired:
        logging.warning(f"Таймаут при получении install_status от {ip}")
    except Exception as e:
        logging.error(f"Ошибка при получении install_status от {ip}: {e}")


def install_status_monitor() -> None:
    """Background task that checks install_status.json on hosts."""
    while True:
        time.sleep(60)
        logging.info("Проверяем статусы установки на хостах...")
        try:
            with get_db() as db:
                rows = db.execute(
                    "SELECT DISTINCT ip FROM hosts WHERE ip != '—' AND ip IS NOT NULL"
                ).fetchall()
                ips = [row[0] for row in rows]
            for ip in ips:
                fetch_install_status(ip)
                time.sleep(0.1)
            logging.info(
                f"Проверка статусов установки завершена. Проверено {len(ips)} хостов."
            )
        except Exception as e:
            logging.error(
                f"Ошибка в задаче мониторинга статуса установки: {e}", exc_info=True
            )


def start_background_tasks() -> None:
    """Start all background threads."""
    global _tasks_started
    if _tasks_started:
        return
    _tasks_started = True
    threading.Thread(target=ping_hosts_background, daemon=True).start()
    threading.Thread(target=ansible_log_monitor, daemon=True).start()
    threading.Thread(target=install_status_monitor, daemon=True).start()
