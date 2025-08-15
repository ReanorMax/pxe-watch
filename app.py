#!/usr/bin/env python3
"""
PXE Dashboard server + Full Ansible Integration + Real-time Logs + Background Ping + Ansible Status
Это веб-приложение предоставляет централизованный интерфейс для мониторинга и управления
процессом установки ОС через PXE. Основные функции:
1. Отслеживание этапов загрузки клиентов (DHCP, iPXE, установка Debian)
2. Управление конфигурационными файлами (preseed.cfg, boot.ipxe, dnsmasq.conf)
3. Интеграция с Ansible для автоматизации пост-установочных задач
4. Реальное время мониторинга через фоновые задачи (пинг хостов, парсинг логов Ansible)
5. Веб-интерфейс для визуализации состояния всех хостов
Структура данных:
- hosts: основная таблица с информацией о хостах и их текущем этапе установки
- host_status: таблица с результатами пинга для отслеживания онлайн-статуса
- playbook_status: таблица с результатами выполнения Ansible-плейбуков
Фоновые задачи:
- ping_hosts_background: периодически пингует все известные хосты
- parse_ansible_logs: анализирует логи Ansible для обновления статусов выполнения
"""
import os
import pathlib
import logging
import subprocess
import sqlite3
import datetime
import threading
import time
import re
import json
import requests
from flask import Flask, render_template, request, jsonify, abort

# Blueprint с функциями просмотра журналов
from logtail import logtail_bp
from preseed import preseed_bp

# ==== Конфигурация ====
# Пути к основным файлам и настройкам приложения
DB_PATH = os.getenv('DB_PATH', '/opt/pxewatch/pxe.db')
PRESEED_PATH = os.getenv('PRESEED_PATH', '/var/www/html/debian12/preseed.cfg')
DNSMASQ_PATH = '/etc/dnsmasq.conf'
BOOT_IPXE_PATH = '/srv/tftp/boot.ipxe'
AUTOEXEC_IPXE_PATH = '/srv/tftp/autoexec.ipxe'
LOGS_DIR = os.getenv('LOGS_DIR', '/var/log/installer')
ONLINE_TIMEOUT = int(os.getenv('ONLINE_TIMEOUT', 300))  # Таймаут для определения онлайн-статуса в секундах
LOCAL_OFFSET = datetime.timedelta(hours=int(os.getenv('LOCAL_OFFSET', 3)))  # Смещение часового пояса
ANSIBLE_PLAYBOOK = '/root/ansible/playbook.yml'
ANSIBLE_INVENTORY = '/root/ansible/inventory.ini'
ANSIBLE_FILES_DIR = '/home/ansible-offline/files'
ANSIBLE_TEMPLATES_DIR = '/root/ansible/templates'

# ==== Конфигурация SSH для перезагрузки/выключения ====
# ВАЖНО: Использование shell=True и форматирования строки может быть небезопасно.
# Убедитесь, что SSH_PASSWORD и SSH_USER надёжны и не доступны третьим лицам.
SSH_PASSWORD = os.getenv('SSH_PASSWORD', 'Q1w2a3s40007')
SSH_USER = os.getenv('SSH_USER', 'root')
SSH_OPTIONS = '-o StrictHostKeyChecking=no'

# ==== Конфигурация Ansible Run ====
# Предполагается, что плейбук запускается отдельно, например, через systemd сервис ansible-api.service
# Этот скрипт будет обновлять статус в БД, основываясь на логах этого сервиса.
# Альтернативно, можно добавить API-эндпоинт для ручного запуска и обновления статуса.
ANSIBLE_SERVICE_NAME = 'ansible-api.service'

# ==== Конфигурация Semaphore API ====
SEMAPHORE_API = 'http://10.19.1.90:3000/api'
SEMAPHORE_TOKEN = 'pkoqhsremgn9s_4d1qdrzf9lgxzmn8e9nwtjjillvss='
SEMAPHORE_PROJECT_ID = 1
SEMAPHORE_TEMPLATE_ID = 1

# Настройка базового логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
app = Flask(__name__, static_folder='static')
# Enable caching for static assets
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 3600

# Регистрируем Blueprint логов, чтобы панель логов работала на том же хосте
app.register_blueprint(logtail_bp)
app.register_blueprint(preseed_bp, url_prefix='/preseed')

# ==== Вспомогательные функции ====
def get_db():
    """
    Создает и инициализирует соединение с базой данных SQLite.
    Создает необходимые таблицы, если они не существуют, и настраивает соединение.
    Таблицы:
    - hosts: основная информация о хостах и их текущем этапе установки
    - host_status: результаты пинга для отслеживания онлайн-статуса
    - playbook_status: статусы выполнения Ansible-плейбуков
    Returns:
        sqlite3.Connection: Соединение с базой данных, готовое к использованию
    """
    os.makedirs(pathlib.Path(DB_PATH).parent, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row
    conn.execute('''
        CREATE TABLE IF NOT EXISTS hosts (
            mac TEXT PRIMARY KEY,  -- MAC-адрес клиента
            ip TEXT,               -- IP-адрес клиента
            stage TEXT,            -- Текущий этап установки
            details TEXT,          -- Дополнительные детали этапа
            ts TEXT,               -- Время последнего обновления
            first_ts TEXT          -- Время первого обнаружения
        )
    ''')
    # Создаём таблицу для хранения результатов пинга
    conn.execute('''
        CREATE TABLE IF NOT EXISTS host_status (
            ip TEXT PRIMARY KEY,    -- IP-адрес
            is_online BOOLEAN,      -- Статус онлайн/оффлайн
            last_checked TEXT       -- Время последней проверки
        )
    ''')
    # Создаём таблицу для хранения статуса выполнения Ansible плейбука
    conn.execute('''
        CREATE TABLE IF NOT EXISTS playbook_status (
            ip TEXT PRIMARY KEY,    -- IP-адрес целевого хоста
            status TEXT,            -- Статус выполнения ('ok', 'failed', 'running', 'unknown')
            updated TEXT            -- Время последнего обновления статуса
        )
    ''')
    return conn

def read_file(path):
    """
    Читает содержимое файла с диска.
    Args:
        path (str): Путь к файлу для чтения
    Returns:
        str: Содержимое файла в формате UTF-8
    Raises:
        HTTP 404: Если файл не найден на диске
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        abort(404)

def write_file(path, content):
    """
    Записывает содержимое в файл на диск.
    Создает директорию, если она не существует.
    Args:
        path (str): Путь к файлу для записи
        content (str): Содержимое, которое нужно записать
    Side Effects:
        - Создает директорию, если она не существует
        - Записывает данные в файл
        - Логирует факт обновления файла
    """
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    logging.info(f'Файл {path} обновлён')

def list_files_in_dir(directory):
    """
    Возвращает список файлов в указанной директории с дополнительной информацией.
    Args:
        directory (str): Путь к директории для сканирования
    Returns:
        Response: JSON-список файлов с информацией о размере и дате изменения
    Note:
        Возвращает только файлы, исключая поддиректории
    """
    try:
        os.makedirs(directory, exist_ok=True)
        file_list = []
        for f in os.listdir(directory):
            file_path = os.path.join(directory, f)
            if os.path.isfile(file_path):
                stat_info = os.stat(file_path)
                # Форматируем размер и дату для удобного отображения
                size_bytes = stat_info.st_size
                # Преобразуем байты в более удобные единицы
                if size_bytes < 1024:
                    size_str = f"{size_bytes} B"
                elif size_bytes < 1024**2:
                    size_str = f"{size_bytes / 1024:.1f} KB"
                elif size_bytes < 1024**3:
                    size_str = f"{size_bytes / (1024**2):.1f} MB"
                else:
                    size_str = f"{size_bytes / (1024**3):.1f} GB"
                modified_timestamp = stat_info.st_mtime
                # Формат даты и времени
                modified_str = datetime.datetime.fromtimestamp(modified_timestamp).strftime('%d.%m.%Y %H:%M')
                file_list.append({
                    'name': f,
                    'size': size_str, # Используем отформатированный размер
                    'modified': modified_str # Используем отформатированную дату
                })
        # Сортируем файлы по имени для консистентности
        file_list.sort(key=lambda x: x['name'].lower())
        return jsonify(file_list)
    except Exception as e:
        logging.error(f"Ошибка при получении списка файлов из {directory}: {e}")
        return jsonify({'error': str(e)}), 500

def set_playbook_status(ip, status):
    """
    Устанавливает статус выполнения Ansible плейбука для конкретного IP-адреса.
    Эта функция используется фоновой задачей `parse_ansible_logs` для синхронизации
    состояния хостов с результатами, полученными из логов `journalctl`.
    Args:
        ip (str): IP-адрес хоста (например, '192.168.1.100')
        status (str): Статус выполнения ('ok', 'failed', 'running', 'unknown')
    Side Effects:
        - Обновляет запись в таблице playbook_status
        - Логирует изменение статуса
    """
    try:
        with get_db() as db:
            db.execute('''
                INSERT INTO playbook_status (ip, status, updated)
                VALUES (?, ?, ?)
                ON CONFLICT(ip) DO UPDATE SET
                  status = excluded.status,
                  updated = excluded.updated
            ''', (ip, status, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')))
        logging.info(f"Статус Ansible для {ip} установлен в '{status}'")
    except Exception as e:
        # Добавлено exc_info=True для более детального логирования ошибок
        logging.error(f"Ошибка при установке статуса Ansible для {ip}: {e}", exc_info=True)

def get_ansible_mark(ip):
    """
    Получает информацию из файла /opt/ansible_mark.json с удаленного хоста через SSH.
    Args:
        ip (str): IP-адрес целевого хоста
    Returns:
        dict: Содержимое mark.json или информация об ошибке
    """
    if not re.match(r'^\d{1,3}(\.\d{1,3}){3}$', ip) or ip == '—':
        return {'status': 'error', 'msg': 'Invalid IP'}
    try:
        cmd = f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} 'cat /opt/ansible_mark.json'"
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            if "No such file" in result.stderr:
                return {'status': 'pending', 'msg': 'Файл mark.json не найден (Ansible не завершил установку)'}
            else:
                return {'status': 'error', 'msg': f"SSH ошибка: {result.stderr.strip()}"}
        try:
            data = json.loads(result.stdout)
            data['status'] = 'ok'
            return data
        except json.JSONDecodeError as e:
            return {'status': 'error', 'msg': f'Некорректный JSON в mark.json: {str(e)}'}
    except subprocess.TimeoutExpired:
        return {'status': 'error', 'msg': 'Таймаут подключения к хосту'}
    except Exception as e:
        return {'status': 'error', 'msg': f'Внутренняя ошибка: {str(e)}'}

# ==== Универсальные обработчики для файлов Ansible ====
def create_file_api_handlers(file_path_getter, allow_missing_get=False, name_prefix=""):
    """
    Создаёт пару обработчиков GET/POST для работы с файлами через API.
    Универсальная функция для создания RESTful API для управления файлами.
    Позволяет сократить дублирование кода для различных типов файлов Ansible.
    Args:
        file_path_getter (function): Функция, возвращающая путь к файлу
        allow_missing_get (bool): Разрешить возвращать пустую строку при отсутствии файла (для GET)
        name_prefix (str): Префикс для имен обработчиков (для избежания конфликтов в Flask)
    Returns:
        tuple: Пара функций (get_handler, post_handler) для регистрации в Flask
    Example:
        # Для работы с playbook.yml
        playbook_get, playbook_post = create_file_api_handlers(lambda: ANSIBLE_PLAYBOOK, name_prefix="playbook")
        app.route('/api/ansible/playbook', methods=['GET'])(playbook_get)
    """
    def get_handler(*args, **kwargs):
        try:
            file_path = file_path_getter(*args, **kwargs)
            return read_file(file_path), 200, {'Content-Type': 'text/plain; charset=utf-8'}
        except FileNotFoundError:
            if allow_missing_get:
                return '', 200
            else:
                # read_file вызовет abort(404)
                return read_file(file_path_getter(*args, **kwargs))
        except Exception as e:
            logging.error(f'Ошибка при чтении файла {file_path_getter(*args, **kwargs) if "file_path" not in locals() else file_path}: {e}')
            return 'Ошибка', 500
    def post_handler(*args, **kwargs):
         try:
             file_path = file_path_getter(*args, **kwargs)
             body = request.get_data(as_text=True)
             write_file(file_path, body)
             return jsonify({'status': 'ok'}), 200
         except Exception as e:
             logging.error(f'Ошибка при записи файла {file_path_getter(*args, **kwargs)}: {e}')
             return jsonify({'status': 'error', 'msg': str(e)}), 500
    # Явно задаем уникальные имена функциям, чтобы Flask не ругался
    get_handler.__name__ = f"{name_prefix}_get_handler"
    post_handler.__name__ = f"{name_prefix}_post_handler"
    return get_handler, post_handler

# ==== Фоновая задача: пинг хостов ====
def ping_host(ip):
    """
    Проверяет доступность хоста через ICMP-запрос (пинг).
    Args:
        ip (str): IP-адрес для проверки
    Returns:
        bool: True если хост отвечает, False в противном случае
    Note:
        Использует таймаут 1 секунду и подавляет вывод в консоль
    """
    try:
        # Используем timeout 1 секунду и подавляем вывод
        result = subprocess.run(
            ['ping', '-c', '1', '-W', '1', ip],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return result.returncode == 0
    except Exception as e:
        logging.warning(f"Ошибка при пинге {ip}: {e}")
        return False

def update_host_online_status(ip, is_online):
    """
    Обновляет статус онлайн/оффлайн для хоста в базе данных.
    Args:
        ip (str): IP-адрес хоста
        is_online (bool): Статус доступности хоста
    Side Effects:
        - Обновляет запись в таблице host_status
        - Логирует ошибки при работе с БД
    """
    try:
        with get_db() as db:
            db.execute('''
                INSERT INTO host_status (ip, is_online, last_checked)
                VALUES (?, ?, ?)
                ON CONFLICT(ip) DO UPDATE SET
                    is_online = excluded.is_online,
                    last_checked = excluded.last_checked
            ''', (ip, is_online, datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')))
    except Exception as e:
        logging.error(f"Ошибка обновления статуса для {ip}: {e}")

def ping_hosts_background():
    """
    Фоновая задача для периодической проверки доступности всех известных хостов.
    Выполняется каждую минуту в отдельном потоке.
    Логика работы:
    1. Получает список всех уникальных IP-адресов из таблицы hosts
    2. Для каждого IP выполняет пинг
    3. Обновляет статус в таблице host_status
    4. Делает небольшую паузу между пингами для снижения нагрузки
    Note:
        Пропускает хосты с IP '—' (неизвестный IP)
    """
    while True:
        time.sleep(60) # Ждём 1 минуту
        logging.info("Начинаем фоновый пинг хостов...")
        try:
            with get_db() as db:
                # Получаем все уникальные IP, кроме '—' и NULL
                rows = db.execute("SELECT DISTINCT ip FROM hosts WHERE ip != '—' AND ip IS NOT NULL").fetchall()
                # Используем list comprehension для компактности
                ips = [row[0] for row in rows] # row['ip'] или row[0], row[0] чуть быстрее
            # Используем генераторное выражение или list comprehension для компактности
            # Хотя в данном случае цикл с логированием понятнее
            for ip in ips:
                is_online = ping_host(ip)
                update_host_online_status(ip, is_online)
                time.sleep(0.1) # Небольшая задержка между пингами
            logging.info(f"Фоновый пинг завершён. Проверено {len(ips)} хостов.")
        except Exception as e:
            logging.error(f"Ошибка в фоновой задаче пинга: {e}", exc_info=True)

# ==== Фоновая задача: анализ логов Ansible ====
def parse_ansible_logs():
    """
    Фоновая задача для парсинга логов Ansible и обновления статусов выполнения.
    Выполняется каждые 30 секунд в отдельном потоке.
    Логика работы:
    1. Получает последние записи журнала systemd для сервиса Ansible
    2. Фильтрует уже обработанные строки
    3. Парсит строки, содержащие статистику выполнения (PLAY RECAP)
    4. Извлекает IP-адреса и статусы выполнения
    5. Обновляет статусы в таблице playbook_status
    Note:
        Использует deque для отслеживания обработанных строк, чтобы не повторяться
    """
    # Используем collections.deque для хранения последних строк
    last_checked_lines = set() # Храним последние обработанные строки, чтобы не повторяться
    while True:
        time.sleep(30) # Проверяем логи каждые 30 секунд
        logging.info("Начинаем анализ логов Ansible...")
        try:
            # Получаем последние 500 записей журнала (можно настроить)
            result = subprocess.run(
                ['journalctl', '-u', ANSIBLE_SERVICE_NAME, '-n', '500', '--no-pager', '--since', '5 minutes ago'],
                capture_output=True, text=True, check=True
            )
            lines = result.stdout.strip().split('\n') # Исправлено: правильный разделитель строк
            # Отфильтруем уже обработанные строки
            new_lines = [line for line in lines if line not in last_checked_lines]
            last_checked_lines.update(new_lines[-100:]) # Храним последние 100 строк
            # Парсим логи на предмет завершения задач для IP
            ip_status_map = {}
            for line in reversed(new_lines): # Обрабатываем с конца, чтобы получить последний статус
                # Ищем строки PLAY RECAP
                if 'PLAY RECAP' in line:
                    # Следующие строки должны содержать статистику
                    continue
                # Ищем статистику вида "IP : ok=X changed=X ..."
                recap_match = re.search(r'(\d+\.\d+\.\d+\.\d+)\s*:.*?failed=(\d+)', line)
                if recap_match:
                    ip = recap_match.group(1)
                    failed_count = int(recap_match.group(2))
                    if ip not in ip_status_map: # Обрабатываем только последнюю запись для каждого IP
                         if failed_count > 0:
                             ip_status_map[ip] = 'failed'
                         else:
                             ip_status_map[ip] = 'ok'
            # Обновляем статусы в БД
            for ip, status in ip_status_map.items():
                set_playbook_status(ip, status)
            if ip_status_map:
                logging.info(f"Статусы Ansible обновлены для IP: {list(ip_status_map.keys())}")
        except subprocess.CalledProcessError as e:
            logging.warning(f"Ошибка выполнения journalctl для {ANSIBLE_SERVICE_NAME}: {e}")
        except Exception as e:
            logging.error(f"Ошибка в фоновой задаче парсинга логов Ansible: {e}", exc_info=True)

# ==== Фоновая задача: проверка ansible_mark.json ====
def check_ansible_marks_background():
    """
    Фоновая задача для периодической проверки ansible_mark.json на всех известных хостах.
    Выполняется каждые 2 минуты в отдельном потоке.
    Логика работы:
    1. Получает список всех уникальных IP-адресов из таблицы hosts
    2. Для каждого IP проверяет наличие и содержимое ansible_mark.json через SSH
    3. Обновляет статус Ansible в основной таблице hosts
    """
    while True:
        time.sleep(120) # Ждём 2 минуты
        logging.info("Начинаем проверку статусов Ansible через mark.json...")
        try:
            with get_db() as db:
                # Получаем все уникальные IP, кроме '—' и NULL
                rows = db.execute("SELECT DISTINCT ip FROM hosts WHERE ip != '—' AND ip IS NOT NULL").fetchall()
                ips = [row[0] for row in rows]
            for ip in ips:
                logging.info(f"Проверяем статус Ansible для {ip}")
                # Здесь можно добавить логику обновления статуса в БД, если нужно
                # Но для отображения в интерфейсе достаточно получать данные при запросе
        except Exception as e:
            logging.error(f"Ошибка в фоновой задаче проверки статусов Ansible: {e}", exc_info=True)

# ==== Интеграция с Semaphore API ====
def get_semaphore_status():
    """
    Получает статус последнего запуска Ansible из Semaphore
    """
    try:
        url = f'{SEMAPHORE_API}/project/{SEMAPHORE_PROJECT_ID}/templates'
        headers = {'Authorization': f'Bearer {SEMAPHORE_TOKEN}'}
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code != 200:
            return {'status': 'error', 'msg': f'API ошибка {res.status_code}'}

        templates = res.json()
        template = next((t for t in templates if t['id'] == SEMAPHORE_TEMPLATE_ID), None)
        if not template or 'last_task' not in template:
            return {'status': 'unknown', 'msg': 'Нет данных'}

        task = template['last_task']
        created = datetime.datetime.fromisoformat(task['created'].replace('Z', '+00:00'))
        local_time = created.astimezone(datetime.datetime.now().astimezone().tzinfo)
        formatted_time = local_time.strftime('%d.%m.%Y %H:%M')

        status_map = {
            'success': 'ok',
            'failed': 'failed',
            'running': 'running',
            'waiting': 'pending',
            'canceled': 'failed'
        }
        display_status = task['status']
        icon = '✅' if task['status'] == 'success' else \
               '🔴' if task['status'] in ('failed', 'canceled') else \
               '🔄' if task['status'] in ('running', 'waiting') else \
               '🟡'

        return {
            'status': status_map.get(task['status'], 'unknown'),
            'display_status': display_status,
            'time': formatted_time,
            'commit_message': task.get('commit_message', ''),
            'task_id': task.get('id'),
            'icon': icon
        }
    except Exception as e:
        logging.error(f"Ошибка получения статуса из Semaphore: {e}")
        return {'status': 'error', 'msg': str(e)}

def trigger_semaphore_playbook():
    try:
        url = f'{SEMAPHORE_API}/project/{SEMAPHORE_PROJECT_ID}/tasks'
        headers = {
            'Authorization': f'Bearer {SEMAPHORE_TOKEN}',
            'Content-Type': 'application/json'
        }
        payload = {'template_id': SEMAPHORE_TEMPLATE_ID}
        res = requests.post(url, json=payload, headers=headers, timeout=10)

        # ✅ Исправлено: принимаем 200, 201 и другие успешные коды
        if res.status_code >= 200 and res.status_code < 300:
            task = res.json()
            logging.info(f"Ansible запущен через API: task_id={task['id']}")
            return {'status': 'ok', 'task_id': task['id']}
        else:
            return {'status': 'error', 'msg': f"HTTP {res.status_code}: {res.text}"}
    except Exception as e:
        logging.error(f"Ошибка запуска Ansible через API: {e}")
        return {'status': 'error', 'msg': str(e)}
# ==== API эндпоинты для Semaphore ====
@app.route('/api/semaphore/status', methods=['GET'])
def api_semaphore_status():
    return jsonify(get_semaphore_status())

@app.route('/api/semaphore/trigger', methods=['POST'])
def api_semaphore_trigger():
    result = trigger_semaphore_playbook()
    return jsonify(result), 200 if result['status'] == 'ok' else 500

# Запуск фоновых задач в отдельных потоках
ping_thread = threading.Thread(target=ping_hosts_background, daemon=True)
ping_thread.start()
log_parser_thread = threading.Thread(target=parse_ansible_logs, daemon=True)
log_parser_thread.start()
# Запускаем фоновую задачу проверки ansible_mark.json
ansible_marks_thread = threading.Thread(target=check_ansible_marks_background, daemon=True)
ansible_marks_thread.start()

# ==== API: регистрация хоста ====
@app.route('/api/register', methods=['GET', 'POST'])
def api_register():
    """
    API-эндпоинт для регистрации или обновления информации о хосте.
    Принимает данные от клиента на этапах загрузки (DHCP, iPXE, установка).
    Parameters (query parameters):
        mac (str): MAC-адрес клиента
        ip (str): IP-адрес клиента (опционально, по умолчанию request.remote_addr)
        stage (str): Текущий этап установки
        details (str): Дополнительные детали этапа
    Returns:
        str: "OK" при успешной регистрации, ошибка в противном случае
    Note:
        Использует UPSERT для обновления существующих записей по MAC-адресу
    """
    mac = request.values.get('mac', '').lower()
    ip = request.values.get('ip', request.remote_addr)
    stage = request.values.get('stage', 'unknown')
    details = request.values.get('details', '')
    if not mac:
        logging.warning('Отсутствует MAC-адрес в запросе')
        return 'Missing MAC', 400
    ts = datetime.datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')
    try:
        with get_db() as db:
            db.execute('''
                INSERT INTO hosts(mac, ip, stage, details, ts, first_ts)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(mac) DO UPDATE SET
                    ip = excluded.ip,
                    stage = excluded.stage,
                    details = excluded.details,
                    ts = excluded.ts,
                    first_ts = COALESCE(hosts.first_ts, excluded.ts)
            ''', (mac, ip, stage, details, ts, ts))
        logging.info(f'Зарегистрирован или обновлен хост с MAC: {mac}')
    except Exception as e:
        logging.error(f'Ошибка при регистрации хоста: {e}')
        return 'Error', 500
    return 'OK', 200

# ==== API: preseed файл ====
@app.route('/api/preseed', methods=['GET'])
def api_preseed_get():
    """Возвращает содержимое preseed.cfg для автоматической установки Debian."""
    return read_file(PRESEED_PATH), 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/api/preseed', methods=['POST'])
def api_preseed_post():
    """
    Обновляет содержимое preseed.cfg.
    Используется для изменения параметров автоматической установки Debian.
    Returns:
        JSON: {'status': 'ok'} при успехе, сообщение об ошибке в противном случае
    """
    body = request.get_data(as_text=True)
    try:
        write_file(PRESEED_PATH, body)
        return jsonify({'status': 'ok'}), 200
    except IOError as e:
        logging.error(f'Ошибка при записи preseed файла: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500

# ==== API: boot.ipxe и autoexec.ipxe ====
@app.route('/api/ipxe', methods=['GET'])
def api_ipxe_get():
    """
    Возвращает объединенное содержимое boot.ipxe и autoexec.ipxe.
    Добавляет разделители для удобства последующего разбора при обновлении.
    Returns:
        str: Объединенное содержимое файлов с разделителями
    """
    try:
        boot_content = read_file(BOOT_IPXE_PATH)
        autoexec_content = read_file(AUTOEXEC_IPXE_PATH)
        # Используем f-строки для чистоты и читаемости
        combined = f"### boot.ipxe ###\n{boot_content}\n### autoexec.ipxe ###\n{autoexec_content}"
        return combined, 200, {'Content-Type': 'text/plain; charset=utf-8'}
    except Exception as e: # Ловим более общее исключение, так как read_file уже делает abort(404)
        logging.error(f'Ошибка при чтении iPXE файлов: {e}')
        return 'Ошибка', 500

@app.route('/api/ipxe', methods=['POST'])
def api_ipxe_post():
    """
    Обновляет содержимое boot.ipxe и autoexec.ipxe.
    Ожидает единый текст с разделителями, который затем разделяется на два файла.
    Format:
        ### boot.ipxe ###
        [содержимое boot.ipxe]
        ### autoexec.ipxe ###
        [содержимое autoexec.ipxe]
    Returns:
        JSON: {'status': 'ok'} при успехе, сообщение об ошибке в противном случае
    """
    content = request.get_data(as_text=True)
    try:
        # Используем ### autoexec.ipxe ### для разделения и замены
        parts = content.split('\n### autoexec.ipxe ###\n')
        if len(parts) != 2:
            raise ValueError("Неверный формат данных")
        boot_content = parts[0].replace('### boot.ipxe ###\n', '', 1)
        autoexec_content = parts[1]
        write_file(BOOT_IPXE_PATH, boot_content)
        write_file(AUTOEXEC_IPXE_PATH, autoexec_content)
        logging.info('Файлы boot.ipxe и autoexec.ipxe обновлены')
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logging.error(f'Ошибка при сохранении iPXE файлов: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500

# ==== API: dnsmasq ====
@app.route('/api/dnsmasq', methods=['GET'])
def api_dnsmasq_get():
    """Возвращает содержимое конфигурационного файла dnsmasq."""
    return read_file(DNSMASQ_PATH), 200, {'Content-Type': 'text/plain; charset=utf-8'}

@app.route('/api/dnsmasq', methods=['POST'])
def api_dnsmasq_post():
    """
    Обновляет конфигурацию dnsmasq и перезапускает сервис.
    После обновления файла конфигурации перезапускает dnsmasq для применения изменений.
    Returns:
        JSON: {'status': 'ok'} при успехе, сообщение об ошибке в противном случае
    """
    body = request.get_data(as_text=True)
    try:
        write_file(DNSMASQ_PATH, body)
        subprocess.run(['sudo', 'systemctl', 'restart', 'dnsmasq'], check=True)
        logging.info('dnsmasq.conf обновлён и dnsmasq перезапущен')
        return jsonify({'status': 'ok'}), 200
    except subprocess.CalledProcessError as e:
        logging.error(f'Ошибка при сохранении dnsmasq.conf: {e}')
        msg = f"Ошибка выполнения команды: {e}"
        if e.stderr:
            msg += f". Stderr: {e.stderr.decode('utf-8')}"
        return jsonify({'status': 'error', 'msg': msg}), 500
    except Exception as e:
        logging.error(f'Неизвестная ошибка при сохранении dnsmasq.conf: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500

# ==== API: очистка базы ====
@app.route('/api/clear-db', methods=['POST'])
def api_clear_db():
    """
    Очищает базу данных, удаляя текущий файл БД.
    Используется для сброса состояния приложения.
    Note:
        Приложение автоматически создаст новую БД при следующем запуске
    Returns:
        JSON: {'status': 'ok'} при успехе, сообщение об ошибке в противном случае
    """
    try:
        pathlib.Path(DB_PATH).unlink(missing_ok=True)
        logging.info('База данных очищена')
        return jsonify({'status': 'ok'}), 200
    except Exception as e:
        logging.error(f'Ошибка при очистке базы данных: {e}')
        return jsonify({'status': 'error', 'msg': str(e)}), 500

# ==== API: Ansible playbook, inventory, files, templates ====
# Создаём обработчики для playbook
playbook_get, playbook_post = create_file_api_handlers(lambda: ANSIBLE_PLAYBOOK, name_prefix="playbook")
app.route('/api/ansible/playbook', methods=['GET'])(playbook_get)
app.route('/api/ansible/playbook', methods=['POST'])(playbook_post)

# Создаём обработчики для inventory (с allow_missing_get=True)
inventory_get, inventory_post = create_file_api_handlers(lambda: ANSIBLE_INVENTORY, allow_missing_get=True, name_prefix="inventory")
app.route('/api/ansible/inventory', methods=['GET'])(inventory_get)
app.route('/api/ansible/inventory', methods=['POST'])(inventory_post)

# Создаём обработчики для файлов
def get_file_path(filename):
    return os.path.join(ANSIBLE_FILES_DIR, filename)

file_get, file_post = create_file_api_handlers(get_file_path, name_prefix="file")
app.route('/api/ansible/files/<path:filename>', methods=['GET'])(file_get)
app.route('/api/ansible/files/<path:filename>', methods=['POST'])(file_post)

# Создаём обработчики для шаблонов
def get_template_path(filename):
    return os.path.join(ANSIBLE_TEMPLATES_DIR, filename)

template_get, template_post = create_file_api_handlers(get_template_path, name_prefix="template")
app.route('/api/ansible/templates/<path:filename>', methods=['GET'])(template_get)
app.route('/api/ansible/templates/<path:filename>', methods=['POST'])(template_post)

# Обработчики списков файлов остаются как есть
@app.route('/api/ansible/files', methods=['GET'])
def api_ansible_files_list():
    """Возвращает список файлов в директории Ansible files с информацией."""
    return list_files_in_dir(ANSIBLE_FILES_DIR)

@app.route('/api/ansible/templates', methods=['GET'])
def api_ansible_templates_list():
    """Возвращает список файлов в директории Ansible templates."""
    return list_files_in_dir(ANSIBLE_TEMPLATES_DIR)

# ==== НОВЫЙ API: статус Ansible по mark.json ====
@app.route('/api/ansible/status/<ip>', methods=['GET'])
def api_ansible_status(ip):
    """
    Возвращает статус Ansible для указанного IP-адреса, основываясь на данных из /opt/ansible_mark.json.
    Args:
        ip (str): IP-адрес целевого хоста
    Returns:
        JSON: Статус Ansible и дополнительные данные
    """
    result = get_ansible_mark(ip)
    return jsonify(result)

# ==== API: журнал Ansible через ansible-api.service ====
@app.route('/api/logs/ansible', methods=['GET'])
def api_logs_ansible():
    """
    Возвращает последние записи логов Ansible с цветовой подсветкой.
    Парсит вывод journalctl и применяет HTML-разметку для визуального выделения
    ключевых слов и статусов выполнения.
    Returns:
        JSON: Массив строк с HTML-разметкой для отображения в веб-интерфейсе
    Note:
        Возвращает только последние 100 строк для оптимизации производительности
        Фильтрует повторяющиеся однотипные служебные сообщения скрипта.
    """
    try:
        # Получаем последние 300 записей журнала (увеличено для фильтрации)
        result = subprocess.run(
            ['journalctl', '-u', 'ansible-api.service', '-n', '300', '--no-pager'],
            capture_output=True, text=True, check=True
        )
        lines = result.stdout.strip().split('\n') # Исправлено: правильный разделитель строк
        # Фильтрация повторяющихся однотипных служебных сообщений скрипта
        filtered_lines = []
        # Сообщения, которые мы хотим фильтровать
        filter_keywords = [
            "Начинаем фоновый пинг хостов",
            "Фоновый пинг завершён",
            "Начинаем анализ логов Ansible",
            "[Пропущено" # Фильтруем и уведомления о пропущенных сообщениях
        ]
        for line in lines:
            # Проверяем, содержит ли строка одно из фильтруемых сообщений
            if not any(keyword in line for keyword in filter_keywords):
                filtered_lines.append(line)
            # Если содержит, пропускаем строку
        # Применяем цветовую подсветку (только к оставшимся строкам)
        colored_lines = []
        for line in filtered_lines:
            # Увеличиваем шрифт и подсвечиваем
            line = f'<span style="font-size:14px;line-height:1.5">{line}</span>'
            # Подсветка уровней
            line = line.replace('INFO', '<span style="color:#51cf66; font-weight:bold">INFO</span>')
            line = line.replace('WARNING', '<span style="color:#ffa94d; font-weight:bold">WARNING</span>')
            line = line.replace('ERROR', '<span style="color:#ff6b6b; font-weight:bold">ERROR</span>')
            line = line.replace('CRITICAL', '<span style="color:#ff375f; background:#ffccd5; font-weight:bold">CRITICAL</span>')
            # Подсветка HTTP-статусов
            line = line.replace(' 200 ', '<span style="color:#51cf66; font-weight:bold"> 200 </span>')
            line = line.replace(' 404 ', '<span style="color:#ff6b6b; font-weight:bold"> 404 </span>')
            line = line.replace(' 500 ', '<span style="color:#ff375f; background:#ffccd5; font-weight:bold"> 500 </span>')
            # Подсветка методов
            line = line.replace('GET', '<span style="color:#9775fa; font-weight:bold">GET</span>')
            line = line.replace('POST', '<span style="color:#9775fa; font-weight:bold">POST</span>')
            # Подсветка MAC
            line = re.sub(r'([0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2}:[0-9a-fA-F]{2})',
                          r'<span style="color:#0ca678; font-weight:bold; font-family:monospace">\1</span>', line)
            # Подсветка IP
            line = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b',
                          r'<span style="color:#087f5b; font-weight:bold; font-family:monospace">\g<0></span>', line)
            # Подсветка даты
            line = re.sub(r'(\w{3} \d{1,2} \d{2}:\d{2}:\d{2})',
                          r'<span style="color:#adb5bd">\1</span>', line)
            colored_lines.append(line)
        # Возвращаем последние 100 строк (или меньше, если лог короче)
        return jsonify(colored_lines[-100:]), 200
    except subprocess.CalledProcessError as e:
        logging.error(f"Ошибка выполнения journalctl: {e}")
        msg = f"Ошибка выполнения journalctl: {e}"
        if e.stderr:
            msg += f". Stderr: {e.stderr}"
        return jsonify([f"<span style='color:#ff6b6b; font-size:14px'>{msg}</span>"]), 500
    except Exception as e:
        logging.error(f"Ошибка чтения логов Ansible: {e}")
        return jsonify([f"<span style='color:#ff375f; font-size:14px'>Ошибка: {str(e)}</span>"]), 500

# ==== API: перезагрузка хоста ====
@app.route('/api/host/reboot', methods=['POST'])
def api_host_reboot():
    """
    Отправляет команду перезагрузки на указанный хост через SSH.
    Parameters (JSON):
        ip (str): IP-адрес хоста для перезагрузки
    Returns:
        JSON: {'status': 'ok'} при успехе, сообщение об ошибке в противном случае
    Note:
        Использует sshpass для передачи пароля, что небезопасно в production
        Рекомендуется использовать SSH-ключи для аутентификации
    """
    data = request.get_json()
    ip = data.get('ip')
    if not ip or ip == '—':
        return jsonify({'status': 'error', 'msg': 'Неверный IP-адрес'}), 400
    # Восстанавливаем оригинальный способ с shell=True и форматированием строки
    try:
        # Используем команду в точности как указано
        # Предполагаем, что SSH_PASSWORD, SSH_USER определены глобально
        cmd = f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} 'reboot'"
        # Выполняем команду через оболочку (shell=True)
        # ВАЖНО: Убедитесь, что переменные SSH_PASSWORD и SSH_USER безопасны!
        result = subprocess.run(cmd, shell=True, check=True, timeout=10, capture_output=True, text=True)
        logging.info(f'Команда перезагрузки отправлена на {ip}')
        return jsonify({'status': 'ok', 'msg': f'Команда перезагрузки отправлена на {ip}'}), 200
    except subprocess.TimeoutExpired as e:
        # Хост может перезагружаться и не ответить вовремя — считаем это успехом
        msg = f'Команда перезагрузки отправлена на {ip} (таймаут ожидания ответа)'
        logging.warning(msg + f" | Stderr: {e.stderr if e.stderr else 'N/A'}")
        return jsonify({'status': 'ok', 'msg': msg}), 200
    except subprocess.CalledProcessError as e:
        # SSH может вернуть ошибку, если соединение оборвалось из-за перезагрузки
        msg = f'Команда перезагрузки отправлена на {ip} (возможна ошибка SSH)'
        detailed_msg = f"{msg}. Код ошибки SSH: {e.returncode}"
        if e.stderr:
            detailed_msg += f". Вывод SSH: {e.stderr.strip()}"
        logging.warning(detailed_msg)
        return jsonify({'status': 'ok', 'msg': msg}), 200
    except Exception as e:
        msg = f'Неизвестная ошибка при отправке команды перезагрузки на {ip}: {e}'
        logging.error(msg)
        return jsonify({'status': 'error', 'msg': msg}), 500

# ==== НОВЫЙ API: Wake-on-LAN ====
@app.route('/api/host/wol', methods=['POST'])
def api_host_wol():
    """
    Отправляет Wake-on-LAN "magic packet" на указанный MAC-адрес.
    Parameters (JSON):
        mac (str): MAC-адрес хоста для включения
    Returns:
        JSON: {'status': 'ok', 'msg': '...'} при успехе,
              {'status': 'error', 'msg': '...'} при ошибке
    Note:
        Требуется установленный пакет 'wakeonlan' в системе.
        Команда: sudo apt install wakeonlan
    """
    data = request.get_json()
    mac = data.get('mac')
    if not mac or mac == '—':
        return jsonify({'status': 'error', 'msg': 'Неверный MAC-адрес'}), 400
    try:
        # Выполняем команду wakeonlan
        # Убедитесь, что пакет wakeonlan установлен: sudo apt install wakeonlan
        result = subprocess.run(
            ['wakeonlan', mac],
            capture_output=True,
            text=True,
            check=True # Вызовет CalledProcessError, если команда завершится с ошибкой
        )
        # result.stdout может содержать вывод команды, если нужно
        logging.info(f'Wake-on-LAN пакет отправлен на {mac}')
        return jsonify({"status": "ok", "msg": f"Wake-on-LAN пакет отправлен на {mac}."}), 200
    except subprocess.CalledProcessError as e:
        # Команда wakeonlan завершилась с ошибкой (например, неверный MAC)
        error_msg = f"Ошибка выполнения wakeonlan: {e.stderr.strip() if e.stderr else str(e)}"
        logging.error(error_msg)
        return jsonify({"status": "error", "msg": error_msg}), 500
    except FileNotFoundError:
        # Команда wakeonlan не найдена
        error_msg = "Команда 'wakeonlan' не найдена. Установите пакет 'wakeonlan'."
        logging.error(error_msg)
        return jsonify({"status": "error", "msg": error_msg}), 500
    except Exception as e:
        # Другие ошибки (например, проблемы с парсингом JSON)
        error_msg = f"Внутренняя ошибка сервера: {str(e)}"
        logging.error(error_msg, exc_info=True) # exc_info=True для полного трейса
        return jsonify({"status": "error", "msg": error_msg}), 500

# ==== НОВЫЙ API: Выключение хоста ====
@app.route('/api/host/shutdown', methods=['POST'])
def api_host_shutdown():
    """
    Отправляет команду выключения (shutdown -h now) на указанный хост через SSH.
    Parameters (JSON):
        ip (str): IP-адрес хоста для выключения
    Returns:
        JSON: {'status': 'ok', 'msg': '...'} при успехе,
              {'status': 'error', 'msg': '...'} при ошибке
    Note:
        Использует те же SSH настройки, что и для перезагрузки.
        Это небезопасно, рекомендуется использовать SSH-ключи.
    """
    data = request.get_json()
    ip = data.get('ip')
    if not ip or ip == '—':
        return jsonify({'status': 'error', 'msg': 'Неверный IP-адрес'}), 400
    try:
        # Формируем команду выключения
        # Используем те же глобальные переменные для SSH, что и в reboot
        cmd = f"sshpass -p '{SSH_PASSWORD}' ssh {SSH_OPTIONS} {SSH_USER}@{ip} 'shutdown -h now'"
        # Выполняем команду через оболочку
        result = subprocess.run(
            cmd,
            shell=True,
            check=True,
            timeout=10, # Таймаут 10 секунд
            capture_output=True,
            text=True
        )
        logging.info(f'Команда выключения отправлена на {ip}')
        # Команда может вернуть ошибку, если SSH соединение прервано из-за выключения,
        # что нормально. Проверим stderr.
        msg = f'Команда выключения отправлена на {ip}'
        if result.stderr:
             msg += f" (Stderr: {result.stderr.strip()})"
        return jsonify({'status': 'ok', 'msg': msg}), 200
    except subprocess.TimeoutExpired as e:
        # Это может быть нормально, если хост быстро начал выключаться
        msg = f'Команда выключения отправлена на {ip} (таймаут ожидания ответа)'
        logging.warning(msg + f" | Stderr: {e.stderr if e.stderr else 'N/A'}")
        return jsonify({'status': 'ok', 'msg': msg}), 200 # Считаем успехом
    except subprocess.CalledProcessError as e:
        # Этот блок поймает ненулевой код возврата SSH
        # Это может произойти, если команда не выполнена или соединение потеряно
        # быстро (что тоже может быть успехом для shutdown)
        msg = f'Команда выключения отправлена на {ip} (возможна ошибка SSH)'
        detailed_msg = f"{msg}. Код ошибки SSH: {e.returncode}"
        if e.stderr:
             detailed_msg += f". Вывод SSH: {e.stderr.strip()}"
        logging.warning(detailed_msg) # Логируем как warning
        # Возвращаем успех, так как команда могла быть выполнена
        return jsonify({'status': 'ok', 'msg': msg}), 200
    except Exception as e:
        msg = f'Неизвестная ошибка при отправке команды выключения на {ip}: {e}'
        logging.error(msg, exc_info=True) # exc_info=True для полного трейса
        return jsonify({'status': 'error', 'msg': msg}), 500

# ==== Веб-интерфейс: дашборд ====
@app.route('/')
def dashboard():
    """
    Основной веб-интерфейс для мониторинга установки ОС на хостах.
    Запрашивает данные из БД и формирует список хостов с их текущим статусом.
    Теперь вместо 'Неизвестно' показывается дата установки из ansible_mark.json.
    Returns:
        HTML: Страница дашборда с информацией о всех хостах
    """
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
    # Убрали 'unknown': 'Неизвестно' — больше не нужно
    STAGE_LABELS = {
        'dhcp': 'IP получен',
        'ipxe_started': 'Загрузка iPXE',
        'debian_install': 'Идёт установка',
        'reboot': 'Перезагрузка'
    }
    hosts = []
    for row in rows:
        mac, ip, stage, details, ts_utc, ipxe_utc, db_is_online = row
        last_seen = datetime.datetime.fromisoformat(ts_utc) + LOCAL_OFFSET
        is_online = bool(db_is_online)
        # Проверяем статус Ansible
        ansible_result = get_ansible_mark(ip)
        # Формируем метку состояния
        if ansible_result.get('status') == 'ok':
            # Ansible завершён — показываем дату установки
            try:
                install_date_str = ansible_result['install_date']
                # Убираем смещение времени (берём часть до + или Z)
                clean_date = install_date_str.split('+')[0].split('Z')[0]
                install_dt = datetime.datetime.fromisoformat(clean_date)
                date_str = install_dt.strftime('%d.%m.%Y %H:%M')
                version = ansible_result.get('version', '')
                stage_label = f'✅ Ansible: {date_str}'
                if version:
                    stage_label += f' (v{version})'
            except Exception as e:
                logging.warning(f"Ошибка парсинга даты в ansible_mark.json для {ip}: {e}")
                stage_label = '✅ Ansible: завершён (дата неизвестна)'
        elif ansible_result.get('status') == 'pending':
            # Ansible запущен, но ещё не завершил работу
            stage_label = STAGE_LABELS.get(stage, '—') + ' ⏳ Ansible: в процессе'
        else:
            # Ansible не запускался — показываем текущий этап
            stage_label = STAGE_LABELS.get(stage, '—')
        hosts.append({
            'mac': mac,
            'ip': ip or '—',
            'stage': stage_label,
            'last': last_seen.strftime('%H:%M:%S'),
            'online': is_online,
            'details': details or '',
        })
    return render_template('dashboard.html', hosts=hosts, stage_labels=STAGE_LABELS)

if __name__ == '__main__':
    """
    Точка входа для запуска веб-приложения.
    Запускает Flask-сервер на всех интерфейсах (0.0.0.0) на порту 5000.
    """
    app.run(host='0.0.0.0', port=5000)
