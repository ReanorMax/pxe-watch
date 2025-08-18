import logging
from flask import Flask

from logtail import logtail_bp
from api import api_bp
from web import web_bp
from tasks import start_background_tasks

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def create_app() -> Flask:
    app = Flask(__name__, static_folder='static')
    app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

    app.register_blueprint(logtail_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(web_bp)

    return app


app = create_app()
if __name__ == '__main__':
    start_background_tasks()
    app.run(host='0.0.0.0', port=5000)
