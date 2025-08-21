from flask import request, jsonify
import os
import subprocess
import logging
import re

from db_utils import get_db

from config import (
    ANSIBLE_PLAYBOOK,
    ANSIBLE_INVENTORY,
    ANSIBLE_FILES_DIR,
    ANSIBLE_TEMPLATES_DIR,
)
from . import api_bp
from services import (
    list_files_in_dir,
    get_install_status,
    create_file_api_handlers,
)


playbook_get, playbook_post = create_file_api_handlers(
    lambda: ANSIBLE_PLAYBOOK, name_prefix='playbook'
)
api_bp.route('/ansible/playbook', methods=['GET'])(playbook_get)
api_bp.route('/ansible/playbook', methods=['POST'])(playbook_post)

inventory_get, inventory_post = create_file_api_handlers(
    lambda: ANSIBLE_INVENTORY,
    allow_missing_get=True,
    name_prefix='inventory',
)
api_bp.route('/ansible/inventory', methods=['GET'])(inventory_get)
api_bp.route('/ansible/inventory', methods=['POST'])(inventory_post)


def get_file_path(filename: str) -> str:
    return os.path.join(ANSIBLE_FILES_DIR, filename)


def get_template_path(filename: str) -> str:
    return os.path.join(ANSIBLE_TEMPLATES_DIR, filename)


file_get, file_post = create_file_api_handlers(
    get_file_path, name_prefix='file'
)
api_bp.route('/ansible/files/<path:filename>', methods=['GET'])(file_get)
api_bp.route('/ansible/files/<path:filename>', methods=['POST'])(file_post)

template_get, template_post = create_file_api_handlers(
    get_template_path, name_prefix='template'
)
api_bp.route('/ansible/templates/<path:filename>', methods=['GET'])(template_get)
api_bp.route('/ansible/templates/<path:filename>', methods=['POST'])(template_post)


@api_bp.route('/ansible/files', methods=['GET'])
def api_ansible_files_list():
    rel_path = request.args.get('path', '').strip()
    base_dir = os.path.abspath(ANSIBLE_FILES_DIR)
    target_dir = os.path.abspath(os.path.join(base_dir, rel_path))
    if not target_dir.startswith(base_dir):
        return jsonify({'error': 'Invalid path'}), 400
    try:
        files = list_files_in_dir(target_dir)
        parent = os.path.relpath(os.path.dirname(target_dir), base_dir) if rel_path else ''
        if parent == '.':
            parent = ''
        return jsonify({'files': files, 'path': rel_path, 'parent': parent})
    except Exception as e:
        logging.error(f"Ошибка при получении списка файлов из {target_dir}: {e}")
        return jsonify({'error': str(e)}), 500


@api_bp.route('/ansible/templates', methods=['GET'])
def api_ansible_templates_list():
    try:
        return jsonify(list_files_in_dir(ANSIBLE_TEMPLATES_DIR))
    except Exception as e:
        logging.error(f"Ошибка при получении списка шаблонов: {e}")
        return jsonify({'error': str(e)}), 500

@api_bp.route('/ansible/status/<ip>', methods=['GET'])
def api_ansible_status(ip: str):
    result = get_install_status(ip)
    return jsonify(result)


@api_bp.route('/logs/ansible', methods=['GET'])
def api_logs_ansible():
    """Return colored ansible service logs with optional pagination."""
    limit = request.args.get('limit', default=100, type=int)
    offset = request.args.get('offset', default=0, type=int)
    limit = max(1, min(limit, 1000))
    offset = max(0, offset)
    try:
        fetch_lines = str(limit + offset)
        result = subprocess.run(
            ['journalctl', '-u', 'ansible-api.service', '-n', fetch_lines, '--no-pager'],
            capture_output=True,
            text=True,
            check=True,
        )
        lines = result.stdout.strip().split('\n')
        filtered_lines = []
        filter_keywords = [
            'Начинаем фоновый пинг хостов',
            'Фоновый пинг завершён',
            'Начинаем анализ логов Ansible',
            '[Пропущено',
        ]
        for line in lines:
            if not any(keyword in line for keyword in filter_keywords):
                filtered_lines.append(line)
        colored_lines = []
        for line in filtered_lines:
            line = f'<span style="font-size:14px;line-height:1.5">{line}</span>'
            line = line.replace('INFO', '<span style="color:#51cf66; font-weight:bold">INFO</span>')
            line = line.replace('WARNING', '<span style="color:#ffa94d; font-weight:bold">WARNING</span>')
            line = line.replace('ERROR', '<span style="color:#ff6b6b; font-weight:bold">ERROR</span>')
            line = line.replace('CRITICAL', '<span style="color:#ff375f; background:#ffccd5; font-weight:bold">CRITICAL</span>')
            line = line.replace(' 200 ', '<span style="color:#51cf66; font-weight:bold"> 200 </span>')
            line = line.replace(' 404 ', '<span style="color:#ff6b6b; font-weight:bold"> 404 </span>')
            line = line.replace(' 500 ', '<span style="color:#ff375f; background:#ffccd5; font-weight:bold"> 500 </span>')
            line = line.replace('GET', '<span style="color:#9775fa; font-weight:bold">GET</span>')
            line = line.replace('POST', '<span style="color:#9775fa; font-weight:bold">POST</span>')
            line = re.sub(
                r'([0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5})',
                r'<span style="color:#0ca678; font-weight:bold; font-family:monospace">\1</span>',
                line,
            )
            line = re.sub(
                r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
                r'<span style="color:#087f5b; font-weight:bold; font-family:monospace">\g<0></span>',
                line,
            )
            line = re.sub(
                r'(\w{3} \d{1,2} \d{2}:\d{2}:\d{2})',
                r'<span style="color:#adb5bd">\1</span>',
                line,
            )
            colored_lines.append(line)
        window = colored_lines[-(limit + offset):]
        if offset:
            window = window[:-offset]
        return jsonify(window), 200
    except subprocess.CalledProcessError as e:
        logging.error(f'Ошибка выполнения journalctl: {e}')
        msg = f"Ошибка выполнения journalctl: {e}"
        if e.stderr:
            msg += f". Stderr: {e.stderr}"
        return jsonify([f"<span style='color:#ff6b6b; font-size:14px'>{msg}</span>"]), 500
    except Exception as e:
        logging.error(f'Ошибка чтения логов Ansible: {e}')
        return jsonify([f"<span style='color:#ff375f; font-size:14px'>Ошибка: {str(e)}</span>"]), 500
