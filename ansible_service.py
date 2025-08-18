#!/usr/bin/env python3
"""
PXE Dashboard + Ansible + WebSocket
"""
import datetime
import logging
import subprocess
import configparser

from flask import Flask, jsonify
from flask_socketio import SocketIO
from config import ANSIBLE_PLAYBOOK, ANSIBLE_INVENTORY
from api import api_bp
from web import web_bp
from db_utils import get_db

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")
app.register_blueprint(api_bp)
app.register_blueprint(web_bp)

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

# Route specific to ansible_service: launch playbook and broadcast progress
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
        result = subprocess.run(
            ["ansible-playbook", ANSIBLE_PLAYBOOK, "-i", ANSIBLE_INVENTORY],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
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

# ==== Запуск ====
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5002)
