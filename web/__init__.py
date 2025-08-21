from flask import Blueprint, render_template
import datetime
import logging

from config import LOCAL_OFFSET, ANSIBLE_FILES_DIR
from db_utils import get_db
from services import get_install_status, sync_inventory_hosts

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
        install_result = get_install_status(ip)
        install_status = install_result.get('status')
        if install_status == 'completed':
            try:
                install_date_str = install_result.get('install_date')
                install_dt = datetime.datetime.fromisoformat(
                    install_date_str.replace('Z', '+00:00')
                )
                if install_dt.tzinfo is None:
                    install_dt = install_dt.replace(tzinfo=datetime.timezone.utc)
                install_dt = install_dt.astimezone(
                    datetime.timezone.utc
                ) + LOCAL_OFFSET
                date_str = install_dt.strftime('%d.%m.%Y %H:%M')
                stage_label = f'✅ Установка: {date_str}'
            except Exception as e:
                logging.warning(
                    f"Ошибка парсинга даты установки для {ip}: {e}"
                )
                stage_label = '✅ Установка: завершена (дата неизвестна)'
        elif install_status == 'pending':
            stage_label = STAGE_LABELS.get(stage, '—') + ' ⏳ Установка: в процессе'
        elif install_status == 'failed':
            stage_label = '❌ Установка: ошибка'
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
        if stage == 'debian_install' or install_status == 'pending':
            installing_count += 1
        if install_status == 'completed':
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
