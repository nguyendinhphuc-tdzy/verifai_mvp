"""S1-1: videos whose container omits the frame count (common for WEBM/MKV).

Before the fix, duration became 0, which (a) bypassed MAX_VIDEO_SECONDS and
(b) silently dropped every Gemini event later than 1 second.
"""
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from verifai_core.media_quality import count_decodable_frames
from verifai_core.video_understanding import VideoUnderstandingResult


def _video(tmp_path, frames=21, fps=7):
    path = tmp_path / 'clip.mp4'
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*'mp4v'), fps, (160, 96))
    assert writer.isOpened()
    for idx in range(frames):
        frame = np.full((96, 160, 3), 90 + idx, dtype=np.uint8)
        cv2.putText(frame, str(idx), (20, 55), cv2.FONT_HERSHEY_SIMPLEX, .7, (255, 255, 255), 2)
        writer.write(frame)
    writer.release()
    return path


def _run(tmp_path, monkeypatch, *, max_duration=180, rights='self_created', native_calls=None):
    import backend
    monkeypatch.setattr(backend, 'DB', tmp_path / 'verifai.sqlite3')
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'UPLOAD', tmp_path / 'uploads')
    monkeypatch.setattr(backend, 'FRAMES', tmp_path / 'frames')
    monkeypatch.setattr(backend, 'OCR_SCAN_MODE', 'sampled')
    monkeypatch.setattr(backend, 'MAX_DURATION', max_duration)
    # Simulate a container without frame-count metadata.
    monkeypatch.setattr(backend, '_container_frame_count', lambda cap: 0)
    monkeypatch.setenv('OCR_ENABLED', '0')
    monkeypatch.setenv('ASR_ENABLED', '0')
    monkeypatch.setenv('VLM_ENABLED', '1')
    monkeypatch.setenv('VLM_CIRCUIT_ENABLED', '0')
    monkeypatch.setenv('VLM_INPUT_MODE', 'video')
    backend.UPLOAD.mkdir(); backend.FRAMES.mkdir()
    backend.init()

    class FakeGemini(backend._ProductionGeminiVLM):
        def __init__(self):
            self.model = 'gemini-test'
        def check(self):
            return {'ready': True, 'message': 'mock'}
    monkeypatch.setattr(backend, 'GeminiVLM', FakeGemini)
    def native(client, path, product):
        if native_calls is not None:
            native_calls.append(str(path))
        return VideoUnderstandingResult.model_validate({
            'summary': 'giá ở giây thứ 2',
            'observations': [{'timestamp_seconds': 2.0, 'description': 'Giá bán 149.000đ',
                              'category': 'visible_text', 'confidence': 0.95}],
            'issues': [],
        })
    monkeypatch.setattr(backend, 'analyze_native_video', native)
    client = TestClient(backend.app)
    pid = client.post('/api/products', json={
        'sku': 'SKU001', 'name': 'BabyGentle wash', 'brand': 'BabyGentle',
        'price': 149000, 'claims': [], 'banned': []}).json()['id']
    with _video(tmp_path).open('rb') as stream:
        jid = client.post('/api/jobs', data={'product_id': pid, 'rights': rights},
                          files={'file': ('clip.mp4', stream, 'video/mp4')}).json()['id']
    for _ in range(300):
        job = client.get('/api/jobs/' + jid).json()
        if job['status'] in ('completed', 'failed'):
            return job
        time.sleep(.025)
    raise AssertionError('job did not finish')


def test_count_decodable_frames_is_bounded(tmp_path):
    path = _video(tmp_path, frames=21)
    assert count_decodable_frames(path, limit=100) == 21
    assert count_decodable_frames(path, limit=5) == 6  # stops just past the limit
    assert count_decodable_frames(tmp_path / 'missing.mp4', limit=10) == 0


def test_unknown_frame_count_keeps_gemini_events_after_first_second(tmp_path, monkeypatch):
    job = _run(tmp_path, monkeypatch)
    assert job['status'] == 'completed', job['details']
    assert job['details']['frame_count_source'] == 'decoded'
    assert job['details']['frame_count'] == 21
    assert job['details']['duration'] == 3.0
    observed = [e for e in job['evidence'] if e['kind'] == 'vlm_video_observation']
    assert [e['timestamp'] for e in observed] == [2.0]


def test_unknown_frame_count_still_enforces_max_duration(tmp_path, monkeypatch):
    job = _run(tmp_path, monkeypatch, max_duration=1)
    assert job['status'] == 'failed'
    assert 'vượt giới hạn 1 giây' in job['details']['error']
