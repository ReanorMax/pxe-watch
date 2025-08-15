import pathlib
import sys

import requests

# Ensure the application module is importable when tests are executed from the
# tests directory
sys.path.append(str(pathlib.Path(__file__).resolve().parents[1]))
import app

def test_get_semaphore_status_timeout(monkeypatch):
    def fake_get(*args, **kwargs):
        raise requests.exceptions.Timeout
    monkeypatch.setattr(app.requests, 'get', fake_get)
    result = app.get_semaphore_status()
    assert result['status'] == 'timeout'
    assert 'timed out' in result['msg']


def test_trigger_semaphore_playbook_timeout(monkeypatch):
    def fake_post(*args, **kwargs):
        raise requests.exceptions.Timeout
    monkeypatch.setattr(app.requests, 'post', fake_post)
    result = app.trigger_semaphore_playbook()
    assert result['status'] == 'timeout'
    assert 'timed out' in result['msg']
