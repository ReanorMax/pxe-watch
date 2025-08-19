from flask import request, jsonify
import subprocess
import logging

from config import (
    PRESEED_PATH,
    PRESEED_DIR,
    DNSMASQ_PATH,
    BOOT_IPXE_PATH,
    AUTOEXEC_IPXE_PATH,
)
from . import api_bp
from services import read_file, write_file
import os
import shutil


def _preseed_file_path(name: str) -> str:
    return os.path.join(PRESEED_DIR, name)


def _active_preseed_name() -> str:
    return os.path.basename(os.path.realpath(PRESEED_PATH))


@api_bp.route('/preseed/list', methods=['GET'])
def api_preseed_list():
    os.makedirs(PRESEED_DIR, exist_ok=True)
    files = [
        f
        for f in os.listdir(PRESEED_DIR)
        if os.path.isfile(os.path.join(PRESEED_DIR, f))
    ]
    return jsonify({'files': files, 'active': _active_preseed_name()})


@api_bp.route('/preseed', methods=['GET'])
def api_preseed_get():
    name = request.args.get('name') or _active_preseed_name()
    path = _preseed_file_path(name)
    return read_file(path), 200, {'Content-Type': 'text/plain; charset=utf-8'}


@api_bp.route('/preseed', methods=['POST'])
def api_preseed_post():
    name = request.args.get('name') or _active_preseed_name()
    body = request.get_data(as_text=True)
    try:
        path = _preseed_file_path(name)
        write_file(path, body)
        return jsonify({'status': 'ok'}), 200
    except IOError as e:
        logging.error(f'Ошибка при записи preseed файла: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500


@api_bp.route('/preseed/create', methods=['POST'])
def api_preseed_create():
    data = request.get_json(force=True)
    name = data.get('name') if data else None
    if not name:
        return jsonify({'status': 'error', 'msg': 'name required'}), 400
    path = _preseed_file_path(name)
    if os.path.exists(path):
        return jsonify({'status': 'error', 'msg': 'already exists'}), 400
    try:
        os.makedirs(PRESEED_DIR, exist_ok=True)
        src = os.path.realpath(PRESEED_PATH)
        if os.path.exists(src):
            shutil.copyfile(src, path)
        else:
            write_file(path, '')
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logging.error(f'Ошибка при создании preseed файла: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500


@api_bp.route('/preseed/activate', methods=['POST'])
def api_preseed_activate():
    data = request.get_json(force=True)
    name = data.get('name') if data else None
    if not name:
        return jsonify({'status': 'error', 'msg': 'name required'}), 400
    target = _preseed_file_path(name)
    if not os.path.isfile(target):
        return jsonify({'status': 'error', 'msg': 'file not found'}), 404
    try:
        os.makedirs(os.path.dirname(PRESEED_PATH), exist_ok=True)
        if os.path.islink(PRESEED_PATH) or os.path.exists(PRESEED_PATH):
            os.remove(PRESEED_PATH)
        os.symlink(target, PRESEED_PATH)
        return jsonify({'status': 'ok'}), 200
    except OSError as e:
        logging.error(f'Ошибка при активации preseed файла: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500


@api_bp.route('/ipxe', methods=['GET'])
def api_ipxe_get():
    try:
        boot_content = read_file(BOOT_IPXE_PATH)
        autoexec_content = read_file(AUTOEXEC_IPXE_PATH)
        combined = f"### boot.ipxe ###\n{boot_content}\n### autoexec.ipxe ###\n{autoexec_content}"
        return combined, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e:
        logging.error(f'Ошибка при чтении iPXE файлов: {e}')
        return 'Ошибка', 500


@api_bp.route('/ipxe', methods=['POST'])
def api_ipxe_post():
    content = request.get_data(as_text=True)
    try:
        parts = content.split('\n### autoexec.ipxe ###\n')
        if len(parts) != 2:
            raise ValueError('Неверный формат данных')
        boot_content = parts[0].replace('### boot.ipxe ###\n', '', 1)
        autoexec_content = parts[1]
        write_file(BOOT_IPXE_PATH, boot_content)
        write_file(AUTOEXEC_IPXE_PATH, autoexec_content)
        logging.info('Файлы boot.ipxe и autoexec.ipxe обновлены')
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logging.error(f'Ошибка при сохранении iPXE файлов: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500


@api_bp.route('/dnsmasq', methods=['GET'])
def api_dnsmasq_get():
    return read_file(DNSMASQ_PATH), 200, {'Content-Type': 'text/plain; charset=utf-8'}


@api_bp.route('/dnsmasq', methods=['POST'])
def api_dnsmasq_post():
    body = request.get_data(as_text=True)
    try:
        write_file(DNSMASQ_PATH, body)
        subprocess.run(['sudo', 'systemctl', 'restart', 'dnsmasq'], check=True)
        logging.info('dnsmasq.conf обновлён и dnsmasq перезапущен')
        return jsonify({'status': 'ok'}), 200
    except subprocess.CalledProcessError as e:
        logging.error(f'Ошибка при сохранении dnsmasq.conf: {e}')
        msg = f"Ошибка выполнения команды: {e}"
        if e.stderr:
            msg += f". Stderr: {e.stderr.decode('utf-8')}"
        return jsonify({'status': 'error', 'msg': msg}), 500
    except Exception as e:
        logging.error(f'Неизвестная ошибка при сохранении dnsmasq.conf: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500
