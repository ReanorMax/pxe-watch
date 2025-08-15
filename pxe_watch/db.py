import datetime
import logging
import pathlib
import sqlite3
import os

from .config import DB_PATH


def get_db():
    os.makedirs(pathlib.Path(DB_PATH).parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS hosts (
            mac TEXT PRIMARY KEY,
            ip TEXT,
            stage TEXT,
            details TEXT,
            ts TEXT,
            first_ts TEXT
        )'''
    )
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS host_status (
            ip TEXT PRIMARY KEY,
            is_online BOOLEAN,
            last_checked TEXT
        )'''
    )
    conn.execute(
        '''CREATE TABLE IF NOT EXISTS playbook_status (
            ip TEXT PRIMARY KEY,
            status TEXT,
            updated TEXT
        )'''
    )
    return conn


def update_host_online_status(ip: str, is_online: bool) -> None:
    try:
        with get_db() as db:
            db.execute(
                '''INSERT INTO host_status (ip, is_online, last_checked)
                   VALUES (?, ?, ?)
                   ON CONFLICT(ip) DO UPDATE SET
                     is_online = excluded.is_online,
                     last_checked = excluded.last_checked''',
                (ip, is_online, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')),
            )
    except Exception as e:
        logging.error(f"Ошибка обновления статуса для {ip}: {e}")


def set_playbook_status(ip: str, status: str) -> None:
    try:
        with get_db() as db:
            db.execute(
                '''INSERT INTO playbook_status (ip, status, updated)
                   VALUES (?, ?, ?)
                   ON CONFLICT(ip) DO UPDATE SET
                     status = excluded.status,
                     updated = excluded.updated''',
                (ip, status, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')),
            )
        logging.info(f"Статус Ansible для {ip} установлен в '{status}'")
    except Exception as e:
        logging.error(
            f"Ошибка при установке статуса Ansible для {ip}: {e}", exc_info=True
        )
