import os
import sys
import types

# Ensure the project root is on the import path so ``import app`` works when
# tests are executed from the ``tests`` directory.
sys.path.append(os.path.dirname(os.path.dirname(__file__)))

import app
import api.ansible as ansible_module
import db_utils
import werkzeug

def test_ansible_run_filters_version_warnings(monkeypatch, tmp_path):
    monkeypatch.setattr(db_utils, "DB_PATH", str(tmp_path / "test.db"))
    monkeypatch.setattr(ansible_module, "get_macs_from_inventory", lambda: [])
    monkeypatch.setattr(ansible_module, "set_playbook_status", lambda *a, **kw: None)
    monkeypatch.setattr(werkzeug, "__version__", "patched", raising=False)

    class DummyResult:
        returncode = 0
        stdout = ""
        stderr = (
            "[WARNING]: Collection ansible.posix does not support Ansible version 2.14.8\n"
            "[WARNING]: Collection community.general does not support Ansible version 2.14.8"
        )

    monkeypatch.setattr(ansible_module.subprocess, "run", lambda *a, **kw: DummyResult())

    with app.app.test_client() as client:
        resp = client.post("/api/ansible/run", json={})
        assert resp.status_code == 200
        assert resp.get_json()["status"] == "ok"
