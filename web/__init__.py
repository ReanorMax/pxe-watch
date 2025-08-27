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
    now = datetime.datetime.utcnow()
    for mac, ip, ts_utc in rows:
        last_seen_utc = datetime.datetime.fromisoformat(ts_utc)
        last_seen_local = last_seen_utc + LOCAL_OFFSET
        
        # Calculate status based on last seen time
        time_diff = now - last_seen_utc
        if time_diff.total_seconds() > 3600:  # 1 hour
            status = 'offline'
        elif time_diff.total_seconds() > 1800:  # 30 minutes
            status = 'warning'
        else:
            status = 'online'
            
        hosts.append({
            'mac': mac,
            'ip': ip or '—',
            'last': last_seen_local.strftime('%H:%M:%S'),
            'status': status,
        })
    return render_template(
        'dashboard.html',
        hosts=hosts,
        ansible_files_path=ANSIBLE_FILES_DIR,
    )
