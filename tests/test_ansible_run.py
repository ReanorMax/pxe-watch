import subprocess
import sys
from pathlib import Path

import pytest

# Ensure project root on sys.path so that local packages can be imported when
# tests are executed in environments that do not automatically include it.
sys.path.append(str(Path(__file__).resolve().parents[1]))

# Flask's test client expects werkzeug to expose a ``__version__`` attribute
# which is no longer present in modern versions.  Define a dummy attribute to
# keep the test client operational.
import werkzeug

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "0"


class DummyCompletedProcess:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_ansible_run_ignores_collection_version_warnings(monkeypatch):
    # Prevent background threads from starting when the Flask app is imported
    import tasks

    monkeypatch.setattr(tasks, "start_background_tasks", lambda: None)

    import app as app_module

    # Patch helper functions that interact with the system or DB
    import api.ansible as api_ansible
    import db_utils

    monkeypatch.setattr(api_ansible, "get_macs_from_inventory", lambda: [])

    class DummyDB:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            pass

        def execute(self, *args, **kwargs):
            return self

        def fetchone(self):
            return None

    monkeypatch.setattr(db_utils, "get_db", lambda: DummyDB())

    # Simulate ansible-playbook producing only collection version warnings on stderr
    warning = (
        "[WARNING]: Collection ansible.posix does not support Ansible version 2.14.8\n"
        "[WARNING]: Collection community.general does not support Ansible version 2.14.8\n"
    )
    cp = DummyCompletedProcess(returncode=0, stdout="PLAY RECAP\n", stderr=warning)
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: cp)

    client = app_module.app.test_client()
    resp = client.post("/api/ansible/run", json={})
    assert resp.status_code == 200
    data = resp.get_json()
    assert data["status"] == "ok"
