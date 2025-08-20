import threading
import time
import subprocess
import datetime
import logging

from db_utils import get_db

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


def start_background_tasks() -> None:
    """Start all background threads."""
    global _tasks_started
    if _tasks_started:
        return
    _tasks_started = True
    threading.Thread(target=ping_hosts_background, daemon=True).start()
