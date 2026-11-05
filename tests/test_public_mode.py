"""Opt-in public demo mode: remote access needs the shared access code."""
import base64

import pytest
from starlette.requests import Request

from verifai_core.local_security import validate_request


def _req(peer='203.0.113.5', host='verifai.hf.space', method='GET', path='/api/jobs', auth=None):
    headers = [(b'host', host.encode())]
    if auth is not None:
        headers.append((b'authorization', b'Basic ' + base64.b64encode(auth.encode())))
    return Request({'type': 'http', 'method': method, 'path': path, 'headers': headers,
                    'client': (peer, 1234), 'scheme': 'https', 'server': (host, 443),
                    'query_string': b''})


def test_remote_access_denied_without_public_mode(monkeypatch):
    monkeypatch.delenv('VERIFAI_PUBLIC_MODE', raising=False)
    assert 'localhost' in validate_request(_req(auth='x:longenoughcode'))


def test_public_mode_without_strong_code_stays_local_only(monkeypatch):
    monkeypatch.setenv('VERIFAI_PUBLIC_MODE', '1')
    monkeypatch.setenv('VERIFAI_ACCESS_CODE', 'short')
    assert 'localhost' in validate_request(_req(auth='x:short'))


@pytest.mark.parametrize('auth,expected', [(None, 'AUTH'), ('u:wrong-code', 'AUTH'),
                                           ('anyone:demo-code-2026', None)])
def test_public_mode_requires_access_code(monkeypatch, auth, expected):
    monkeypatch.setenv('VERIFAI_PUBLIC_MODE', '1')
    monkeypatch.setenv('VERIFAI_ACCESS_CODE', 'demo-code-2026')
    assert validate_request(_req(auth=auth)) == expected


def test_public_mode_health_check_is_open_but_cross_site_writes_still_blocked(monkeypatch):
    monkeypatch.setenv('VERIFAI_PUBLIC_MODE', '1')
    monkeypatch.setenv('VERIFAI_ACCESS_CODE', 'demo-code-2026')
    assert validate_request(_req(path='/healthz')) is None
    evil = _req(method='POST', auth='a:demo-code-2026')
    evil.scope['headers'].append((b'origin', b'https://evil.example'))
    assert 'Cross-origin' in validate_request(evil)
