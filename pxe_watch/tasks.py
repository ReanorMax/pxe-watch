import logging
import subprocess
import time
import re
from collections import deque

from .config import ANSIBLE_SERVICE_NAME
from .db import get_db, set_playbook_status, update_host_online_status


def ping_host(ip: str) -> bool:
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


def ping_hosts_background():
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
                online = ping_host(ip)
                update_host_online_status(ip, online)
                time.sleep(0.2)
        except Exception as e:
            logging.error(f"Ошибка в задаче пинга: {e}")


def parse_ansible_logs():
    last_checked = deque(maxlen=100)
    while True:
        time.sleep(30)
        logging.info("Начинаем анализ логов Ansible...")
        try:
            result = subprocess.run(
                ['journalctl', '-u', ANSIBLE_SERVICE_NAME, '-n', '500', '--no-pager', '--since', '5 minutes ago'],
                capture_output=True,
                text=True,
                check=True,
            )
            lines = result.stdout.strip().split('\n')
            new_lines = [line for line in lines if line not in last_checked]
            last_checked.extend(new_lines)
            ip_status_map = {}
            for line in reversed(new_lines):
                if 'PLAY RECAP' in line:
                    continue
                recap_match = re.search(r'(\d+\.\d+\.\d+\.\d+)\s*:.*?failed=(\d+)', line)
                if recap_match:
                    ip = recap_match.group(1)
                    failed = int(recap_match.group(2))
                    if ip not in ip_status_map:
                        ip_status_map[ip] = 'failed' if failed > 0 else 'ok'
            for ip, status in ip_status_map.items():
                set_playbook_status(ip, status)
            if ip_status_map:
                logging.info(f"Статусы Ansible обновлены для IP: {list(ip_status_map.keys())}")
        except subprocess.CalledProcessError as e:
            logging.warning(f"Ошибка journalctl для {ANSIBLE_SERVICE_NAME}: {e}")
        except Exception as e:
            logging.error(f"Ошибка в задаче парсинга логов Ansible: {e}", exc_info=True)


def check_ansible_marks_background():
    while True:
        time.sleep(120)
        logging.info("Начинаем проверку статусов Ansible через mark.json...")
        try:
            with get_db() as db:
                rows = db.execute(
                    "SELECT DISTINCT ip FROM hosts WHERE ip != '—' AND ip IS NOT NULL"
                ).fetchall()
                for row in rows:
                    logging.info(f"Проверяем статус Ansible для {row[0]}")
        except Exception as e:
            logging.error(
                f"Ошибка в фоновой задаче проверки статусов Ansible: {e}",
                exc_info=True,
            )
