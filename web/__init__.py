from flask import Blueprint, render_template
import datetime
import logging

from config import LOCAL_OFFSET, ANSIBLE_FILES_DIR
from db_utils import get_db
from services import get_ansible_mark, sync_inventory_hosts

web_bp = Blueprint('web', __name__)

@web_bp.route('/')
def dashboard():
    sync_inventory_hosts()
    db = get_db()
    rows = db.execute('''
        SELECT h.mac, h.ip, h.stage, h.details, h.ts,
               (SELECT ts FROM hosts
                WHERE mac = h.mac AND stage IN ('dhcp', 'ipxe_started')
                ORDER BY ts ASC LIMIT 1) AS ipxe_ts,
               COALESCE(s.is_online, 0) AS is_online
        FROM hosts h
        LEFT JOIN host_status s ON h.ip = s.ip
        INNER JOIN (
            SELECT mac, MAX(ts) AS last_ts FROM hosts GROUP BY mac
        ) grp
        ON h.mac = grp.mac AND h.ts = grp.last_ts
        ORDER BY ipxe_ts DESC
    ''').fetchall()
    STAGE_LABELS = {
        'dhcp': 'IP получен',
        'ipxe_started': 'Загрузка iPXE',
        'debian_install': 'Идёт установка',
        'reboot': 'Перезагрузка'
    }
    hosts = []
    total_hosts = 0
    online_count = 0
    installing_count = 0
    completed_count = 0
    for row in rows:
        mac, ip, stage, details, ts_utc, ipxe_utc, db_is_online = row
        last_seen = datetime.datetime.fromisoformat(ts_utc) + LOCAL_OFFSET
        is_online = bool(db_is_online)
        ansible_result = get_ansible_mark(ip)
        ansible_status = ansible_result.get('status')
        if ansible_status == 'ok':
            try:
                install_date_str = ansible_result['install_date']
                install_dt = datetime.datetime.fromisoformat(
                    install_date_str.replace('Z', '+00:00')
                )
                install_dt = install_dt.astimezone(
                    datetime.timezone.utc
                ) + LOCAL_OFFSET
                date_str = install_dt.strftime('%d.%m.%Y %H:%M')
                version = ansible_result.get('version', '')
                stage_label = f'✅ Ansible: {date_str}'
                if version:
                    stage_label += f' (v{version})'
            except Exception as e:
                logging.warning(
                    f"Ошибка парсинга даты в ansible_mark.json для {ip}: {e}"
                )
                stage_label = '✅ Ansible: завершён (дата неизвестна)'
        elif ansible_status == 'pending':
            stage_label = STAGE_LABELS.get(stage, '—') + ' ⏳ Ansible: в процессе'
        else:
            stage_label = STAGE_LABELS.get(stage, '—')
        hosts.append({
            'mac': mac,
            'ip': ip or '—',
            'stage': stage_label,
            'last': last_seen.strftime('%H:%M:%S'),
            'online': is_online,
            'details': details or '',
        })
        total_hosts += 1
        if is_online:
            online_count += 1
        if stage == 'debian_install' or ansible_status == 'pending':
            installing_count += 1
        if ansible_status == 'ok':
            completed_count += 1
    return render_template(
        'dashboard.html',
        hosts=hosts,
        stage_labels=STAGE_LABELS,
        ansible_files_path=ANSIBLE_FILES_DIR,
        total_hosts=total_hosts,
        online_hosts=online_count,
        installing_hosts=installing_count,
        completed_hosts=completed_count,
    )
