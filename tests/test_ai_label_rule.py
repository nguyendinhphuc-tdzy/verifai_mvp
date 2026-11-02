"""Dataset group "Thiếu nhãn AI": declared AI videos must show a disclosure."""
import time

import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from verifai_core.ai_label import find_ai_disclosure


@pytest.mark.parametrize('text', ['Nội dung được tạo bởi AI', 'Ni dung đưc to bi Al',
                                  '•Ni dung đưc to bi A', 'AI-generated content', 'Made with AI'])
def test_disclosure_variants_including_lossy_vietnamese_ocr(text):
    assert find_ai_disclosure([text]) == text


@pytest.mark.parametrize('text', ['BabyGentle', 'Không gây kích ứng', '149.000đ', 'Milk Powder',
                                  'Sữa tắm gội toàn thân', 'Mua ngay hôm nay'])
def test_ordinary_text_is_not_a_disclosure(text):
    assert find_ai_disclosure([text]) is None


def _run(tmp_path, monkeypatch, ocr_lines, ai_generated, reference_status='test_reference_approved'):
    import backend
    monkeypatch.setattr(backend, 'DB', tmp_path / 'verifai.sqlite3')
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'UPLOAD', tmp_path / 'uploads')
    monkeypatch.setattr(backend, 'FRAMES', tmp_path / 'frames')
    monkeypatch.setattr(backend, 'OCR_SCAN_MODE', 'adaptive')
    monkeypatch.setenv('OCR_ENABLED', '1')
    monkeypatch.setenv('VLM_ENABLED', '0')
    backend.UPLOAD.mkdir(); backend.FRAMES.mkdir(); backend.init()
    monkeypatch.setattr(backend, 'frame_ocr', lambda frame: ([(t, 0.95) for t in ocr_lines], 'ok'))
    monkeypatch.setattr(backend, 'transcribe', lambda path: ([], 'ok'))
    client = TestClient(backend.app)
    pid = client.post('/api/products', json={
        'sku': 'AI1', 'name': 'Sữa tắm', 'brand': 'BabyGentle', 'price': 149000,
        'claims': [], 'banned': [], 'reference_status': reference_status,
        'reference_note': 'test'}).json()['id']
    video = tmp_path / 'v.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 10, (128, 80))
    for _ in range(20):
        writer.write(np.full((80, 128, 3), 120, dtype=np.uint8))
    writer.release()
    with video.open('rb') as stream:
        response = client.post('/api/jobs', data={'product_id': pid, 'rights': 'self_created',
                                                  'ai_generated': ai_generated},
                               files={'file': ('v.mp4', stream, 'video/mp4')})
    assert response.status_code == 200, response.text
    jid = response.json()['id']
    for _ in range(200):
        job = client.get('/api/jobs/' + jid).json()
        if job['status'] in ('completed', 'failed'):
            break
        time.sleep(.025)
    assert job['status'] == 'completed', job['details']
    return job


def test_missing_disclosure_on_declared_ai_video_recommends_regenerate(tmp_path, monkeypatch):
    job = _run(tmp_path, monkeypatch, ['BabyGentle', '149.000đ'], 'yes')
    flags = [f for f in job['findings'] if f['code'] == 'AI-LABEL-01']
    assert len(flags) == 1 and flags[0]['severity'] == 'high'
    assert job['details']['ai_label']['status'] == 'missing'
    assert job['decision'] == 'Regenerate'
    assert job['label_suggestion']['label'] == 'error'
    assert job['label_suggestion']['error_types'] == ['Thiếu nhãn AI']


def test_present_disclosure_and_undeclared_videos_are_not_flagged(tmp_path, monkeypatch):
    job = _run(tmp_path, monkeypatch, ['Ni dung đưc to bi Al', 'BabyGentle', '149.000đ'], 'yes')
    assert not [f for f in job['findings'] if f['code'] == 'AI-LABEL-01']
    assert job['details']['ai_label']['status'] == 'found'


def test_ai_label_check_skipped_when_not_declared(tmp_path, monkeypatch):
    job = _run(tmp_path, monkeypatch, ['BabyGentle'], 'no')
    assert not [f for f in job['findings'] if f['code'] == 'AI-LABEL-01']
    assert job['details']['ai_label']['status'] == 'not_required'


def test_invalid_ai_generated_value_rejected(tmp_path, monkeypatch):
    import backend
    monkeypatch.setattr(backend, 'DB', tmp_path / 'verifai.sqlite3')
    backend.init()
    client = TestClient(backend.app)
    pid = client.post('/api/products', json={'sku': 'X', 'name': 'x', 'brand': 'b', 'price': 1,
                                             'claims': [], 'banned': []}).json()['id']
    r = client.post('/api/jobs', data={'product_id': pid, 'ai_generated': 'maybe'},
                    files={'file': ('v.mp4', b'x', 'video/mp4')})
    assert r.status_code == 400


def test_label_records_whether_reviewer_accepted_ai_suggestion(tmp_path, monkeypatch):
    job = _run(tmp_path, monkeypatch, ['BabyGentle'], 'yes')
    import backend
    client = TestClient(backend.app)
    accepted = client.post(f'/api/jobs/{job["id"]}/labels',
                           json={'annotator': 'Reviewer A', 'label': 'error',
                                 'error_types': ['Thiếu nhãn AI']}).json()
    assert accepted['label_source'] == 'accepted_ai_suggestion'
    override = client.post(f'/api/jobs/{job["id"]}/labels',
                           json={'annotator': 'Reviewer B', 'label': 'clean'}).json()
    assert override['label_source'] == 'reviewer_override'
    metrics = client.get('/api/metrics').json()
    assert metrics['reviewer_accepted_ai_suggestion'] == 1
    assert metrics['reviewer_overrode_ai_suggestion'] == 1
