import datetime
import logging
import subprocess
import configparser

from flask import request, jsonify

from config import ANSIBLE_PLAYBOOK, ANSIBLE_INVENTORY
from db_utils import get_db
from . import api_bp
from extensions import socketio


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


@api_bp.route('/ansible/run', methods=['POST'])
def api_ansible_run():
    try:
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
                socketio.emit(
                    'task_update',
                    {
                        'mac': mac,
                        'task_name': 'playbook.yml',
                        'status': 'running',
                        'step': 0,
                        'total_steps': 10,
                        'started_at': started,
                    },
                )
        result = subprocess.run(
            ["ansible-playbook", ANSIBLE_PLAYBOOK, "-i", ANSIBLE_INVENTORY],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logging.info("ansible-playbook completed successfully")
            return jsonify({'status': 'ok', 'data': result.stdout}), 200
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
