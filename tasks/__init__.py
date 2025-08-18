import threading
import time
import logging
import subprocess
import re

from config import ANSIBLE_SERVICE_NAME
from services import get_db, ping_host, update_host_online_status, set_playbook_status


def ping_hosts_background():
    while True:
        time.sleep(60)
        logging.info("Начинаем фоновый пинг хостов...")
        try:
            with get_db() as db:
                rows = db.execute("SELECT DISTINCT ip FROM hosts WHERE ip != '—' AND ip IS NOT NULL").fetchall()
                ips = [row[0] for row in rows]
            for ip in ips:
                is_online = ping_host(ip)
                update_host_online_status(ip, is_online)
                time.sleep(0.1)
            logging.info(f"Фоновый пинг завершён. Проверено {len(ips)} хостов.")
        except Exception as e:
            logging.error(f"Ошибка в фоновой задаче пинга: {e}", exc_info=True)


def parse_ansible_logs():
    last_checked_lines = set()
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
            new_lines = [line for line in lines if line not in last_checked_lines]
            last_checked_lines.update(new_lines[-100:])
            ip_status_map = {}
            for line in reversed(new_lines):
                if 'PLAY RECAP' in line:
                    continue
                recap_match = re.search(r'(\d+\.\d+\.\d+\.\d+)\s*:.*?failed=(\d+)', line)
                if recap_match:
                    ip = recap_match.group(1)
                    failed_count = int(recap_match.group(2))
                    if ip not in ip_status_map:
                        ip_status_map[ip] = 'failed' if failed_count > 0 else 'ok'
            for ip, status in ip_status_map.items():
                set_playbook_status(ip, status)
            if ip_status_map:
                logging.info(f"Статусы Ansible обновлены для IP: {list(ip_status_map.keys())}")
        except subprocess.CalledProcessError as e:
            logging.warning(f"Ошибка выполнения journalctl для {ANSIBLE_SERVICE_NAME}: {e}")
        except Exception as e:
            logging.error(f"Ошибка в фоновой задаче парсинга логов Ansible: {e}", exc_info=True)


def check_ansible_marks_background():
    while True:
        time.sleep(120)
        logging.info("Начинаем проверку статусов Ansible через mark.json...")
        try:
            with get_db() as db:
                rows = db.execute("SELECT DISTINCT ip FROM hosts WHERE ip != '—' AND ip IS NOT NULL").fetchall()
                ips = [row[0] for row in rows]
            for ip in ips:
                logging.info(f"Проверяем статус Ansible для {ip}")
        except Exception as e:
            logging.error(f"Ошибка в фоновой задаче проверки статусов Ansible: {e}", exc_info=True)


def start_background_tasks():
    threading.Thread(target=ping_hosts_background, daemon=True).start()
    threading.Thread(target=parse_ansible_logs, daemon=True).start()
    threading.Thread(target=check_ansible_marks_background, daemon=True).start()
