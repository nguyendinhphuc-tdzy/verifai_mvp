"""PO decision 3: keep native Gemini video as default, but media leaves the
machine only after the uploader declares a usage right."""
from fastapi.testclient import TestClient

from test_unknown_frame_count import _run


def test_unknown_rights_never_upload_to_gemini_and_stay_review(tmp_path, monkeypatch):
    calls = []
    job = _run(tmp_path, monkeypatch, rights='unknown', native_calls=calls)
    assert job['status'] == 'completed', job['details']
    assert calls == []
    assert job['details']['coverage']['vlm'] == 'skipped_rights'
    assert job['details']['vlm']['cloud_upload_allowed'] is False
    assert any('quyền sử dụng' in e for e in job['details']['vlm']['errors'])
    assert not [e for e in job['evidence'] if e['kind'].startswith('vlm')]
    assert job['ai_recommendation']['decision'] == 'Needs Review'


def test_declared_rights_upload_once(tmp_path, monkeypatch):
    calls = []
    job = _run(tmp_path, monkeypatch, rights='permission_granted', native_calls=calls)
    assert len(calls) == 1
    assert job['details']['coverage']['vlm'] == 'ok'
    assert job['details']['vlm']['rights'] == 'permission_granted'


def test_rights_can_be_restricted_by_configuration(tmp_path, monkeypatch):
    monkeypatch.setenv('VLM_CLOUD_RIGHTS', 'self_created')
    calls = []
    job = _run(tmp_path, monkeypatch, rights='public_review_only', native_calls=calls)
    assert calls == []
    assert job['details']['coverage']['vlm'] == 'skipped_rights'


def test_invalid_rights_value_is_rejected(tmp_path, monkeypatch):
    import backend
    monkeypatch.setattr(backend, 'DB', tmp_path / 'r.sqlite3')
    backend.init()
    client = TestClient(backend.app)
    pid = client.post('/api/products', json={'sku': 'R1', 'name': 'x', 'brand': 'b',
                                             'price': 1000, 'claims': [], 'banned': []}).json()['id']
    response = client.post('/api/jobs', data={'product_id': pid, 'rights': 'anything'},
                           files={'file': ('a.mp4', b'not-a-video', 'video/mp4')})
    assert response.status_code == 400
