from flask import request, jsonify
import subprocess
import logging

from config import (
    DNSMASQ_PATH,
    BOOT_IPXE_PATH,
    AUTOEXEC_IPXE_PATH,
)
from . import api_bp
from services import read_file, write_file
from services.preseed import get_preseed_path, get_active_index, set_active_index


@api_bp.route('/preseed', methods=['GET'])
def api_preseed_get():
    idx = request.args.get('file', type=int)
    path = get_preseed_path(idx)
    return read_file(path), 200, {'Content-Type': 'text/plain; charset=utf-8'}


@api_bp.route('/preseed', methods=['POST'])
def api_preseed_post():
    idx = request.args.get('file', type=int)
    path = get_preseed_path(idx)
    body = request.get_data(as_text=True)
    try:
        write_file(path, body)
        return jsonify({'status': 'ok'}), 200
    except IOError as e:
        logging.error(f'Ошибка при записи preseed файла: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500


@api_bp.route('/preseed/active', methods=['GET', 'POST'])
def api_preseed_active():
    if request.method == 'GET':
        return jsonify({'active': get_active_index()}), 200
    idx = request.json.get('active') if request.is_json else request.form.get('active')
    try:
        set_active_index(int(idx))
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        return jsonify({'status': 'error', 'msg': str(e)}), 400


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
