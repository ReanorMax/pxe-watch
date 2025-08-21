import threading
import time
import subprocess
import logging
import re

from services import set_playbook_status

# Ensure background threads start only once
_tasks_started = False


def ansible_log_monitor() -> None:
    """Tail Ansible service logs and update playbook status by host."""
    pattern = re.compile(
        r"(?P<ip>(?:\d{1,3}\.){3}\d{1,3})\s*:\s*(?P<stats>.*)"
    )
    while True:
        cmd = [
            "journalctl",
            "-u",
            "ansible-api.service",
            "-f",
            "--no-pager",
            "-n",
            "0",
            "-o",
            "cat",
        ]
        try:
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
            )
            for line in iter(proc.stdout.readline, ""):
                clean = re.sub(r"\x1b\[[0-9;]*m", "", line)
                m = pattern.search(clean)
                if not m:
                    continue
                ip = m.group("ip")
                stats = dict(re.findall(r"(\w+)=(\d+)", m.group("stats")))
                failed = int(stats.get("failed", 0))
                unreachable = int(stats.get("unreachable", 0))
                status = "ok" if failed == 0 and unreachable == 0 else "failed"
                set_playbook_status(ip, status)
        except Exception as e:
            logging.error(
                f"Ошибка в анализе логов Ansible: {e}", exc_info=True
            )
            time.sleep(5)


def start_background_tasks() -> None:
    """Start all background threads."""
    global _tasks_started
    if _tasks_started:
        return
    _tasks_started = True
    threading.Thread(target=ansible_log_monitor, daemon=True).start()
