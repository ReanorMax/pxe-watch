import datetime
import logging

from db_utils import get_db


def register_host(mac: str, ip: str, stage: str, details: str) -> None:
    """Insert or update host registration info in the database.

    Raises:
        ValueError: if ``mac`` is empty.
        Exception: if database operation fails.
    """
    if not mac:
        logging.warning('Отсутствует MAC-адрес в запросе')
        raise ValueError("Missing MAC")

    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    with get_db() as db:
        db.execute(
            '''
            INSERT INTO hosts(mac, ip, stage, details, ts, first_ts)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(mac) DO UPDATE SET
                ip = excluded.ip,
                stage = excluded.stage,
                details = excluded.details,
                ts = excluded.ts,
                first_ts = COALESCE(hosts.first_ts, excluded.ts)
            ''',
            (mac, ip, stage, details, ts, ts),
        )
    logging.info(f'Зарегистрирован или обновлен хост с MAC: {mac}')
