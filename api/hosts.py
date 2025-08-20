from flask import request, jsonify
import subprocess
import logging
import threading
import re

from config import (
    SSH_PASSWORD,
    SSH_USER,
    SSH_OPTIONS,
    ANSIBLE_PLAYBOOK,
    ANSIBLE_INVENTORY,
)
from . import api_bp
from services.registration import register_host
from services import set_playbook_status


def parse_playbook_summary(output: str) -> dict[str, str]:
    """Разобрать PLAY RECAP и вернуть статус по каждому хосту.

    ``ansible-playbook`` может выводить строки ``PLAY RECAP`` с полями в
    произвольном порядке, например ``unreachable`` может идти до ``failed``.
    Прежняя реализация опиралась на конкретный порядок и всегда возвращала
    пустой результат, что оставляло статус ``running``.  Здесь мы разбираем
    каждый токен и ищем значения ``failed`` и ``unreachable`` независимо от
    их позиции.
    """
    result: dict[str, str] = {}
    if "PLAY RECAP" not in output:
        return result

    recap = output.split("PLAY RECAP", 1)[1]
    for line in recap.splitlines():
        line = line.strip()
        if not line:
            continue
        m = re.match(r"^(\S+)\s*:\s*(.*)$", line)
        if not m:
            continue
        host, stats = m.groups()
        failed = unreachable = None
        for token in stats.split():
            if token.startswith("failed="):
                try:
                    failed = int(token.split("=", 1)[1])
                except ValueError:
                    failed = None
            elif token.startswith("unreachable="):
                try:
                    unreachable = int(token.split("=", 1)[1])
                except ValueError:
                    unreachable = None
        if failed is not None and unreachable is not None:
            result[host] = "ok" if failed == 0 and unreachable == 0 else "failed"
    return result


def run_playbook_async(ip: str) -> None:
    """Запустить ansible-playbook в фоне и обновить статус в БД."""
    set_playbook_status(ip, 'running')

    def worker():
        cmd = [
            "ansible-playbook",
            ANSIBLE_PLAYBOOK,
            "-i",
            ANSIBLE_INVENTORY,
        ]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True)
            summary = parse_playbook_summary(proc.stdout + '\n' + proc.stderr)
            if summary:
                for host_ip, status in summary.items():
                    set_playbook_status(host_ip, status)
            else:
                set_playbook_status(ip, 'failed')
        except Exception as e:
            logging.error(f'Ошибка выполнения playbook: {e}')
            set_playbook_status(ip, 'failed')

    threading.Thread(target=worker, daemon=True).start()


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
    try:
        run_playbook_async(ip)
        logging.info(f'Ansible-playbook запущен для MAC {mac}')
    except Exception as e:
        logging.error(f'Ошибка запуска playbook: {e}')
    return 'OK', 200


@api_bp.route('/host/reboot', methods=['POST'])
def api_host_reboot():
    data = request.get_json()
    ip = data.get('ip')
    if not ip or ip == '—':
        return jsonify({'status': 'error', 'msg': 'Неверный IP-адрес'}), 400
    try:
        cmd = f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} 'reboot'"
        subprocess.run(cmd, shell=True, check=True, timeout=10, capture_output=True, text=True)
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
