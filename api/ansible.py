from flask import request, jsonify
import os
import subprocess
import logging
import re
import datetime
import configparser

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
    create_file_api_handlers,
    set_playbook_status,
)


def get_macs_from_inventory():
    try:
        config = configparser.ConfigParser()
        config.read(ANSIBLE_INVENTORY)
        macs = []
        for section in config.sections():
            for key, val in config.items(section):
                if key.startswith('mac'):
                    macs.append(val.lower())
        return macs
    except Exception:
        return []


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


@api_bp.route('/ansible/tags', methods=['GET'])
def api_ansible_tags():
    """Return list of tags defined in the playbook."""
    try:
        result = subprocess.run(
            [
                "ansible-playbook",
                ANSIBLE_PLAYBOOK,
                "-i",
                ANSIBLE_INVENTORY,
                "--list-tags",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        tags = set()
        for line in result.stdout.splitlines():
            match = re.search(r'TAGS:\s*\[([^\]]*)\]', line)
            if match:
                for tag in match.group(1).split(','):
                    tag = tag.strip()
                    if tag:
                        tags.add(tag)
        return jsonify({"tags": sorted(tags)})
    except subprocess.CalledProcessError as e:
        logging.error(f"Ошибка получения тегов Ansible: {e}")
        msg = e.stderr or str(e)
        return jsonify({"error": msg}), 500
    except Exception as e:
        logging.error(f"Ошибка получения тегов Ansible: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route('/ansible/run', methods=['POST'])
def api_ansible_run():
    try:
        payload = request.get_json(silent=True) or {}
        tags = payload.get('tags') or []
        macs = get_macs_from_inventory()
        started = datetime.datetime.utcnow().isoformat()
        with get_db() as db:
            for mac in macs:
                db.execute(
                    '''
                    INSERT INTO ansible_tasks(mac, task_name, status, step, total_steps, started_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ''',
                    (mac, 'playbook.yml', 'running', 0, 10, started),
                )
                ip_row = db.execute(
                    "SELECT ip FROM hosts WHERE mac = ?",
                    (mac,),
                ).fetchone()
                if ip_row and ip_row['ip']:
                    set_playbook_status(ip_row['ip'], 'running')
        cmd = ["ansible-playbook", ANSIBLE_PLAYBOOK, "-i", ANSIBLE_INVENTORY]
        if tags:
            cmd.extend(["--tags", ",".join(tags)])
        result = subprocess.run(cmd, capture_output=True, text=True)

        # Ignore warnings about collections not supporting the current Ansible version.
        # These warnings are emitted on stderr and previously caused the API to
        # treat the execution as a failure even though ``ansible-playbook``
        # returned successfully.  We filter them out so that such warnings do
        # not trigger an error response.
        warning_re = re.compile(
            r"^(?:\[WARNING\]|WARNING): Collection .* does not support Ansible(?: core)? version"
        )
        stderr_lines = result.stderr.splitlines() if result.stderr else []
        non_warning_lines = [line for line in stderr_lines if not warning_re.match(line)]

        ip_status_map = {}
        recap_started = False
        for line in result.stdout.splitlines():
            if line.strip().startswith("PLAY RECAP"):
                recap_started = True
                continue
            if recap_started:
                match = re.search(r"(\d+\.\d+\.\d+\.\d+).*failed=(\d+)", line)
                if match:
                    ip, failed = match.groups()
                    ip_status_map[ip] = 'failed' if int(failed) > 0 else 'ok'
        if ip_status_map:
            with get_db() as db:
                for ip, status in ip_status_map.items():
                    set_playbook_status(ip, status)
                    mac_row = db.execute(
                        "SELECT mac FROM hosts WHERE ip = ?", (ip,)
                    ).fetchone()
                    if mac_row:
                        db.execute(
                            """
                            UPDATE ansible_tasks
                            SET status=?, step=10
                            WHERE mac=? AND started_at=?
                            """,
                            (status, mac_row['mac'], started),
                        )
        if result.returncode == 0 or not non_warning_lines:
            if non_warning_lines:
                logging.warning(
                    "ansible-playbook completed with warnings: %s",
                    "\n".join(non_warning_lines),
                )
            elif stderr_lines:
                logging.warning(
                    "ansible-playbook reported version warnings: %s",
                    "\n".join(stderr_lines),
                )
            else:
                logging.info("ansible-playbook completed successfully")
            return jsonify({'status': 'ok', 'data': result.stdout}), 200
        else:
            logging.error(
                "ansible-playbook failed with code %s: %s",
                result.returncode,
                result.stderr,
            )
            return (
                jsonify(
                    {
                        'status': 'error',
                        'code': result.returncode,
                        'msg': result.stderr,
                    }
                ),
                500,
            )
    except Exception as e:
        logging.error(f"Ошибка запуска ansible-playbook: {e}")
        return jsonify({'status': 'error', 'msg': str(e)}), 500


@api_bp.route('/ansible/status/<ip>', methods=['GET'])
def api_ansible_status(ip: str):
    result = get_ansible_mark(ip)
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
