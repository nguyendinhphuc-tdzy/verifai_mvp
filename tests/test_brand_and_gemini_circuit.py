"""Conservative repeated-brand OCR candidates and cross-job Gemini circuit."""
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient

from verifai_core.brand import detect_brand_inconsistencies, BRAND_RULE_VERSION
from verifai_core.evidence import RawEvidence, normalize_evidence
from verifai_core.vlm_health import GeminiOutageCircuit, is_transient_gemini_error


def _raw_brand(text, n, score=0.99):
    return RawEvidence(f'ev-{n}', 'ocr', float(n), text, score,
                       f'{n:03d}.jpg', source_model='paddleocr')


def test_repeated_skinbaby_from_real_ocr_frames_is_candidate():
    raw = [_raw_brand('BabySkin', 0), _raw_brand('SkinBaby', 1),
           _raw_brand('SkinBaby', 2), _raw_brand('BabySkin', 3)]
    normalized, _ = normalize_evidence(raw)
    results = detect_brand_inconsistencies(normalized, 'BabySkin')
    assert len(results) == 1
    assert results[0]['observed_brand'] == 'SkinBaby'
    assert results[0]['reference_brand'] == 'BabySkin'
    assert results[0]['supporting_frame_count'] == 2
    assert results[0]['rule_version'] == BRAND_RULE_VERSION


def test_no_false_positive_for_single_frame_or_unrelated_words():
    raw = [_raw_brand('BabySkin', 0), _raw_brand('SkinBaby', 1)]
    normalized, _ = normalize_evidence(raw)
    assert not detect_brand_inconsistencies(normalized, 'BabySkin')
    other, _ = normalize_evidence([_raw_brand('BabySkin', 0),
                                   _raw_brand('Face Cream', 1),
                                   _raw_brand('Brand from other context', 2)])
    assert not detect_brand_inconsistencies(other, 'BabySkin')
    assert not detect_brand_inconsistencies(normalized, 'Apple')


def test_low_confidence_or_same_frame_repeats_do_not_qualify():
    low, _ = normalize_evidence([_raw_brand('SkinBaby', 0, 0.7),
                                 _raw_brand('SkinBaby', 1, 0.7)])
    assert not detect_brand_inconsistencies(low, 'BabySkin')
    same, _ = normalize_evidence([
        RawEvidence('a','ocr',0,'SkinBaby',0.98,'000.jpg',source_model='paddleocr'),
        RawEvidence('b','ocr',0,'SkinBaby',0.98,'000.jpg',source_model='paddleocr')])
    assert not detect_brand_inconsistencies(same, 'BabySkin')


def test_transient_outage_circuit_and_cooldown():
    guard = GeminiOutageCircuit()
    assert guard.allow(now=100)
    assert not guard.failure('503 UNAVAILABLE', threshold=2, now=101)
    assert guard.failure('504 DEADLINE_EXCEEDED', threshold=2,
                         cooldown_seconds=180, now=102)
    assert not guard.allow(now=200)
    assert guard.remaining_seconds(now=200) == 82
    assert guard.allow(now=283)
    assert not guard.failure('403 PERMISSION_DENIED', threshold=2, now=284)
    guard.success()
    assert guard.allow(now=285)
    assert is_transient_gemini_error('504 DEADLINE_EXCEEDED')
    assert not is_transient_gemini_error('403 PERMISSION_DENIED')


def _video(path):
    writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'mp4v'),5,(160,96))
    assert writer.isOpened()
    for i in range(20):
        writer.write(np.full((96,160,3),130 if i<10 else 155,dtype=np.uint8))
    writer.release()


def _complete(client, pid, video):
    with video.open('rb') as stream:
        res=client.post('/api/jobs',data={'product_id':pid,'rights':'self_created'},
                        files={'file':('brand.mp4',stream,'video/mp4')})
    assert res.status_code == 200,res.text
    job_id=res.json()['id']
    for _ in range(160):
        job=client.get('/api/jobs/'+job_id).json()
        if job['status'] in ('completed','failed'):
            return job
        time.sleep(.05)
    raise AssertionError('Job did not finish')


def _setup(tmp_path, monkeypatch):
    import backend
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    backend.UPLOAD.mkdir();backend.FRAMES.mkdir();backend.init()
    video=tmp_path/'brand.mp4'
    _video(video)
    client=TestClient(backend.app)
    product=client.post('/api/products',json={
        'sku':'BABY-SKIN', 'name':'Face Cream', 'brand':'BabySkin',
        'price':89000, 'claims':[], 'banned':[],
    })
    assert product.status_code==200,product.text
    return backend,client,product.json()['id'],video


def test_brand_candidate_is_evidence_linked_in_real_api(tmp_path,monkeypatch):
    monkeypatch.setenv('VLM_ENABLED','0')
    monkeypatch.setenv('OCR_ENABLED','1')
    monkeypatch.setenv('ASR_ENABLED','0')
    backend,client,pid,video=_setup(tmp_path,monkeypatch)
    monkeypatch.setattr(backend,'frame_ocr',
                        lambda frame:([('BabySkin',0.999),('SkinBaby',0.999)],'ok'))
    job=_complete(client,pid,video)
    assert job['status']=='completed',job['details']
    brands=[f for f in job['findings'] if f['code']=='SKU-01']
    assert len(brands)==1,job['findings']
    finding=brands[0]
    # Repeated OCR brand transposition (>=2 frames) is strong deterministic evidence.
    assert finding['severity']=='high' and finding['source']=='brand_rule_v1'
    assert finding['metadata']['observed_brand']=='SkinBaby'
    assert finding['metadata']['supporting_frame_count']>=2
    ev=next(e for e in job['evidence'] if e['id']==finding['evidence_id'])
    assert ev['kind']=='ocr' and ev['content']=='SkinBaby'
    brand_checks=[c for c in job['details']['verification']['checks']
                  if c['category']=='brand']
    assert len(brand_checks)==1
    assert brand_checks[0]['status']=='CANDIDATE'
    assert finding['evidence_id'] in brand_checks[0]['evidence_ids']
    assert job['details']['verification']['status']=='REVIEW_REQUIRED'
    assert job['decision']=='Needs Review'


def test_gemini_outage_skips_next_job_but_keeps_local_review(tmp_path,monkeypatch):
    monkeypatch.setenv('VLM_ENABLED','1')
    monkeypatch.setenv('VLM_MAX_FRAMES','1')
    monkeypatch.setenv('VLM_MAX_PAIRS','0')
    monkeypatch.setenv('VLM_CIRCUIT_ENABLED','1')
    monkeypatch.setenv('VLM_CIRCUIT_FAILURES','2')
    monkeypatch.setenv('VLM_CIRCUIT_COOLDOWN_SECONDS','180')
    monkeypatch.setenv('OCR_ENABLED','1')
    monkeypatch.setenv('ASR_ENABLED','0')
    backend,client,pid,video=_setup(tmp_path,monkeypatch)
    backend.GEMINI_OUTAGE_CIRCUIT.reset()
    monkeypatch.setattr(backend,'frame_ocr',
                        lambda frame:([('BabySkin',0.999),('SkinBaby',0.999)],'ok'))
    class FailingGemini:
        model='gemini-3.8-flash'
        def check(self):
            return {'ready':True,'message':'ok'}
        def analyze(self,images,product,task):
            from verifai_core.vlm import VLMError
            raise VLMError('504 DEADLINE_EXCEEDED simulated')
    monkeypatch.setattr(backend,'GeminiVLM',FailingGemini)
    monkeypatch.setattr(backend,'_ProductionGeminiVLM',FailingGemini)
    try:
        first=_complete(client,pid,video)
        second=_complete(client,pid,video)
        third=_complete(client,pid,video)
        assert first['details']['vlm']['calls_attempted']==1
        assert second['details']['vlm']['calls_attempted']==1
        assert third['details']['vlm']['calls_attempted']==0
        assert third['details']['coverage']['vlm']=='error'
        assert any('tạm bỏ qua VLM' in text for text in third['details']['vlm']['errors'])
        assert third['status']=='completed'
        assert any(f['code']=='SKU-01' for f in third['findings'])
    finally:
        backend.GEMINI_OUTAGE_CIRCUIT.reset()


def test_native_gemini_video_outage_opens_circuit_and_skips_third_job(tmp_path,monkeypatch):
    """Cloud video 504 must obey the SAME cross-job circuit as JPEG mode."""
    from verifai_core.vlm import VLMError
    monkeypatch.setenv('VLM_ENABLED','1')
    monkeypatch.setenv('VLM_INPUT_MODE','video')
    monkeypatch.setenv('VLM_CIRCUIT_ENABLED','1')
    monkeypatch.setenv('VLM_CIRCUIT_FAILURES','2')
    monkeypatch.setenv('VLM_CIRCUIT_COOLDOWN_SECONDS','180')
    monkeypatch.setenv('OCR_ENABLED','1')
    monkeypatch.setenv('ASR_ENABLED','0')
    backend,client,pid,video=_setup(tmp_path,monkeypatch)
    backend.GEMINI_OUTAGE_CIRCUIT.reset()
    monkeypatch.setattr(backend,'frame_ocr',
                        lambda frame:([('BabySkin',0.999),('SkinBaby',0.999)],'ok'))
    attempts=[]
    class NativeGemini:
        model='mock-gemini-native-video'
        def check(self):
            return {'ready':True,'message':'ok'}
        def _get_client(self):
            return object()
    def failing_native(client, path, product):
        attempts.append(str(path))
        raise VLMError('504 DEADLINE_EXCEEDED simulated native-video outage')
    monkeypatch.setattr(backend,'GeminiVLM',NativeGemini)
    monkeypatch.setattr(backend,'_ProductionGeminiVLM',NativeGemini)
    monkeypatch.setattr(backend,'analyze_native_video',failing_native)
    try:
        first=_complete(client,pid,video)
        second=_complete(client,pid,video)
        third=_complete(client,pid,video)
        assert [first['details']['vlm']['calls_attempted'],
                second['details']['vlm']['calls_attempted'],
                third['details']['vlm']['calls_attempted']]==[1,1,0]
        assert len(attempts)==2
        assert first['details']['coverage']['vlm']=='error'
        assert second['details']['coverage']['vlm']=='error'
        assert third['details']['coverage']['vlm']=='error'
        assert any('tạm bỏ qua VLM' in err for err in
                   third['details']['vlm']['errors'])
        assert third['status']=='completed'
        assert any(f['code']=='SKU-01' for f in third['findings'])
    finally:
        backend.GEMINI_OUTAGE_CIRCUIT.reset()


def test_native_video_circuit_resets_after_success(tmp_path,monkeypatch):
    from verifai_core.vlm import VLMError
    from verifai_core.video_understanding import VideoUnderstandingResult
    monkeypatch.setenv('VLM_ENABLED','1')
    monkeypatch.setenv('VLM_INPUT_MODE','video')
    monkeypatch.setenv('VLM_CIRCUIT_ENABLED','1')
    monkeypatch.setenv('VLM_CIRCUIT_FAILURES','2')
    monkeypatch.setenv('OCR_ENABLED','1')
    monkeypatch.setenv('ASR_ENABLED','0')
    backend,client,pid,video=_setup(tmp_path,monkeypatch)
    backend.GEMINI_OUTAGE_CIRCUIT.reset()
    monkeypatch.setattr(backend,'frame_ocr',lambda frame:([('BabySkin',0.99)],'ok'))
    class NativeGemini:
        model='mock-gemini-native-video'
        def check(self):
            return {'ready':True,'message':'ok'}
        def _get_client(self):
            return object()
    calls=[]
    def recover_after_one_error(*args):
        calls.append(1)
        if len(calls)==1:
            raise VLMError('503 UNAVAILABLE simulated')
        return VideoUnderstandingResult(
            summary='Product in video',timeline_summary='0s: BabySkin')
    monkeypatch.setattr(backend,'GeminiVLM',NativeGemini)
    monkeypatch.setattr(backend,'_ProductionGeminiVLM',NativeGemini)
    monkeypatch.setattr(backend,'analyze_native_video',recover_after_one_error)
    try:
        first=_complete(client,pid,video)
        second=_complete(client,pid,video)
        third=_complete(client,pid,video)
        assert len(calls)==3
        assert first['details']['coverage']['vlm']=='error'
        assert second['details']['coverage']['vlm']=='ok'
        assert third['details']['coverage']['vlm']=='ok'
        assert all(j['details']['vlm']['calls_attempted']==1
                   for j in (first,second,third))
    finally:
        backend.GEMINI_OUTAGE_CIRCUIT.reset()
