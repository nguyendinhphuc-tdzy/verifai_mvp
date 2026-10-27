"""Price bridging from Gemini visible text, with no OCR/ASR service installed."""
import time
import cv2
import numpy as np
from fastapi.testclient import TestClient
from verifai_core.vlm import VLMResult


def _video(path):
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),5,(160,96))
    assert writer.isOpened()
    for i in range(30):
        writer.write(np.full((96,160,3),130 if i<15 else 160,dtype=np.uint8))
    writer.release()


def _run_case(tmp_path, monkeypatch, visible_text, category='visible_text', failures=False, frame_count=1):
    import backend
    monkeypatch.setenv('VLM_ENABLED','1')
    monkeypatch.setenv('OCR_ENABLED','0')
    monkeypatch.setenv('ASR_ENABLED','0')
    monkeypatch.setenv('VLM_MAX_FRAMES',str(frame_count))
    monkeypatch.setenv('VLM_STOP_AFTER_FAILURES','2')
    monkeypatch.setenv('VLM_MAX_PAIRS','0')
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    backend.UPLOAD.mkdir();backend.FRAMES.mkdir();backend.init()

    class MockGemini:
        model='mock-gemini'
        def check(self):return {'ready':True,'message':'ready'}
        def analyze(self,images,product,task):
            if failures:
                from verifai_core.vlm import VLMError
                raise VLMError('503 UNAVAILABLE test')
            assert task=='single'
            return VLMResult.model_validate({
                'summary':'Observed text; reviewer must validate',
                'observations':[{'description':visible_text,
                                 'category':category,
                                 'confidence':0.97,'frame_index':0}],
                'issues':[]})
    monkeypatch.setattr(backend,'GeminiVLM',MockGemini)
    client=TestClient(backend.app)
    prod=client.post('/api/products',json={
        'sku':'BABY-01','name':'Sữa tắm gội','brand':'BabyGentle','price':149000,
        'claims':[],'banned':[],'reference_status':'unverified',
    })
    assert prod.status_code==200,prod.text
    video=tmp_path/'test.mp4'
    _video(video)
    with video.open('rb') as stream:
        upload=client.post('/api/jobs',data={'product_id':prod.json()['id']},
                          files={'file':('test.mp4',stream,'video/mp4')})
    assert upload.status_code==200,upload.text
    jid=upload.json()['id']
    for _ in range(150):
        job=client.get('/api/jobs/'+jid).json()
        if job['status'] in ('completed','failed'):break
        time.sleep(.05)
    assert job['status']=='completed',job['details']
    return job


def test_gemini_text_price_candidate_without_local_ocr_asr(tmp_path,monkeypatch):
    job=_run_case(tmp_path,monkeypatch,
        "Phần overlay hiển thị 'BabyGentle Sữa tắm gội 200ml', giá '99.000đ'")
    assert job['details']['coverage']['ocr']=='disabled'
    assert job['details']['coverage']['asr']=='disabled'
    assert job['details']['coverage']['vlm']=='ok'
    assert job['details']['vlm']['calls_attempted']==1
    flags=[f for f in job['findings'] if f['code']=='PRICE-01']
    assert len(flags)==1,job['findings']
    assert flags[0]['severity']=='medium'
    assert flags[0]['source']=='price_rule_vlm'
    assert flags[0]['metadata']['evidence_origin']=='gemini_visible_text'
    assert flags[0]['metadata']['reference_status']=='unverified'
    assert flags[0]['metadata']['price_assessment']['compared_vnd']==99000
    assert flags[0]['evidence_id'] in {e['id'] for e in job['evidence']}
    check=[c for c in job['details']['verification']['checks']
           if c['category']=='price']
    assert check and check[0]['status']=='CANDIDATE'
    assert job['details']['verification']['status']=='REVIEW_REQUIRED'
    assert job['decision']=='Needs Review' # never automatic rejection


def test_promotional_gemini_price_does_not_raise_mismatch(tmp_path,monkeypatch):
    job=_run_case(tmp_path,monkeypatch,
        'Giá gốc 149.000đ, giá khuyến mãi 99.000đ')
    assert not [f for f in job['findings'] if f['code']=='PRICE-01']
    assert any(e['kind']=='vlm_observation' for e in job['evidence'])


def test_non_text_gemini_observation_never_enters_price_rules(tmp_path,monkeypatch):
    job=_run_case(tmp_path,monkeypatch,'Vỏ chai có mức giá 99.000đ',category='product')
    assert not [f for f in job['findings'] if f['code']=='PRICE-01']

def test_consecutive_gemini_failures_short_circuit_remaining_calls(tmp_path,monkeypatch):
    job=_run_case(tmp_path,monkeypatch,
                  'not used',failures=True,frame_count=3)
    vlm=job['details']['vlm']
    assert job['status']=='completed'
    assert vlm['calls_attempted']==2
    assert vlm['calls_skipped']==1
    assert vlm['calls_succeeded']==0
    assert job['details']['coverage']['vlm']=='error'
    assert job['decision']=='Needs Review'
    assert not [f for f in job['findings'] if f['code']=='PRICE-01']
