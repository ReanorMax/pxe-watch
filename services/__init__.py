import os
import logging
import subprocess
import datetime
import re
import json
from typing import Optional
from flask import jsonify, abort, request

from config import (
    SSH_PASSWORD,
    SSH_USER,
    SSH_OPTIONS,
)
from db_utils import get_db


def read_file(path: str) -> str:
    """Read file content as UTF-8."""
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        abort(404)


def write_file(path: str, content: str) -> None:
    """Write content to a file creating directories if needed."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    logging.info(f'Файл {path} обновлён')


def list_files_in_dir(directory: str):
    """Return list of files in directory with size, mtime and type."""
    os.makedirs(directory, exist_ok=True)
    file_list = []
    for f in os.listdir(directory):
        file_path = os.path.join(directory, f)
        try:
            stat_info = os.stat(file_path)
        except OSError as e:
            logging.warning(
                f"Не удалось получить информацию о файле {file_path}: {e}"
            )
            continue

        is_dir = os.path.isdir(file_path)
        size_str = "-"
        if not is_dir:
            size_bytes = stat_info.st_size
            if size_bytes < 1024:
                size_str = f"{size_bytes} B"
            elif size_bytes < 1024 ** 2:
                size_str = f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 ** 3:
                size_str = f"{size_bytes / (1024 ** 2):.1f} MB"
            else:
                size_str = f"{size_bytes / (1024 ** 3):.1f} GB"

        modified_str = datetime.datetime.fromtimestamp(
            stat_info.st_mtime
        ).strftime('%d.%m.%Y %H:%M')
        file_list.append(
            {
                'name': f,
                'size': size_str,
                'modified': modified_str,
                'is_dir': is_dir,
            }
        )

    file_list.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    return file_list


def set_playbook_status(ip: str, status: str, updated: Optional[str] = None) -> None:
    """Store Ansible playbook status for host.

    Args:
        ip: Host IP address.
        status: One of ``running``, ``ok`` or ``failed``.
        updated: Optional timestamp (in ISO format) of when the status was
            recorded.  If not provided, current UTC time is used.
    """
    try:
        ts = updated or datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
        with get_db() as db:
            db.execute(
                '''
                INSERT INTO playbook_status (ip, status, updated)
                VALUES (?, ?, ?)
                ON CONFLICT(ip) DO UPDATE SET
                  status = excluded.status,
                  updated = excluded.updated
                ''',
                (ip, status, ts),
            )
        logging.info(f"Статус Ansible для {ip} установлен в '{status}'")
    except Exception as e:
        logging.error(
            f"Ошибка при установке статуса Ansible для {ip}: {e}", exc_info=True
        )


def get_ansible_mark(ip: str):
    """Fetch ``/opt/ansible_mark.json`` or fall back to stored status.

    Returns a dict with at least a ``status`` field.  When the mark file is
    unavailable but a status exists in the local database, the database value is
    returned so that the dashboard can still reflect the final playbook result.
    """
    if not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip) or ip == '—':
        return {'status': 'error', 'msg': 'Invalid IP'}
    try:
        with get_db() as db:
            row = db.execute(
                "SELECT status, updated FROM playbook_status WHERE ip = ?",
                (ip,),
            ).fetchone()
        if row and row['status'] == 'running':
            return {'status': 'pending', 'msg': 'Ansible playbook is running'}

        db_status = row['status'] if row else None
        db_updated = row['updated'] if row else None

        cmd = (
            f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} "
            "'cat /opt/ansible_mark.json'"
        )
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            try:
                data = json.loads(result.stdout)
                data['status'] = 'ok'
                return data
            except json.JSONDecodeError as e:
                return {
                    'status': 'error',
                    'msg': f'Некорректный JSON в mark.json: {str(e)}',
                }

        # SSH or file errors: fall back to DB if possible
        if db_status in ('ok', 'failed') and db_updated:
            return {'status': db_status, 'install_date': db_updated}

        if "No such file" in result.stderr:
            return {
                'status': 'none',
                'msg': 'Файл mark.json не найден',
            }
        return {'status': 'error', 'msg': f"SSH ошибка: {result.stderr.strip()}"}
    except subprocess.TimeoutExpired:
        if db_status in ('ok', 'failed') and db_updated:
            return {'status': db_status, 'install_date': db_updated}
        return {'status': 'error', 'msg': 'Таймаут подключения к хосту'}
    except Exception as e:
        if db_status in ('ok', 'failed') and db_updated:
            return {'status': db_status, 'install_date': db_updated}
        return {'status': 'error', 'msg': f'Внутренняя ошибка: {str(e)}'}


def create_file_api_handlers(file_path_getter, allow_missing_get: bool = False, name_prefix: str = ""):
    """Create GET/POST handlers for file based APIs."""

    def get_handler(*args, **kwargs):
        try:
            file_path = file_path_getter(*args, **kwargs)
            return read_file(file_path), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        except FileNotFoundError:
            if allow_missing_get:
                return '', 200
            return read_file(file_path_getter(*args, **kwargs))
        except Exception as e:
            logging.error(
                f'Ошибка при чтении файла {file_path_getter(*args, **kwargs)}: {e}'
            )
            return 'Ошибка', 500

    def post_handler(*args, **kwargs):
        try:
            file_path = file_path_getter(*args, **kwargs)
            body = request.get_data(as_text=True)
            write_file(file_path, body)
            return jsonify({'status': 'ok'}), 200
        except Exception as e:
            logging.error(
                f'Ошибка при записи файла {file_path_getter(*args, **kwargs)}: {e}'
            )
            return jsonify({'status': 'error', 'msg': str(e)}), 500

    get_handler.__name__ = f"{name_prefix}_get_handler"
    post_handler.__name__ = f"{name_prefix}_post_handler"
    return get_handler, post_handler
