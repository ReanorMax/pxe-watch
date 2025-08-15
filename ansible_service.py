#!/usr/bin/env python3
"""
PXE Dashboard + Ansible + WebSocket
"""
import os
import pathlib
import datetime
import subprocess
import logging
import sqlite3
import uuid
import configparser

from flask import Flask, render_template, request, jsonify, abort
from flask_socketio import SocketIO, emit
import requests

# ==== Конфигурация ====
DB_PATH = os.getenv('DB_PATH', '/opt/pxewatch/pxe.db')
PRESEED_PATH = os.getenv('PRESEED_PATH', '/var/www/html/debian12/preseed.cfg')
DNSMASQ_PATH = '/etc/dnsmasq.conf'
BOOT_IPXE_PATH = '/srv/tftp/boot.ipxe'
AUTOEXEC_IPXE_PATH = '/srv/tftp/autoexec.ipxe'
LOGS_DIR = os.getenv('LOGS_DIR', '/var/log/installer')
ONLINE_TIMEOUT = int(os.getenv('ONLINE_TIMEOUT', 300))
LOCAL_OFFSET = datetime.timedelta(hours=int(os.getenv('LOCAL_OFFSET', 3)))
ANSIBLE_PLAYBOOK = '/root/ansible/playbook.yml'
ANSIBLE_INVENTORY = '/root/ansible/inventory.ini'
ANSIBLE_FILES_DIR = '/root/ansible/files'
ANSIBLE_TEMPLATES_DIR = '/root/ansible/templates'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# ==== Вспомогательные функции ====
def get_db():
    os.makedirs(pathlib.Path(DB_PATH).parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute('''
        CREATE TABLE IF NOT EXISTS hosts (
            mac TEXT PRIMARY KEY,
            ip TEXT,
            stage TEXT,
            details TEXT,
            ts TEXT,
            first_ts TEXT
        )
    ''')
    conn.execute('''
        CREATE TABLE IF NOT EXISTS ansible_tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mac TEXT,
            task_name TEXT,
            status TEXT,
            step INTEGER DEFAULT 0,
            total_steps INTEGER DEFAULT 1,
            started_at TEXT,
            finished_at TEXT,
            log TEXT
        )
    ''')
    return conn

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

# ==== API: регистрация хоста ====
@app.route('/api/register', methods=['GET', 'POST'])
def api_register():
    mac = request.values.get('mac', '').lower()
    ip = request.values.get('ip', request.remote_addr)
    stage = request.values.get('stage', 'unknown')
    details = request.values.get('details', '')
    if not mac:
        logging.warning('Отсутствует MAC-адрес в запросе')
        return 'Missing MAC', 400
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with get_db() as db:
            db.execute('''
                INSERT INTO hosts(mac, ip, stage, details, ts, first_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(mac) DO UPDATE SET
                    ip = excluded.ip,
                    stage = excluded.stage,
                    details = excluded.details,
                    ts = excluded.ts,
                    first_ts = COALESCE(hosts.first_ts, excluded.ts)
            ''', (mac, ip, stage, details, ts, ts))
        logging.info(f'Зарегистрирован или обновлен хост с MAC: {mac}')
    except Exception as e:
        logging.error(f'Ошибка при регистрации хоста: {e}')
        return 'Error', 500

    # ==== Запускаем playbook ====
    try:
        subprocess.Popen([
            "ansible-playbook",
            ANSIBLE_PLAYBOOK,
            "-i",
            ANSIBLE_INVENTORY
        ])
        logging.info(f'Ansible-playbook запущен для MAC {mac}')
    except Exception as e:
        logging.error(f'Ошибка запуска playbook: {e}')

    return 'OK', 200

# ==== API: Ansible ====
@app.route('/api/ansible/task/<mac>')
def api_ansible_task(mac):
    with get_db() as db:
        task = db.execute('''
            SELECT * FROM ansible_tasks
            WHERE mac = ? ORDER BY started_at DESC LIMIT 1
        ''', (mac,)).fetchone()
        return jsonify(dict(task) if task else {})

@app.route('/api/ansible/clients')
def api_ansible_clients():
    with get_db() as db:
        rows = db.execute('''
            SELECT mac, task_name, status, step, total_steps, started_at
            FROM ansible_tasks ORDER BY started_at DESC
        ''').fetchall()
        return jsonify([dict(r) for r in rows])

@app.route('/api/ansible/run', methods=['POST'])
def api_ansible_run():
    try:
        macs = get_macs_from_inventory()
        started = datetime.datetime.utcnow().isoformat()
        with get_db() as db:
            for mac in macs:
                db.execute('''
                    INSERT INTO ansible_tasks(mac, task_name, status, step, total_steps, started_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                ''', (mac, 'playbook.yml', 'running', 0, 10, started))
                socketio.emit('task_update', {
                    'mac': mac,
                    'task_name': 'playbook.yml',
                    'status': 'running',
                    'step': 0,
                    'total_steps': 10,
                    'started_at': started
                })
        resp = requests.post('http://localhost:5002/api/run-playbook', timeout=60)
        if resp.status_code == 200:
            return jsonify({'status': 'ok', 'data': resp.json()}), 200
        else:
            return jsonify({'status': 'error', 'msg': resp.text}), resp.status_code
    except requests.exceptions.ConnectionError:
        return jsonify({'status': 'error', 'msg': 'Сервис ansible-api недоступен (порт 5002)'}), 503

# ==== API: логи ansible-api.service ====
@app.route('/api/logs/ansible')
def api_logs_ansible():
    try:
        result = subprocess.run(
            ['journalctl', '-u', 'ansible-api.service', '-n', '50', '--no-pager'],
            capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().split('\n')
        return jsonify(lines[-100:]), 200
    except Exception as e:
        return jsonify([f"Ошибка чтения логов: {str(e)}"]), 500

# ==== Веб-интерфейс ====
@app.route('/')
def dashboard():
    db = get_db()
    now = datetime.datetime.utcnow()
    rows = db.execute('''
        SELECT h.mac, h.ip, h.stage, h.details, h.ts,
               (SELECT ts FROM hosts
                WHERE mac = h.mac AND stage IN ('dhcp', 'ipxe_started')
                ORDER BY ts ASC LIMIT 1) AS ipxe_ts
        FROM hosts h
        INNER JOIN (
            SELECT mac, MAX(ts) AS last_ts FROM hosts GROUP BY mac
        ) grp
        ON h.mac = grp.mac AND h.ts = grp.last_ts
        ORDER BY ipxe_ts DESC
    ''').fetchall()
    STAGE_LABELS = {
        'dhcp': 'IP получен',
        'ipxe_started': 'Загрузка iPXE',
        'debian_install': 'Идёт установка',
        'reboot': 'Перезагрузка',
        'unknown': 'Неизвестно'
    }
    hosts = []
    for r in rows:
        mac, ip, stage, details, ts_utc, ipxe_utc = r
        dt_last = datetime.datetime.fromisoformat(ts_utc) + LOCAL_OFFSET
        stage_label = STAGE_LABELS.get(stage, stage)
        online = (now + LOCAL_OFFSET - dt_last).total_seconds() < ONLINE_TIMEOUT
        hosts.append({
            'mac': mac,
            'ip': ip or '—',
            'stage': stage_label,
            'last': dt_last.strftime('%H:%M:%S'),
            'online': online,
            'details': details or '',
            'preseed_path': PRESEED_PATH
        })
    return render_template('dashboard.html', hosts=hosts)

# ==== Запуск ====
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5002)
