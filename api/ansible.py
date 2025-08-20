from flask import request, jsonify
import os
import logging

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
    get_ansible_mark,
    create_file_api_handlers
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


@api_bp.route('/ansible/task/<mac>')
def api_ansible_task(mac):
    with get_db() as db:
        task = db.execute(
            '''
            SELECT * FROM ansible_tasks
            WHERE mac = ? ORDER BY started_at DESC LIMIT 1
            ''',
            (mac,),
        ).fetchone()
        return jsonify(dict(task) if task else {})


@api_bp.route('/ansible/clients')
def api_ansible_clients():
    with get_db() as db:
        rows = db.execute(
            '''
            SELECT mac, task_name, status, step, total_steps, started_at
            FROM ansible_tasks ORDER BY started_at DESC
            '''
        ).fetchall()
        return jsonify([dict(r) for r in rows])


@api_bp.route('/ansible/status/<ip>', methods=['GET'])
def api_ansible_status(ip: str):
    result = get_ansible_mark(ip)
    return jsonify(result)

