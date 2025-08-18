import os
import pathlib
import logging
import subprocess
import sqlite3
import datetime
import re
import json
import requests
from flask import abort, jsonify, request

from config import (
    DB_PATH,
    PRESEED_PATH,
    DNSMASQ_PATH,
    BOOT_IPXE_PATH,
    AUTOEXEC_IPXE_PATH,
    LOGS_DIR,
    ONLINE_TIMEOUT,
    LOCAL_OFFSET,
    ANSIBLE_PLAYBOOK,
    ANSIBLE_INVENTORY,
    ANSIBLE_FILES_DIR,
    ANSIBLE_TEMPLATES_DIR,
    SSH_PASSWORD,
    SSH_USER,
    SSH_OPTIONS,
    ANSIBLE_SERVICE_NAME,
    SEMAPHORE_API,
    SEMAPHORE_TOKEN,
    SEMAPHORE_PROJECT_ID,
    SEMAPHORE_TEMPLATE_ID,
)


def get_db():
    """Создает и инициализирует соединение с базой данных SQLite."""
    os.makedirs(pathlib.Path(DB_PATH).parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute('''
        CREATE TABLE IF NOT EXISTS hosts (
            mac TEXT PRIMARY KEY,
            ip TEXT,
            stage TEXT,
            details TEXT,
            ts TEXT,
            first_ts TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS host_status (
            ip TEXT PRIMARY KEY,
            is_online BOOLEAN,
            last_checked TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS playbook_status (
            ip TEXT PRIMARY KEY,
            status TEXT,
            updated TEXT
        )
    ''')
    return conn


def read_file(path):
    """Читает содержимое файла с диска."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        abort(404)


def write_file(path, content):
    """Записывает содержимое в файл на диск."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    logging.info(f'Файл {path} обновлён')


def list_files_in_dir(directory):
    """Возвращает список файлов в указанной директории с дополнительной информацией."""
    try:
        os.makedirs(directory, exist_ok=True)
        file_list = []
        for f in os.listdir(directory):
            file_path = os.path.join(directory, f)
            if os.path.isfile(file_path):
                stat_info = os.stat(file_path)
                size_bytes = stat_info.st_size
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024**2:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024**3:
                    size_str = f"{size_bytes / (1024**2):.1f} MB"
                else:
                    size_str = f"{size_bytes / (1024**3):.1f} GB"
                modified_timestamp = stat_info.st_mtime
                modified_str = datetime.datetime.fromtimestamp(modified_timestamp).strftime('%d.%m.%Y %H:%M')
                file_list.append({'name': f, 'size': size_str, 'modified': modified_str})
        file_list.sort(key=lambda x: x['name'].lower())
        return jsonify(file_list)
    except Exception as e:
        logging.error(f"Ошибка при получении списка файлов из {directory}: {e}")
        return jsonify({'error': str(e)}), 500


def set_playbook_status(ip, status):
    """Устанавливает статус выполнения Ansible плейбука для IP-адреса."""
    try:
        with get_db() as db:
            db.execute('''
                INSERT INTO playbook_status (ip, status, updated)
                VALUES (?, ?, ?)
                ON CONFLICT(ip) DO UPDATE SET
                  status = excluded.status,
                  updated = excluded.updated
            ''', (ip, status, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')))
        logging.info(f"Статус Ansible для {ip} установлен в '{status}'")
    except Exception as e:
        logging.error(f"Ошибка при установке статуса Ansible для {ip}: {e}", exc_info=True)


def get_ansible_mark(ip):
    """Получает информацию из файла /opt/ansible_mark.json с удаленного хоста через SSH."""
    if not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip) or ip == '—':
        return {'status': 'error', 'msg': 'Invalid IP'}
    try:
        cmd = f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} 'cat /opt/ansible_mark.json'"
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            if "No such file" in result.stderr:
                return {'status': 'pending', 'msg': 'Файл mark.json не найден (Ansible не завершил установку)'}
            else:
                return {'status': 'error', 'msg': f"SSH ошибка: {result.stderr.strip()}"}
        try:
            data = json.loads(result.stdout)
            data['status'] = 'ok'
            return data
        except json.JSONDecodeError as e:
            return {'status': 'error', 'msg': f'Некорректный JSON в mark.json: {str(e)}'}
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'msg': 'Таймаут подключения к хосту'}
    except Exception as e:
        return {'status': 'error', 'msg': f'Внутренняя ошибка: {str(e)}'}


def create_file_api_handlers(file_path_getter, allow_missing_get=False, name_prefix=""):
    """Создаёт пару обработчиков GET/POST для работы с файлами через API."""
    def get_handler(*args, **kwargs):
        try:
            file_path = file_path_getter(*args, **kwargs)
            return read_file(file_path), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        except FileNotFoundError:
            if allow_missing_get:
                return '', 200
            else:
                return read_file(file_path_getter(*args, **kwargs))
        except Exception as e:
            logging.error(f'Ошибка при чтении файла {file_path_getter(*args, **kwargs) if "file_path" not in locals() else file_path}: {e}')
            return 'Ошибка', 500

    def post_handler(*args, **kwargs):
        try:
            file_path = file_path_getter(*args, **kwargs)
            body = request.get_data(as_text=True)
            write_file(file_path, body)
            return jsonify({'status': 'ok'}), 200
        except Exception as e:
            logging.error(f'Ошибка при записи файла {file_path_getter(*args, **kwargs)}: {e}')
            return jsonify({'status': 'error', 'msg': str(e)}), 500

    get_handler.__name__ = f"{name_prefix}_get_handler"
    post_handler.__name__ = f"{name_prefix}_post_handler"
    return get_handler, post_handler


def ping_host(ip):
    """Проверяет доступность хоста через ICMP-запрос (пинг)."""
    try:
        result = subprocess.run(['ping', '-c', '1', '-W', '1', ip], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return result.returncode == 0
    except Exception as e:
        logging.warning(f"Ошибка при пинге {ip}: {e}")
        return False


def update_host_online_status(ip, is_online):
    """Обновляет статус онлайн/оффлайн для хоста в базе данных."""
    try:
        with get_db() as db:
            db.execute('''
                INSERT INTO host_status (ip, is_online, last_checked)
                VALUES (?, ?, ?)
                ON CONFLICT(ip) DO UPDATE SET
                    is_online = excluded.is_online,
                    last_checked = excluded.last_checked
            ''', (ip, is_online, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')))
    except Exception as e:
        logging.error(f"Ошибка обновления статуса для {ip}: {e}")


def get_semaphore_status():
    """Получает статус последнего запуска Ansible из Semaphore."""
    try:
        url = f'{SEMAPHORE_API}/project/{SEMAPHORE_PROJECT_ID}/templates'
        headers = {'Authorization': f'Bearer {SEMAPHORE_TOKEN}'}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return {'status': 'error', 'msg': f'API ошибка {res.status_code}'}
        templates = res.json()
        template = next((t for t in templates if t['id'] == SEMAPHORE_TEMPLATE_ID), None)
        if not template or not template.get('last_task'):
            return {'status': 'unknown'}
        task = template['last_task']
        ts = task.get('created')
        try:
            dt = datetime.datetime.fromisoformat(ts)
            formatted_time = dt.strftime('%d.%m.%Y %H:%M')
        except Exception:
            formatted_time = ts
        status_map = {
            'success': 'ok',
            'error': 'failed',
            'pending': 'running',
            'running': 'running',
            None: 'unknown'
        }
        icon = {
            'success': '🟢',
            'error': '🔴',
            'pending': '🟡',
            'running': '🟡',
            None: '⚪'
        }.get(task['status'])
        return {
            'status': status_map.get(task['status'], 'unknown'),
            'display_status': task.get('status', 'unknown'),
            'time': formatted_time,
            'commit_message': task.get('commit_message', ''),
            'task_id': task.get('id'),
            'icon': icon
        }
    except Exception as e:
        logging.error(f"Ошибка получения статуса из Semaphore: {e}")
        return {'status': 'error', 'msg': str(e)}


def trigger_semaphore_playbook():
    try:
        url = f'{SEMAPHORE_API}/project/{SEMAPHORE_PROJECT_ID}/tasks'
        headers = {
            'Authorization': f'Bearer {SEMAPHORE_TOKEN}',
            'Content-Type': 'application/json'
        }
        payload = {'template_id': SEMAPHORE_TEMPLATE_ID}
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if 200 <= res.status_code < 300:
            task = res.json()
            logging.info(f"Ansible запущен через API: task_id={task['id']}")
            return {'status': 'ok', 'task_id': task['id']}
        else:
            return {'status': 'error', 'msg': f"HTTP {res.status_code}: {res.text}"}
    except Exception as e:
        logging.error(f"Ошибка запуска Ansible через API: {e}")
        return {'status': 'error', 'msg': str(e)}


def get_file_path(filename):
    return os.path.join(ANSIBLE_FILES_DIR, filename)


def get_template_path(filename):
    return os.path.join(ANSIBLE_TEMPLATES_DIR, filename)
