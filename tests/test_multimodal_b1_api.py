"""Sprint B1: end-to-end sampling and partial OCR failure reporting."""
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient


def _setup(monkeypatch, tmp_path):
    import backend
    monkeypatch.setenv('VLM_ENABLED', '0')
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'DB', tmp_path / 'verifai.sqlite3')
    monkeypatch.setattr(backend, 'UPLOAD', tmp_path / 'uploads')
    monkeypatch.setattr(backend, 'FRAMES', tmp_path / 'frames')
    monkeypatch.setattr(backend, 'OCR_MAX_FRAMES', 4)
    monkeypatch.setattr(backend, 'OCR_SAMPLING_MODE', 'hybrid')
    backend.UPLOAD.mkdir()
    backend.FRAMES.mkdir()
    backend.init()
    return backend, TestClient(backend.app)


def _video(tmp_path):
    video = tmp_path / 'b1.mp4'
    writer = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*'mp4v'), 5, (160, 96))
    assert writer.isOpened()
    for i in range(45):
        frame = np.full((96, 160, 3), 120 if i < 25 else 180, dtype=np.uint8)
        cv2.putText(frame, str(i), (20, 60), cv2.FONT_HERSHEY_SIMPLEX, .7, (230,230,230), 2)
        writer.write(frame)
    writer.release()
    return video


def _run(client, video):
    product = client.post('/api/products', json={
        'sku':'B1-001','name':'B1 demo','brand':'Test',
        'price':149000,'claims':[],'banned':[]})
    assert product.status_code == 200, product.text
    with video.open('rb') as stream:
        up = client.post('/api/jobs', data={'product_id':product.json()['id']},
                         files={'file':('b1.mp4', stream, 'video/mp4')})
    assert up.status_code == 200, up.text
    job_id = up.json()['id']
    for _ in range(140):
        job = client.get('/api/jobs/' + job_id).json()
        if job['status'] in ('completed','failed'):
            break
        time.sleep(.05)
    assert job['status'] == 'completed', job['details']
    return job


def test_partial_ocr_does_not_misreport_ok_and_asr_has_end(monkeypatch,tmp_path):
    backend,client = _setup(monkeypatch,tmp_path)
    count = [0]
    def fake_ocr(_frame):
        count[0] += 1
        if count[0] == 2:
            return [], 'error: model timeout'
        if count[0] == 3:
            return [], 'ok'
        return [('Giá bán 99k', 0.96)], 'ok'
    monkeypatch.setattr(backend,'frame_ocr',fake_ocr)
    monkeypatch.setattr(backend,'transcribe',lambda path: (
        [{'at':1.25,'end':2.75,'text':'Giá bán 149k','score':None}], 'ok'))
    job=_run(client,_video(tmp_path))
    stats=job['details']['perception_quality']
    assert stats['sampling_version']=='media-sampling-b1.0'
    assert stats['ocr_sampling_mode']=='hybrid'
    assert stats['sampling_stride_frames'] == 5
    assert stats['ocr']['status']=='partial'
    assert stats['ocr']['attempted_frames']==4
    assert stats['ocr']['successful_frames']==3
    assert stats['ocr']['failed_frames']==1
    assert stats['ocr']['empty_frames']==1
    assert stats['ocr']['text_lines']==2
    assert stats['asr']['status']=='ok'
    assert stats['asr']['segments_with_end']==1
    assert job['details']['coverage']['ocr']=='partial'
    assert job['details']['coverage']['asr']=='ok'
    speech=[e for e in job['evidence'] if e['kind']=='asr']
    assert speech and speech[0]['end_timestamp'] == 2.75
    assert speech[0]['metadata']['segment_end_seconds']==2.75
    prices=[f for f in job['findings'] if f['code']=='PRICE-01']
    assert prices, job['findings']
    assert all(f['evidence_id'] is not None for f in prices)
    assert job['details']['verification']['status']=='REVIEW_REQUIRED'


def test_empty_successful_ocr_is_not_fake_transcript(monkeypatch,tmp_path):
    backend,client = _setup(monkeypatch,tmp_path)
    monkeypatch.setattr(backend,'frame_ocr',lambda frame:([],'ok'))
    monkeypatch.setattr(backend,'transcribe',lambda path:([],'ok'))
    job=_run(client,_video(tmp_path))
    stats=job['details']['perception_quality']
    assert stats['ocr']['status']=='ok'
    assert stats['ocr']['empty_frames']==stats['ocr']['attempted_frames']==4
    assert not stats['ocr']['text_observed']
    assert stats['asr']['segments']==0
    assert not stats['asr']['speech_observed']
    assert not [e for e in job['evidence'] if e['kind'] in ('ocr','asr')]
    assert job['details']['verification']['status']=='INSUFFICIENT_EVIDENCE'
