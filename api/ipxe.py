from flask import request, jsonify
import subprocess
import logging

from config import (
    PRESEED_PATH,
    DNSMASQ_PATH,
    BOOT_IPXE_PATH,
    AUTOEXEC_IPXE_PATH,
)
from . import api_bp
from services import read_file, write_file


@api_bp.route('/preseed', methods=['GET'])
def api_preseed_get():
    return read_file(PRESEED_PATH), 200, {'Content-Type': 'text/plain; charset=utf-8'}


@api_bp.route('/preseed', methods=['POST'])
def api_preseed_post():
    body = request.get_data(as_text=True)
    try:
        write_file(PRESEED_PATH, body)
        return jsonify({'status': 'ok'}), 200
    except IOError as e:
        logging.error(f'Ошибка при записи preseed файла: {e}')
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
