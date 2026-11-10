"""Attach/change the Product Truth (SKU) of an analysed video and re-analyse it."""
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient


def _setup(tmp_path, monkeypatch):
    import backend
    monkeypatch.setattr(backend, 'DB', tmp_path / 'verifai.sqlite3')
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'UPLOAD', tmp_path / 'uploads')
    monkeypatch.setattr(backend, 'FRAMES', tmp_path / 'frames')
    monkeypatch.setenv('OCR_ENABLED', '1')
    monkeypatch.setenv('VLM_ENABLED', '0')
    backend.UPLOAD.mkdir(); backend.FRAMES.mkdir(); backend.init()
    # The video shows a 99.000đ price on every frame.
    monkeypatch.setattr(backend, 'frame_ocr', lambda frame: ([('Giá 99.000đ', 0.97)], 'ok'))
    monkeypatch.setattr(backend, 'transcribe', lambda path: ([], 'ok'))
    client = TestClient(backend.app)

    def product(sku, price):
        r = client.post('/api/products', json={'sku': sku, 'name': 'Sữa tắm', 'brand': 'BabyGentle',
                                               'price': price, 'claims': [], 'banned': [],
                                               'reference_status': 'test_reference_approved',
                                               'reference_note': 'test'})
        assert r.status_code == 200, r.text
        return r.json()['id']

    video = tmp_path / 'v.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 10, (128, 80))
    for _ in range(20):
        writer.write(np.full((80, 128, 3), 120, dtype=np.uint8))
    writer.release()
    return backend, client, product, video


def _wait(client, jid):
    for _ in range(300):
        job = client.get('/api/jobs/' + jid).json()
        if job['status'] in ('completed', 'failed'):
            return job
        time.sleep(.025)
    raise AssertionError('job did not finish')


def test_changing_sku_reanalyses_stored_video_against_new_reference(tmp_path, monkeypatch):
    backend, client, product, video = _setup(tmp_path, monkeypatch)
    wrong = product('SKU-WRONG', 149000)
    right = product('SKU-RIGHT', 99000)
    with video.open('rb') as stream:
        jid = client.post('/api/jobs', data={'product_id': wrong, 'rights': 'self_created'},
                          files={'file': ('v.mp4', stream, 'video/mp4')}).json()['id']
    first = _wait(client, jid)
    assert any(f['code'] == 'PRICE-01' for f in first['findings'])
    reviewed = client.post(f'/api/jobs/{jid}/review', json={'decision': 'Regenerate', 'reviewer': 'A', 'note': ''})
    assert reviewed.status_code == 200, reviewed.text
    assert client.get('/api/jobs/' + jid).json()['review_decision'] == 'Regenerate'

    r = client.post(f'/api/jobs/{jid}/product', json={'product_id': right, 'actor': 'Reviewer A'})
    assert r.status_code == 200, r.text
    assert r.json()['sku'] == 'SKU-RIGHT'
    second = _wait(client, jid)
    assert second['product']['sku'] == 'SKU-RIGHT'
    assert not any(f['code'] == 'PRICE-01' for f in second['findings'])
    assert second['review_decision'] is None
    changed = [a for a in second['audits'] if a['action'] == 'product_changed']
    assert len(changed) == 1 and 'SKU-WRONG' in changed[0]['payload'] and 'SKU-RIGHT' in changed[0]['payload']
    assert changed[0]['actor'] == 'Reviewer A'


def test_change_is_rejected_for_running_jobs_missing_or_same_product(tmp_path, monkeypatch):
    backend, client, product, video = _setup(tmp_path, monkeypatch)
    pid = product('SKU-A', 99000)
    other = product('SKU-B', 99000)
    with video.open('rb') as stream:
        jid = client.post('/api/jobs', data={'product_id': pid, 'rights': 'self_created'},
                          files={'file': ('v.mp4', stream, 'video/mp4')}).json()['id']
    _wait(client, jid)
    assert client.post(f'/api/jobs/{jid}/product', json={'product_id': pid}).status_code == 409
    assert client.post(f'/api/jobs/{jid}/product', json={'product_id': 'missing'}).status_code == 404
    assert client.post('/api/jobs/nope/product', json={'product_id': other}).status_code == 404
    with backend.db() as conn:
        conn.execute("UPDATE jobs SET status='processing' WHERE id=?", (jid,))
    r = client.post(f'/api/jobs/{jid}/product', json={'product_id': other})
    assert r.status_code == 409
    with backend.db() as conn:
        row = conn.execute('SELECT product_id FROM jobs WHERE id=?', (jid,)).fetchone()
    assert row['product_id'] == pid  # nothing changed on rejection
