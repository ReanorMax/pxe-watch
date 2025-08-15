import logging
import threading
from flask import Flask

from .routes.api import api_bp
from .routes.web import web_bp
from .tasks import (
    check_ansible_marks_background,
    parse_ansible_logs,
    ping_hosts_background,
)


def create_app() -> Flask:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    app = Flask(__name__)
    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

    threading.Thread(target=ping_hosts_background, daemon=True).start()
    threading.Thread(target=parse_ansible_logs, daemon=True).start()
    threading.Thread(target=check_ansible_marks_background, daemon=True).start()
    return app
