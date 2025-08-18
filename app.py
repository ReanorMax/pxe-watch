#!/usr/bin/env python3
"""Main application entry point."""
import os
import logging
import subprocess
from flask import Flask

from logtail import logtail_bp
from api import api_bp
from web import web_bp
from tasks import start_background_tasks

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__, static_folder='static')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

app.register_blueprint(logtail_bp)
app.register_blueprint(api_bp)
app.register_blueprint(web_bp)

start_background_tasks()


def start_ansible_service() -> None:
    """Запускает дополнительный сервис ansible_service.py в фоне."""
    service_path = os.path.join(os.path.dirname(__file__), 'ansible_service.py')
    try:
        subprocess.Popen(['python3', service_path])
        logging.info('Ansible service started')
    except Exception as e:
        logging.error(f'Failed to start ansible service: {e}')


if __name__ == '__main__':
    start_ansible_service()
    app.run(host='0.0.0.0', port=5000)
