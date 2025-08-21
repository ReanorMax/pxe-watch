import os
import pathlib
import sqlite3

from config import DB_PATH


def get_db():
    """Create and initialize a SQLite database connection.

    Ensures the database file and required tables exist before returning the
    connection. The schema includes tables used by both the main application
    and auxiliary services.

    Returns:
        sqlite3.Connection: ready-to-use database connection
    """
    os.makedirs(pathlib.Path(DB_PATH).parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row

    # Table with host info and current installation stage
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS hosts (
            mac TEXT PRIMARY KEY,
            ip TEXT,
            stage TEXT,
            details TEXT,
            ts TEXT,
            first_ts TEXT
        )
        """
    )

    # Store ping results to track host online status
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS host_status (
            ip TEXT PRIMARY KEY,
            is_online BOOLEAN,
            last_checked TEXT
        )
        """
    )

    # Status of Ansible playbook execution
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS playbook_status (
            ip TEXT PRIMARY KEY,
            status TEXT,
            updated TEXT
        )
        """
    )

    # Status of OS installation completion
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS install_status (
            ip TEXT PRIMARY KEY,
            status TEXT,
            completed_at TEXT
        )
        """
    )

    return conn
