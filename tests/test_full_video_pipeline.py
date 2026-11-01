"""Integration coverage for complete OCR scans and Gemini-native timeline evidence."""
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from verifai_core.video_understanding import VideoUnderstandingResult


def create_video(tmp_path, frames=21, fps=7):
    video=tmp_path/'full.mp4'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),fps,(160,96))
    assert writer.isOpened()
    for idx in range(frames):
        frame=np.full((96,160,3),100+idx%80,dtype=np.uint8)
        cv2.putText(frame,str(idx),(20,55),cv2.FONT_HERSHEY_SIMPLEX,.7,
                    (255,255,255),2)
        writer.write(frame)
    writer.release()
    return video


def run_job(tmp_path,monkeypatch, *, native=False):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    monkeypatch.setattr(backend,'OCR_SCAN_MODE','all')
    monkeypatch.setattr(backend,'OCR_MAX_FRAMES',4)
    monkeypatch.setenv('OCR_ENABLED','1')
    monkeypatch.setenv('ASR_ENABLED','1')
    monkeypatch.setenv('VLM_ENABLED','1' if native else '0')
    monkeypatch.setenv('VLM_CIRCUIT_ENABLED','0')
    backend.UPLOAD.mkdir(); backend.FRAMES.mkdir()
    backend.init()
    calls=[]
    def ocr_stub(frame):
        calls.append('ocr')
        return [('200ml',0.94)],'ok'
    monkeypatch.setattr(backend,'frame_ocr',ocr_stub)
    monkeypatch.setattr(backend,'transcribe',lambda p:([],'ok'))
    if native:
        class FakeGemini(backend._ProductionGeminiVLM):
            def __init__(self):
                self.model='gemini-3.5-flash-lite'
            def check(self):
                return {'ready':True,'message':'mock'}
        monkeypatch.setattr(backend,'GeminiVLM',FakeGemini)
        monkeypatch.setenv('VLM_INPUT_MODE','video')
        def native_stub(client,path,product):
            assert path.is_file()
            assert product['brand']=='BabyGentle'
            return VideoUnderstandingResult.model_validate({
                'summary':'Chai ở đầu; giá ở giữa; chuyển cảnh ở cuối',
                'timeline_summary':'0s: chai; 1s: giá; 2s: cận cảnh',
                'observations':[{'timestamp_seconds':1.0,'description':'Giá bán 149.000đ',
                                 'category':'visible_text','confidence':0.95}],
                'issues':[],
            })
        monkeypatch.setattr(backend,'analyze_native_video',native_stub)
    client=TestClient(backend.app)
    p=client.post('/api/products',json={
        'sku':'SKU001','name':'BabyGentle wash','brand':'BabyGentle',
        'price':149000,'claims':[],'banned':[],
    })
    assert p.status_code==200,p.text
    video=create_video(tmp_path)
    with video.open('rb') as stream:
        response=client.post('/api/jobs',data={'product_id':p.json()['id'],'rights':'self_created'},
                             files={'file':('full.mp4',stream,'video/mp4')})
    assert response.status_code==200,response.text
    jid=response.json()['id']
    for _ in range(300):
        job=client.get('/api/jobs/'+jid).json()
        if job['status'] in ('completed','failed'):
            break
        time.sleep(.025)
    assert job['status']=='completed',job.get('details')
    return job,calls


def test_full_ocr_actual_job_scans_all_21_frames_not_four(monkeypatch,tmp_path):
    job,calls=run_job(tmp_path,monkeypatch)
    assert len(calls)==21
    stats=job['details']['perception_quality']['ocr']
    assert stats['attempted_frames']==21
    assert stats['scan_mode']=='all'
    assert stats['complete_video_scan'] is True
    assert stats['expected_decoded_frames']==21
    assert job['details']['timings']['ocr_frames']==21
    assert job['details']['sampled_frames']<21  # UI thumbnail stream separate
    assert any(e['kind']=='ocr' for e in job['evidence'])


def test_native_gemini_video_timeline_persisted_and_readable(monkeypatch,tmp_path):
    job,calls=run_job(tmp_path,monkeypatch,native=True)
    assert len(calls)==21
    assert job['details']['coverage']['vlm']=='ok'
    assert job['details']['vlm']['input_mode']=='video'
    assert '1s: giá' in job['details']['vlm']['timeline_summary']
    observations=[e for e in job['evidence'] if e['kind']=='vlm_video_observation']
    assert observations
    assert observations[0]['timestamp']==1.0
    assert observations[0]['metadata']['timestamp_source']=='model_reported'
    assert observations[0]['metadata']['category']=='visible_text'
    assert job['details']['vlm']['calls_succeeded']==1
