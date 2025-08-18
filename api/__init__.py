from flask import Blueprint, request, jsonify
import os
import pathlib
import subprocess
import datetime
import logging
import re

from config import (
    DB_PATH,
    PRESEED_PATH,
    DNSMASQ_PATH,
    BOOT_IPXE_PATH,
    AUTOEXEC_IPXE_PATH,
    ANSIBLE_PLAYBOOK,
    ANSIBLE_INVENTORY,
    ANSIBLE_FILES_DIR,
    ANSIBLE_TEMPLATES_DIR,
    SSH_PASSWORD,
    SSH_USER,
    SSH_OPTIONS,
)
from db_utils import get_db
from services import (
    read_file,
    write_file,
    list_files_in_dir,
    get_ansible_mark,
    create_file_api_handlers,
    get_semaphore_status,
    trigger_semaphore_playbook,
)
from services.registration import register_host

api_bp = Blueprint('api', __name__, url_prefix='/api')

@api_bp.route('/semaphore/status', methods=['GET'])
def api_semaphore_status():
    return jsonify(get_semaphore_status())

@api_bp.route('/semaphore/trigger', methods=['POST'])
def api_semaphore_trigger():
    result = trigger_semaphore_playbook()
    return jsonify(result), 200 if result['status'] == 'ok' else 500

@api_bp.route('/register', methods=['GET', 'POST'])
def api_register():
    mac = request.values.get('mac', '').lower()
    ip = request.values.get('ip', request.remote_addr)
    stage = request.values.get('stage', 'unknown')
    details = request.values.get('details', '')
    try:
        register_host(mac, ip, stage, details)
    except ValueError:
        return 'Missing MAC', 400
    except Exception as e:
        logging.error(f'Ошибка при регистрации хоста: {e}')
        return 'Error', 500
    return 'OK', 200

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

@api_bp.route('/clear-db', methods=['POST'])
def api_clear_db():
    try:
        pathlib.Path(DB_PATH).unlink(missing_ok=True)
        logging.info('База данных очищена')
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logging.error(f'Ошибка при очистке базы данных: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500

playbook_get, playbook_post = create_file_api_handlers(lambda: ANSIBLE_PLAYBOOK, name_prefix='playbook')
api_bp.route('/ansible/playbook', methods=['GET'])(playbook_get)
api_bp.route('/ansible/playbook', methods=['POST'])(playbook_post)

inventory_get, inventory_post = create_file_api_handlers(lambda: ANSIBLE_INVENTORY, allow_missing_get=True, name_prefix='inventory')
api_bp.route('/ansible/inventory', methods=['GET'])(inventory_get)
api_bp.route('/ansible/inventory', methods=['POST'])(inventory_post)

def get_file_path(filename):
    return os.path.join(ANSIBLE_FILES_DIR, filename)

file_get, file_post = create_file_api_handlers(get_file_path, name_prefix='file')
api_bp.route('/ansible/files/<path:filename>', methods=['GET'])(file_get)
api_bp.route('/ansible/files/<path:filename>', methods=['POST'])(file_post)

def get_template_path(filename):
    return os.path.join(ANSIBLE_TEMPLATES_DIR, filename)

template_get, template_post = create_file_api_handlers(get_template_path, name_prefix='template')
api_bp.route('/ansible/templates/<path:filename>', methods=['GET'])(template_get)
api_bp.route('/ansible/templates/<path:filename>', methods=['POST'])(template_post)

@api_bp.route('/ansible/files', methods=['GET'])
def api_ansible_files_list():
    return list_files_in_dir(ANSIBLE_FILES_DIR)

@api_bp.route('/ansible/templates', methods=['GET'])
def api_ansible_templates_list():
    return list_files_in_dir(ANSIBLE_TEMPLATES_DIR)

@api_bp.route('/ansible/status/<ip>', methods=['GET'])
def api_ansible_status(ip):
    result = get_ansible_mark(ip)
    return jsonify(result)

@api_bp.route('/logs/ansible', methods=['GET'])
def api_logs_ansible():
    try:
        result = subprocess.run(
            ['journalctl', '-u', 'ansible-api.service', '-n', '300', '--no-pager'],
            capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().split('\n')
        filtered_lines = []
        filter_keywords = [
            'Начинаем фоновый пинг хостов',
            'Фоновый пинг завершён',
            'Начинаем анализ логов Ansible',
            '[Пропущено'
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
            line = re.sub(r'([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})', r'<span style="color:#0ca678; font-weight:bold; font-family:monospace">\1</span>', line)
            line = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', r'<span style="color:#087f5b; font-weight:bold; font-family:monospace">\g<0></span>', line)
            line = re.sub(r'(\w{3} \d{1,2} \d{2}:\d{2}:\d{2})', r'<span style="color:#adb5bd">\1</span>', line)
            colored_lines.append(line)
        return jsonify(colored_lines[-100:]), 200
    except subprocess.CalledProcessError as e:
        logging.error(f'Ошибка выполнения journalctl: {e}')
        msg = f"Ошибка выполнения journalctl: {e}"
        if e.stderr:
            msg += f". Stderr: {e.stderr}"
        return jsonify([f"<span style='color:#ff6b6b; font-size:14px'>{msg}</span>"]), 500
    except Exception as e:
        logging.error(f'Ошибка чтения логов Ansible: {e}')
        return jsonify([f"<span style='color:#ff375f; font-size:14px'>Ошибка: {str(e)}</span>"]), 500

@api_bp.route('/host/reboot', methods=['POST'])
def api_host_reboot():
    data = request.get_json()
    ip = data.get('ip')
    if not ip or ip == '—':
        return jsonify({'status': 'error', 'msg': 'Неверный IP-адрес'}), 400
    try:
        cmd = f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} 'reboot'"
        result = subprocess.run(cmd, shell=True, check=True, timeout=10, capture_output=True, text=True)
        logging.info(f'Команда перезагрузки отправлена на {ip}')
        return jsonify({'status': 'ok', 'msg': f'Команда перезагрузки отправлена на {ip}'}), 200
    except subprocess.TimeoutExpired as e:
        msg = f'Команда перезагрузки отправлена на {ip} (таймаут ожидания ответа)'
        logging.warning(msg + f" | Stderr: {e.stderr if e.stderr else 'N/A'}")
        return jsonify({'status': 'ok', 'msg': msg}), 200
    except subprocess.CalledProcessError as e:
        msg = f'Команда перезагрузки отправлена на {ip} (возможна ошибка SSH)'
        detailed_msg = f"{msg}. Код ошибки SSH: {e.returncode}"
        if e.stderr:
            detailed_msg += f". Вывод SSH: {e.stderr.strip()}"
        logging.warning(detailed_msg)
        return jsonify({'status': 'ok', 'msg': msg}), 200
    except Exception as e:
        msg = f'Неизвестная ошибка при отправке команды перезагрузки на {ip}: {e}'
        logging.error(msg)
        return jsonify({'status': 'error', 'msg': msg}), 500

@api_bp.route('/host/wol', methods=['POST'])
def api_host_wol():
    data = request.get_json()
    mac = data.get('mac')
    if not mac or mac == '—':
        return jsonify({'status': 'error', 'msg': 'Неверный MAC-адрес'}), 400
    try:
        subprocess.run(['wakeonlan', mac], capture_output=True, text=True, check=True)
        logging.info(f'Wake-on-LAN пакет отправлен на {mac}')
        return jsonify({'status': 'ok', 'msg': f'Wake-on-LAN пакет отправлен на {mac}.'}), 200
    except subprocess.CalledProcessError as e:
        error_msg = f"Ошибка выполнения wakeonlan: {e.stderr.strip() if e.stderr else str(e)}"
        logging.error(error_msg)
        return jsonify({'status': 'error', 'msg': error_msg}), 500
    except FileNotFoundError:
        error_msg = "Команда 'wakeonlan' не найдена. Установите пакет 'wakeonlan'."
        logging.error(error_msg)
        return jsonify({'status': 'error', 'msg': error_msg}), 500
    except Exception as e:
        error_msg = f"Внутренняя ошибка сервера: {str(e)}"
        logging.error(error_msg, exc_info=True)
        return jsonify({'status': 'error', 'msg': error_msg}), 500

@api_bp.route('/host/shutdown', methods=['POST'])
def api_host_shutdown():
    data = request.get_json()
    ip = data.get('ip')
    if not ip or ip == '—':
        return jsonify({'status': 'error', 'msg': 'Неверный IP-адрес'}), 400
    try:
        cmd = f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} 'shutdown -h now'"
        result = subprocess.run(cmd, shell=True, check=True, timeout=10, capture_output=True, text=True)
        logging.info(f'Команда выключения отправлена на {ip}')
        msg = f'Команда выключения отправлена на {ip}'
        if result.stderr:
            msg += f" (Stderr: {result.stderr.strip()})"
        return jsonify({'status': 'ok', 'msg': msg}), 200
    except subprocess.TimeoutExpired as e:
        msg = f'Команда выключения отправлена на {ip} (таймаут ожидания ответа)'
        logging.warning(msg + f" | Stderr: {e.stderr if e.stderr else 'N/A'}")
        return jsonify({'status': 'ok', 'msg': msg}), 200
    except subprocess.CalledProcessError as e:
        msg = f'Команда выключения отправлена на {ip} (возможна ошибка SSH)'
        detailed_msg = f"{msg}. Код ошибки SSH: {e.returncode}"
        if e.stderr:
            detailed_msg += f". Вывод SSH: {e.stderr.strip()}"
        logging.warning(detailed_msg)
        return jsonify({'status': 'ok', 'msg': msg}), 200
    except Exception as e:
        msg = f'Неизвестная ошибка при отправке команды выключения на {ip}: {e}'
        logging.error(msg, exc_info=True)
        return jsonify({'status': 'error', 'msg': msg}), 500
