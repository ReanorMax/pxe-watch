#!/usr/bin/env python3
"""
logtail.py  – Flask-бекенд + пароль-SSH
pip install flask
apt install sshpass
"""
import os, shlex, sqlite3, json, subprocess, re, time
import html
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory
from datetime import datetime
import threading # Для кэширования

# --- Конфигурация ---
INI_FILE   = os.environ.get('LOGTAIL_INI_FILE', '/root/ansible/inventory.ini')
DB_FILE    = os.environ.get('LOGTAIL_DB_FILE', 'logtail.sqlite')
STATIC_DIR = os.path.dirname(__file__) or '.'

# --- Глобальный кэш инвентаря ---
_inventory_cache = {}
_inventory_cache_lock = threading.Lock()

# --------------------------------------------------
# helpers
# --------------------------------------------------
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as db:
        db.execute("""CREATE TABLE IF NOT EXISTS host_logpaths
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       host TEXT NOT NULL,
                       path TEXT NOT NULL,
                       name TEXT NOT NULL DEFAULT '',
                       UNIQUE(host, path))""")
        db.execute("""CREATE TABLE IF NOT EXISTS color_rules
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       host TEXT NOT NULL,
                       keyword TEXT NOT NULL,
                       color TEXT NOT NULL,
                       enabled INTEGER DEFAULT 1,
                       UNIQUE(host, keyword))""")
        db.execute("""CREATE TABLE IF NOT EXISTS profiles
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       name TEXT NOT NULL,
                       log_paths TEXT NOT NULL,
                       color_rules TEXT NOT NULL,
                       created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                       UNIQUE(name))""")
        # Закладки удалены

def load_inventory():
    """Простейший INI-парсер с кэшированием"""
    global _inventory_cache
    cache_key = INI_FILE

    with _inventory_cache_lock:
        mtime = None
        if os.path.exists(INI_FILE):
            mtime = os.path.getmtime(INI_FILE)

        if cache_key in _inventory_cache:
            cached_mtime, cached_hosts = _inventory_cache[cache_key]
            if cached_mtime == mtime:
                # print(f"Using cached inventory for {INI_FILE}")
                return cached_hosts

        # print(f"Reloading inventory from {INI_FILE}")
        hosts = {}
        if not os.path.isfile(INI_FILE):
            _inventory_cache[cache_key] = (mtime, hosts)
            return hosts
        try:
            with open(INI_FILE) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and not line.startswith('['):
                        parts = line.split()
                        host = parts[0]
                        vars = {}
                        for item in parts[1:]:
                            if '=' in item:
                                k, v = item.split('=', 1)
                                vars[k] = v
                        hosts[host] = vars
        except Exception as e:
             print(f"Error loading inventory: {e}")
             pass

        _inventory_cache[cache_key] = (mtime, hosts)
        return hosts

# --------------------------------------------------
# flask
# --------------------------------------------------
app = Flask(__name__)

@app.route('/logtail.html')
def dashboard():
    return send_from_directory(STATIC_DIR, 'logtail.html')

@app.route('/api/hosts')
def api_hosts():
    return jsonify(load_inventory())

# --- Новый эндпоинт для получения всей конфигурации хоста ---
@app.route('/api/host-config/<host>')
def api_host_config(host):
    """Получить всю конфигурацию для хоста за один запрос"""
    db = get_db()
    inventory = load_inventory()
    if host not in inventory:
        return 'unknown host', 404

    path_rows = db.execute("SELECT id, path, name FROM host_logpaths WHERE host=?", (host,)).fetchall()
    paths = [{'id': row['id'], 'path': row['path'], 'name': row['name']} for row in path_rows]

    rule_rows = db.execute("SELECT id, keyword, color, enabled FROM color_rules WHERE host=?", (host,)).fetchall()
    rules = [{'id': row['id'], 'keyword': row['keyword'], 'color': row['color'], 'enabled': row['enabled']} for row in rule_rows]

    profile_rows = db.execute("SELECT id, name, created_at FROM profiles ORDER BY created_at DESC").fetchall()
    profiles = [{'id': row['id'], 'name': row['name'], 'created_at': row['created_at']} for row in profile_rows]

    return jsonify({
        'paths': paths,
        'rules': rules,
        'profiles': profiles
    })

@app.route('/api/logpaths/<host>', methods=['GET', 'POST', 'DELETE'])
def api_logpaths(host):
    db = get_db()
    if request.method == 'POST':
        data = request.json
        path = data['path']
        name = data.get('name', '')
        db.execute("INSERT OR REPLACE INTO host_logpaths(host, path, name) VALUES (?, ?, ?)",
                   (host, path, name))
        db.commit()
        return jsonify({'status': 'ok'})
    elif request.method == 'DELETE':
        path_id = request.json.get('id')
        db.execute("DELETE FROM host_logpaths WHERE id=? AND host=?", (path_id, host))
        db.commit()
        return jsonify({'status': 'ok'})
    rows = db.execute("SELECT id, path, name FROM host_logpaths WHERE host=?", (host,)).fetchall()
    paths = [{'id': row['id'], 'path': row['path'], 'name': row['name']} for row in rows]
    return jsonify({'paths': paths})

@app.route('/api/color-rules/<host>', methods=['GET', 'POST', 'DELETE'])
def api_color_rules(host):
    db = get_db()
    if request.method == 'POST':
        data = request.json
        keyword = data['keyword']
        color = data['color']
        enabled = data.get('enabled', 1)
        db.execute("INSERT OR REPLACE INTO color_rules(host, keyword, color, enabled) VALUES (?, ?, ?, ?)",
                   (host, keyword, color, enabled))
        db.commit()
        return jsonify({'status': 'ok'})
    elif request.method == 'DELETE':
        rule_id = request.json.get('id')
        db.execute("DELETE FROM color_rules WHERE id=? AND host=?", (rule_id, host))
        db.commit()
        return jsonify({'status': 'ok'})
    rows = db.execute("SELECT id, keyword, color, enabled FROM color_rules WHERE host=?", (host,)).fetchall()
    rules = [{'id': row['id'], 'keyword': row['keyword'], 'color': row['color'], 'enabled': row['enabled']} for row in rows]
    return jsonify({'rules': rules})

# --- API для профилей остается ---
@app.route('/api/profiles', methods=['GET', 'POST', 'DELETE', 'PUT'])
def api_profiles():
    db = get_db()
    if request.method == 'POST':
        data = request.json
        name = data['name']
        host = data['host']
        path_rows = db.execute("SELECT id, path, name FROM host_logpaths WHERE host=?", (host,)).fetchall()
        paths = [{'id': row['id'], 'path': row['path'], 'name': row['name']} for row in path_rows]
        rule_rows = db.execute("SELECT id, keyword, color, enabled FROM color_rules WHERE host=?", (host,)).fetchall()
        rules = [{'id': row['id'], 'keyword': row['keyword'], 'color': row['color'], 'enabled': row['enabled']} for row in rule_rows]
        db.execute("INSERT INTO profiles(name, log_paths, color_rules) VALUES (?, ?, ?)",
                   (name, json.dumps(paths), json.dumps(rules)))
        db.commit()
        return jsonify({'status': 'ok'})
    elif request.method == 'DELETE':
        profile_id = request.json.get('id')
        db.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        db.commit()
        return jsonify({'status': 'ok'})
    elif request.method == 'PUT':
        data = request.json
        profile_id = data.get('id')
        target_host = data.get('host')
        profile_row = db.execute("SELECT log_paths, color_rules FROM profiles WHERE id=?",
                                (profile_id,)).fetchone()
        if not profile_row:
            return 'Profile not found', 404
        db.execute("DELETE FROM host_logpaths WHERE host=?", (target_host,))
        db.execute("DELETE FROM color_rules WHERE host=?", (target_host,))
        paths = json.loads(profile_row['log_paths'])
        for path_data in paths:
            db.execute("INSERT INTO host_logpaths(host, path, name) VALUES (?, ?, ?)",
                      (target_host, path_data['path'], path_data['name']))
        rules = json.loads(profile_row['color_rules'])
        for rule_data in rules:
            db.execute("INSERT INTO color_rules(host, keyword, color, enabled) VALUES (?, ?, ?, ?)",
                      (target_host, rule_data['keyword'], rule_data['color'], rule_data['enabled']))
        db.commit()
        return jsonify({'status': 'ok'})
    rows = db.execute("SELECT id, name, created_at FROM profiles ORDER BY created_at DESC").fetchall()
    profiles = [{'id': row['id'], 'name': row['name'], 'created_at': row['created_at']} for row in rows]
    return jsonify({'profiles': profiles})

@app.route('/api/tail/<host>')
def api_tail(host):
    # --- Изменено: получаем списки и флаг ignore_case ---
    include_list  = request.args.getlist('include') # Flask автоматически парсит повторяющиеся параметры
    exclude_list  = request.args.getlist('exclude')
    ignore_case   = request.args.get('ignore_case', 'false').lower() == 'true' # Новый параметр
    lines = int(request.args.get('lines', 100))
    path_id = request.args.get('path_id')
    follow = request.args.get('follow', 'true').lower() == 'true'
    db = get_db()

    if path_id:
        row = db.execute("SELECT path FROM host_logpaths WHERE id=? AND host=?", (path_id, host)).fetchone()
    else:
        row = db.execute("SELECT path FROM host_logpaths WHERE host=? LIMIT 1", (host,)).fetchone()
    if not row or not row['path']:
        return 'log path not set', 400
    logpath = row['path']
    inventory = load_inventory()
    if host not in inventory:
        return 'unknown host', 404
    vars = inventory[host]
    ssh_target = vars.get('ansible_host', host)
    ssh_user   = vars.get('ansible_user', 'root')
    ssh_pass   = vars.get('ansible_ssh_pass', '')
    if follow:
        cmd = f"tail -n {lines} -F {shlex.quote(logpath)}"
    else:
        cmd = f"tail -n {lines} {shlex.quote(logpath)}"

    # --- Изменено: Обработка Include и Exclude с учетом регистра ---
    grep_options = "--line-buffered"
    if ignore_case:
        grep_options += " -i" # Добавляем флаг -i

    if include_list:
        # Фильтруем пустые значения
        filtered_includes = [p for p in include_list if p.strip()]
        if filtered_includes:
            # Экранируем каждый паттерн и объединяем через |
            escaped_includes = [re.escape(p) for p in filtered_includes]
            include_regex = '|'.join(escaped_includes)
            cmd += f" | grep {grep_options} -E {shlex.quote(include_regex)}"

    if exclude_list:
        # Фильтруем пустые значения
        filtered_excludes = [p for p in exclude_list if p.strip()]
        if filtered_excludes:
            # Экранируем каждый паттерн и объединяем через |
            escaped_excludes = [re.escape(p) for p in filtered_excludes]
            exclude_regex = '|'.join(escaped_excludes)
            cmd += f" | grep {grep_options} -v -E {shlex.quote(exclude_regex)}"
    # --- /Изменено ---

    color_rows = db.execute("SELECT keyword, color FROM color_rules WHERE host=? AND enabled=1", (host,)).fetchall()
    color_rules = [(row['keyword'], row['color']) for row in color_rows]

    def yield_buffer(generator, buffer_time=0.1):
        buffer = []
        last_yield_time = time.time()
        try:
            for item in generator:
                buffer.append(item)
                current_time = time.time()
                if buffer and (current_time - last_yield_time >= buffer_time):
                    yield ''.join(buffer)
                    buffer = []
                    last_yield_time = current_time
            if buffer:
                yield ''.join(buffer)
        except GeneratorExit:
            pass
        except Exception as e:
            yield f"\nERROR in yield_buffer: {e}\n"

    def generate():
        sshpass_cmd = [
            'sshpass', '-p', ssh_pass,
            'ssh',
            '-o', 'StrictHostKeyChecking=no',
            '-o', 'UserKnownHostsFile=/dev/null',
            '-o', 'LogLevel=ERROR',
            f"{ssh_user}@{ssh_target}",
            cmd
        ]
        proc = subprocess.Popen(
            sshpass_cmd,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        try:
            line_generator = iter(proc.stdout.readline, '')
            for chunk in yield_buffer((apply_color_rules_html(line, color_rules, follow) for line in line_generator)):
                yield chunk
        except Exception as e:
            yield f"\nERROR in generate: {e}\n"
        finally:
            try:
                proc.terminate()
            except subprocess.TimeoutExpired:
                proc.kill()
            except:
                pass

    return app.response_class(generate(), mimetype='text/html')

def apply_color_rules_html(line, color_rules, add_timestamp=False):
    """Применить правила раскраски к строке и конвертировать в HTML"""
    if add_timestamp:
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        line = f"[{timestamp}] {line}"

    if not color_rules:
        return html.escape(line) + '\n'

    result = html.escape(line)
    for keyword, color in color_rules:
        if keyword in result:
            escaped_keyword = re.escape(keyword)
            color_class = get_css_color_class(color)
            colored_keyword = f'<span class="{color_class}">{keyword}</span>'
            result = re.sub(escaped_keyword, colored_keyword, result)
    return result + '\n'

def get_css_color_class(color_name):
    return f"log-color-{color_name}"

# --------------------------------------------------
if __name__ == '__main__':
    init_db()
    app.run(host='0.0.0.0', port=5004, threaded=True)
