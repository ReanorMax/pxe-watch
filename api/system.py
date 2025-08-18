from flask import jsonify
import pathlib
import logging

from config import DB_PATH
from . import api_bp


@api_bp.route('/clear-db', methods=['POST'])
def api_clear_db():
    try:
        pathlib.Path(DB_PATH).unlink(missing_ok=True)
        logging.info('База данных очищена')
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logging.error(f'Ошибка при очистке базы данных: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500
