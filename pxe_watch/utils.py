import datetime
import json
import logging
import os
import re
import subprocess
from flask import abort, jsonify, request
import requests

from .config import (
    SSH_OPTIONS,
    SSH_PASSWORD,
    SSH_USER,
    SEMAPHORE_API,
    SEMAPHORE_PROJECT_ID,
    SEMAPHORE_TEMPLATE_ID,
    SEMAPHORE_TOKEN,
)


def read_file(path: str) -> str:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        abort(404)


def write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    logging.info(f"Файл {path} обновлён")


def list_files_in_dir(directory: str):
    try:
        files = []
        for name in os.listdir(directory):
            file_path = os.path.join(directory, name)
            if os.path.isfile(file_path):
                stat_info = os.stat(file_path)
                size = stat_info.st_size
                if size < 1024:
                    size_str = f"{size} B"
                elif size < 1024**2:
                    size_str = f"{size / 1024:.1f} KB"
                elif size < 1024**3:
                    size_str = f"{size / (1024**2):.1f} MB"
                else:
                    size_str = f"{size / (1024**3):.1f} GB"
                modified = datetime.datetime.fromtimestamp(stat_info.st_mtime).strftime('%d.%m.%Y %H:%M')
                files.append({'name': name, 'size': size_str, 'modified': modified})
        files.sort(key=lambda x: x['name'].lower())
        return jsonify(files)
    except Exception as e:
        logging.error(f"Ошибка при получении списка файлов из {directory}: {e}")
        return jsonify({'error': str(e)}), 500


def create_file_api_handlers(file_path_getter, allow_missing_get=False, name_prefix=""):
    def get_handler(*args, **kwargs):
        try:
            file_path = file_path_getter(*args, **kwargs)
            return read_file(file_path), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        except FileNotFoundError:
            if allow_missing_get:
                return '', 200
            return read_file(file_path_getter(*args, **kwargs))
        except Exception as e:
            logging.error(f'Ошибка при чтении файла {file_path_getter(*args, **kwargs)}: {e}')
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


def get_ansible_mark(ip: str):
    if not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip) or ip == '—':
        return {'status': 'error', 'msg': 'Invalid IP'}
    try:
        cmd = f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} 'cat /opt/ansible_mark.json'"
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
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


def get_semaphore_status():
    try:
        url = f'{SEMAPHORE_API}/project/{SEMAPHORE_PROJECT_ID}/templates'
        headers = {'Authorization': f'Bearer {SEMAPHORE_TOKEN}'}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return {'status': 'error', 'msg': f'API ошибка {res.status_code}'}
        templates = res.json()
        template = next((t for t in templates if t['id'] == SEMAPHORE_TEMPLATE_ID), None)
        if not template or 'last_task' not in template:
            return {'status': 'unknown', 'msg': 'Нет данных'}
        task = template['last_task']
        created = datetime.datetime.fromisoformat(task['created'].replace('Z', '+00:00'))
        local_time = created.astimezone(datetime.datetime.now().astimezone().tzinfo)
        formatted_time = local_time.strftime('%d.%м.%Y %H:%M')
        status_map = {
            'success': 'ok',
            'failed': 'failed',
            'running': 'running',
            'waiting': 'pending',
            'canceled': 'failed',
        }
        icon = (
            '✅' if task['status'] == 'success'
            else '🔴' if task['status'] in ('failed', 'canceled')
            else '🔄' if task['status'] in ('running', 'waiting')
            else '🟡'
        )
        return {
            'status': status_map.get(task['status'], 'unknown'),
            'display_status': task['status'],
            'time': formatted_time,
            'commit_message': task.get('commit_message', ''),
            'task_id': task.get('id'),
            'icon': icon,
        }
    except Exception as e:
        logging.error(f"Ошибка получения статуса из Semaphore: {e}")
        return {'status': 'error', 'msg': str(e)}


def trigger_semaphore_playbook():
    try:
        url = f'{SEMAPHORE_API}/project/{SEMAPHORE_PROJECT_ID}/tasks'
        headers = {
            'Authorization': f'Bearer {SEMAPHORE_TOKEN}',
            'Content-Type': 'application/json',
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
