from flask import Blueprint, render_template
import datetime

from config import LOCAL_OFFSET, ANSIBLE_FILES_DIR
from db_utils import get_db
from services import sync_inventory_hosts

web_bp = Blueprint('web', __name__)

@web_bp.route('/')
def dashboard():
    sync_inventory_hosts()
    db = get_db()
    rows = db.execute('''
        SELECT h.mac, h.ip, h.ts
        FROM hosts h
        INNER JOIN (
            SELECT mac, MAX(ts) AS last_ts FROM hosts GROUP BY mac
        ) grp
        ON h.mac = grp.mac AND h.ts = grp.last_ts
        ORDER BY ts DESC
    ''').fetchall()
    hosts = []
    for mac, ip, ts_utc in rows:
        last_seen = datetime.datetime.fromisoformat(ts_utc) + LOCAL_OFFSET
        hosts.append({
            'mac': mac,
            'ip': ip or '—',
            'last': last_seen.strftime('%H:%M:%S'),
        })
    return render_template(
        'dashboard.html',
        hosts=hosts,
        ansible_files_path=ANSIBLE_FILES_DIR,
    )
