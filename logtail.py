#!/usr/bin/env python3
"""Blueprint providing log tailing and journal features.

This module is adapted from standalone logtail.py to be used as part of the
main PXE panel.  It exposes routes under the same application so that
monitoring logs and journal of remote hosts is available from a single panel.
"""

import os
import shlex
import sqlite3
import json
import subprocess
import re
import html
from datetime import datetime

from flask import (
    Blueprint,
    request,
    jsonify,
    current_app,
    render_template,
)
from config import ANSIBLE_INVENTORY

# ---------------------------------------------------------------------------
# Константы и настройки
# ---------------------------------------------------------------------------
INI_FILE = ANSIBLE_INVENTORY
DB_FILE = "logtail.sqlite"

# Defaults can be overridden via environment variables
DEFAULT_SSH_USER = os.getenv("LOGTAIL_DEFAULT_SSH_USER", "root")
DEFAULT_SSH_PASS = os.getenv("LOGTAIL_DEFAULT_SSH_PASS", "")
DEFAULT_SSH_PORT = os.getenv("LOGTAIL_DEFAULT_SSH_PORT", "22")

logtail_bp = Blueprint("logtail", __name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def get_logtail_db():
    """Return connection to local sqlite database used by log viewer."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_logtail_db():
    """Create required tables if they do not exist."""
    with get_logtail_db() as db:
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS host_logpaths(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT NOT NULL,
                path TEXT NOT NULL,
                name TEXT NOT NULL DEFAULT '',
                UNIQUE(host, path)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS color_rules(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                host TEXT NOT NULL,
                keyword TEXT NOT NULL,
                color TEXT NOT NULL,
                enabled INTEGER DEFAULT 1,
                UNIQUE(host, keyword)
            )
            """
        )
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS profiles(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                log_paths TEXT NOT NULL,
                color_rules TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(name)
            )
            """
        )


@logtail_bp.before_app_first_request
def _init_db() -> None:
    """Initialise DB once application starts."""
    init_logtail_db()


def load_inventory():
    """Read Ansible inventory file and return mapping of hosts."""
    hosts = {}
    if not os.path.isfile(INI_FILE):
        return hosts
    with open(INI_FILE) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and not line.startswith("["):
                parts = line.split()
                host = parts[0]
                vars = {}
                for item in parts[1:]:
                    if "=" in item:
                        k, v = item.split("=", 1)
                        vars[k] = v
                hosts[host] = vars
    return hosts


def build_ssh_command(host: str, vars: dict, cmd: str):
    """Prepare command for remote or local execution.

    Returns a tuple ``(is_local, command)`` where ``command`` is either a list
    suitable for ``subprocess`` or a shell string when executing locally.
    ``is_local`` indicates whether the command should be executed without SSH.
    """
    if vars.get("ansible_connection") == "local":
        return True, cmd

    ssh_target = vars.get("ansible_host", host)
    ssh_user = vars.get("ansible_user", DEFAULT_SSH_USER)
    ssh_pass = (
        vars.get("ansible_ssh_pass")
        or vars.get("ansible_password")
        or DEFAULT_SSH_PASS
    )
    ssh_port = (
        vars.get("ansible_port")
        or vars.get("ansible_ssh_port")
        or DEFAULT_SSH_PORT
    )

    ssh_cmd: list[str] = [
        "ssh",
        "-o",
        "StrictHostKeyChecking=accept-new",
        "-o",
        "UserKnownHostsFile=/dev/null",
        "-o",
        "LogLevel=ERROR",
    ]
    if ssh_port:
        ssh_cmd.extend(["-p", str(ssh_port)])
    ssh_cmd.extend([f"{ssh_user}@{ssh_target}", cmd])
    if ssh_pass:
        ssh_cmd = ["sshpass", "-p", ssh_pass, *ssh_cmd]
    return False, ssh_cmd


# ---------------------------------------------------------------------------
# Frontend route
# ---------------------------------------------------------------------------
@logtail_bp.route("/logtail")
def logtail_dashboard():
    """Serve logtail dashboard page."""
    return render_template("logtail.html")


# ---------------------------------------------------------------------------
# API endpoints
# ---------------------------------------------------------------------------
@logtail_bp.route("/api/hosts")
def api_hosts():
    return jsonify(load_inventory())


@logtail_bp.route("/api/logpaths/<host>", methods=["GET", "POST", "DELETE"])
def api_logpaths(host):
    db = get_logtail_db()
    if request.method == "POST":
        data = request.json
        path = data["path"]
        name = data.get("name", "")
        db.execute(
            "INSERT OR REPLACE INTO host_logpaths(host, path, name) VALUES (?, ?, ?)",
            (host, path, name),
        )
        db.commit()
        return jsonify({"status": "ok"})
    elif request.method == "DELETE":
        path_id = request.json.get("id")
        db.execute(
            "DELETE FROM host_logpaths WHERE id=? AND host=?",
            (path_id, host),
        )
        db.commit()
        return jsonify({"status": "ok"})

    rows = db.execute(
        "SELECT id, path, name FROM host_logpaths WHERE host=?", (host,)
    ).fetchall()
    paths = [
        {"id": row["id"], "path": row["path"], "name": row["name"]}
        for row in rows
    ]
    return jsonify({"paths": paths})


@logtail_bp.route("/api/color-rules/<host>", methods=["GET", "POST", "DELETE"])
def api_color_rules(host):
    db = get_logtail_db()
    if request.method == "POST":
        data = request.json
        keyword = data["keyword"]
        color = data["color"]
        enabled = data.get("enabled", 1)
        db.execute(
            """INSERT OR REPLACE INTO color_rules(host, keyword, color, enabled)
                VALUES (?, ?, ?, ?)""",
            (host, keyword, color, enabled),
        )
        db.commit()
        return jsonify({"status": "ok"})
    elif request.method == "DELETE":
        rule_id = request.json.get("id")
        db.execute(
            "DELETE FROM color_rules WHERE id=? AND host=?",
            (rule_id, host),
        )
        db.commit()
        return jsonify({"status": "ok"})

    rows = db.execute(
        "SELECT id, keyword, color, enabled FROM color_rules WHERE host=?",
        (host,),
    ).fetchall()
    rules = [
        {
            "id": row["id"],
            "keyword": row["keyword"],
            "color": row["color"],
            "enabled": row["enabled"],
        }
        for row in rows
    ]
    return jsonify({"rules": rules})


@logtail_bp.route("/api/profiles", methods=["GET", "POST", "DELETE", "PUT"])
def api_profiles():
    db = get_logtail_db()
    if request.method == "POST":
        data = request.json
        name = data["name"]
        host = data["host"]

        path_rows = db.execute(
            "SELECT id, path, name FROM host_logpaths WHERE host=?", (host,)
        ).fetchall()
        paths = [
            {"id": row["id"], "path": row["path"], "name": row["name"]}
            for row in path_rows
        ]

        rule_rows = db.execute(
            "SELECT id, keyword, color, enabled FROM color_rules WHERE host=?",
            (host,),
        ).fetchall()
        rules = [
            {
                "id": row["id"],
                "keyword": row["keyword"],
                "color": row["color"],
                "enabled": row["enabled"],
            }
            for row in rule_rows
        ]

        db.execute(
            "INSERT INTO profiles(name, log_paths, color_rules) VALUES (?, ?, ?)",
            (name, json.dumps(paths), json.dumps(rules)),
        )
        db.commit()
        return jsonify({"status": "ok"})
    elif request.method == "DELETE":
        profile_id = request.json.get("id")
        db.execute("DELETE FROM profiles WHERE id=?", (profile_id,))
        db.commit()
        return jsonify({"status": "ok"})
    elif request.method == "PUT":
        data = request.json
        profile_id = data.get("id")
        target_host = data.get("host")
        profile_row = db.execute(
            "SELECT log_paths, color_rules FROM profiles WHERE id=?",
            (profile_id,),
        ).fetchone()
        if not profile_row:
            return "Profile not found", 404
        db.execute("DELETE FROM host_logpaths WHERE host=?", (target_host,))
        db.execute("DELETE FROM color_rules WHERE host=?", (target_host,))
        paths = json.loads(profile_row["log_paths"])
        for p in paths:
            db.execute(
                "INSERT INTO host_logpaths(host, path, name) VALUES (?, ?, ?)",
                (target_host, p["path"], p["name"]),
            )
        rules = json.loads(profile_row["color_rules"])
        for r in rules:
            db.execute(
                "INSERT INTO color_rules(host, keyword, color, enabled) VALUES (?, ?, ?, ?)",
                (target_host, r["keyword"], r["color"], r["enabled"]),
            )
        db.commit()
        return jsonify({"status": "ok"})

    rows = db.execute(
        "SELECT id, name, created_at FROM profiles ORDER BY created_at DESC"
    ).fetchall()
    profiles = [
        {"id": row["id"], "name": row["name"], "created_at": row["created_at"]}
        for row in rows
    ]
    return jsonify({"profiles": profiles})


@logtail_bp.route("/api/tail/<host>")
def api_tail(host):
    grep = request.args.get("grep", "")
    lines = int(request.args.get("lines", 100))
    path_id = request.args.get("path_id")
    follow = request.args.get("follow", "true").lower() == "true"
    exclude = request.args.get("exclude", "")
    level = request.args.get("level", "")

    db = get_logtail_db()
    if path_id:
        row = db.execute(
            "SELECT path FROM host_logpaths WHERE id=? AND host=?",
            (path_id, host),
        ).fetchone()
    else:
        row = db.execute(
            "SELECT path FROM host_logpaths WHERE host=? LIMIT 1", (host,)
        ).fetchone()

    if not row or not row["path"]:
        return "log path not set", 400
    logpath = row["path"]

    inventory = load_inventory()
    if host not in inventory:
        return "unknown host", 404
    vars = inventory[host]

    if follow:
        cmd = f"tail -n {lines} -F {shlex.quote(logpath)}"
    else:
        cmd = f"tail -n {lines} {shlex.quote(logpath)}"
    if grep:
        cmd += f" | grep --line-buffered -E {shlex.quote(grep)}"
    if exclude:
        cmd += f" | grep --line-buffered -v -E {shlex.quote(exclude)}"
    if level:
        level_patterns = {
            "ERROR": "(ERROR|ERR|FATAL)",
            "WARN": "(WARN|WARNING)",
            "INFO": "INFO",
            "DEBUG": "DEBUG",
        }
        if level in level_patterns:
            cmd += f" | grep --line-buffered -E {shlex.quote(level_patterns[level])}"

    color_rows = db.execute(
        "SELECT keyword, color FROM color_rules WHERE host=? AND enabled=1",
        (host,),
    ).fetchall()
    color_rules = [(row["keyword"], row["color"]) for row in color_rows]

    is_local, exec_cmd = build_ssh_command(host, vars, cmd)

    def generate():
        proc = subprocess.Popen(
            exec_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=is_local,
        )
        try:
            for line in iter(proc.stdout.readline, ""):
                if follow:
                    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    line = f"[{timestamp}] {line}"
                colored_line = apply_color_rules_html(line, color_rules)
                yield colored_line
        finally:
            proc.terminate()

    return current_app.response_class(generate(), mimetype="text/html")


def apply_color_rules_html(line, color_rules):
    if not color_rules:
        return line
    result = html.escape(line)
    for keyword, color in color_rules:
        if keyword in result:
            escaped_keyword = re.escape(keyword)
            color_class = get_css_color_class(color)
            colored_keyword = f'<span class="{color_class}">{keyword}</span>'
            result = re.sub(escaped_keyword, colored_keyword, result)
    return result + "\n"


def get_css_color_class(color_name):
    return f"log-color-{color_name}"


# ---------------------------------------------------------------------------
# Journal API
# ---------------------------------------------------------------------------
@logtail_bp.route("/api/journal-services/<host>")
def api_journal_services(host):
    inventory = load_inventory()
    if host not in inventory:
        return "unknown host", 404
    vars = inventory[host]
    cmd = "systemctl list-units --type=service --no-pager --no-legend | head -50"
    is_local, exec_cmd = build_ssh_command(host, vars, cmd)
    try:
        result = subprocess.run(
            exec_cmd, capture_output=True, text=True, timeout=10, shell=is_local
        )
        if result.returncode == 0:
            services = []
            for line in result.stdout.strip().split("\n"):
                if line:
                    parts = line.split(None, 4)
                    if len(parts) >= 5:
                        service_name = parts[0]
                        description = parts[4]
                        services.append({"name": service_name, "description": description})
            return jsonify({"services": services})
        return "Failed to get services", 500
    except subprocess.TimeoutExpired:
        return "Timeout getting services", 500
    except Exception as e:  # pragma: no cover
        return f"Error: {e}", 500


@logtail_bp.route("/api/journal/<host>")
def api_journal(host):
    service = request.args.get("service")
    lines = int(request.args.get("lines", 100))
    grep = request.args.get("grep", "")
    follow = request.args.get("follow", "true").lower() == "true"
    include_filters = request.args.get("include", "")
    exclude_filters = request.args.get("exclude", "")
    if not service:
        return "service parameter required", 400
    inventory = load_inventory()
    if host not in inventory:
        return "unknown host", 404
    vars = inventory[host]
    cmd = f"journalctl -u {shlex.quote(service)} -n {lines} --no-pager"
    if follow:
        cmd += " -f"
    if grep:
        cmd += f" | grep --line-buffered -E {shlex.quote(grep)}"
    if include_filters:
        for inc in include_filters.split(","):
            if inc.strip():
                cmd += f" | grep --line-buffered -E {shlex.quote(inc.strip())}"
    if exclude_filters:
        for exc in exclude_filters.split(","):
            if exc.strip():
                cmd += f" | grep --line-buffered -v -E {shlex.quote(exc.strip())}"

    is_local, exec_cmd = build_ssh_command(host, vars, cmd)

    def generate():
        proc = subprocess.Popen(
            exec_cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            shell=is_local,
        )
        try:
            for line in iter(proc.stdout.readline, ""):
                yield line
        finally:
            proc.terminate()

    return current_app.response_class(generate(), mimetype="text/plain")


@logtail_bp.route("/api/journal-status/<host>")
def api_journal_status_get(host):
    service = request.args.get("service")
    if not service:
        return jsonify({"status": "error", "error": "service parameter required"}), 400
    inventory = load_inventory()
    if host not in inventory:
        return jsonify({"status": "error", "error": "unknown host"}), 404
    vars = inventory[host]
    cmd = f"systemctl is-active {shlex.quote(service)}.service"
    is_local, exec_cmd = build_ssh_command(host, vars, cmd)
    try:
        result = subprocess.run(
            exec_cmd, capture_output=True, text=True, timeout=10, shell=is_local
        )
        status = result.stdout.strip() if result.returncode == 0 else "unknown"
        return jsonify({"active": status})
    except Exception as e:  # pragma: no cover
        return jsonify({"status": "error", "error": str(e)})


@logtail_bp.route("/api/journal-control/<host>", methods=["POST"])
def api_journal_control(host):
    data = request.json
    service = data.get("service")
    action = data.get("action")
    if not service or not action:
        return jsonify({"status": "error", "error": "service and action required"}), 400
    if action not in ["start", "stop", "restart"]:
        return jsonify({"status": "error", "error": "invalid action"}), 400
    inventory = load_inventory()
    if host not in inventory:
        return jsonify({"status": "error", "error": "unknown host"}), 404
    vars = inventory[host]
    cmd = f"sudo systemctl {action} {shlex.quote(service)}.service"
    is_local, exec_cmd = build_ssh_command(host, vars, cmd)
    try:
        result = subprocess.run(
            exec_cmd, capture_output=True, text=True, timeout=30, shell=is_local
        )
        if result.returncode == 0:
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "error": result.stderr.strip()}), 500
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "error": "timeout"}), 500
    except Exception as e:  # pragma: no cover
        return jsonify({"status": "error", "error": str(e)}), 500
