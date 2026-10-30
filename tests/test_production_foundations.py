"""Regression gates for provenance-aware benchmark PASS and local-only APIs."""
from fastapi.testclient import TestClient
from verifai_core.recommendation import recommend_ai
from verifai_core.verification import build_verification_report


def test_benchmark_reference_can_pass_but_is_never_commercial_verification():
    from verifai_core.evidence import RawEvidence, normalize_evidence
    # A directly observed OCR string makes the checked scope nonempty.
    evidence = [type('Ev', (), {
        'kind': 'ocr', 'timestamp': 0.0, 'metadata': {}, 'content': 'BabyGentle'
    })()]
    report=build_verification_report(
        evidence,[],{'ocr':'ok','asr':'ok','vlm':'ok'},
        {'reference_status':'test_reference_approved','revision':2})
    assert report['status']=='NO_ISSUES_OBSERVED'
    assert report['reference_scope']=='test'
    rec=recommend_ai(report,[])
    assert rec['decision']=='Pass'
    assert rec['reference_scope']=='test'
    assert rec['reason']=='no_issues_in_checked_test_scope'
    assert rec['is_final_decision'] is False
    assert 'không chứng nhận' in rec['explanation']


def test_ok_modules_with_zero_observations_do_not_get_pass():
    report=build_verification_report([],[],
        {'ocr':'ok','asr':'ok','vlm':'ok'},
        {'reference_status':'test_reference_approved','revision':2})
    assert report['status']=='INSUFFICIENT_EVIDENCE'
    assert report['content_evidence_observed'] is False
    assert recommend_ai(report,[])['decision']=='Needs Review'


def test_unreviewed_reference_still_needs_review():
    evidence=[{'kind':'ocr','content':'149.000đ','timestamp':0,'metadata':{}}]
    report=build_verification_report(evidence,[],
        {'ocr':'ok','asr':'ok','vlm':'ok'},
        {'reference_status':'unverified','revision':1})
    assert report['status']=='INSUFFICIENT_EVIDENCE'
    assert recommend_ai(report,[])['decision']=='Needs Review'


def test_approval_requires_note_is_audited_and_versioned(monkeypatch,tmp_path):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'truth.sqlite3')
    backend.init()
    client=TestClient(backend.app)
    original={
        'sku':'SKU001','name':'BabyGentle','brand':'BabyGentle',
        'price':149000,'claims':['Dịu nhẹ cho da bé'],'banned':[],
    }
    invalid=client.post('/api/products',json={
        **original,'reference_status':'test_reference_approved'})
    assert invalid.status_code==422
    created=client.post('/api/products',json=original)
    assert created.status_code==200,created.text
    pid=created.json()['id']
    changed=client.put('/api/products/'+pid,json={
        **original,'reference_status':'test_reference_approved',
        'reference_note':'Nhóm dự án xác nhận Sheet 1 là chuẩn kiểm thử, không phải dữ liệu thương mại.',
        'expected_revision':1})
    assert changed.status_code==200,changed.text
    assert changed.json()['revision']==2
    product=client.get('/api/products/'+pid).json()
    assert product['reference_status']=='test_reference_approved'
    assert product['reference_scope']=='test'
    history=client.get('/api/products/'+pid+'/history').json()
    assert len(history)==2
    assert history[-1]['snapshot'].find('test_reference_approved')>=0
    stale=client.put('/api/products/'+pid,json={
        **original,'reference_status':'test_reference_approved',
        'reference_note':'stale approval','expected_revision':1})
    assert stale.status_code==409


def test_network_and_cross_origin_writes_blocked_but_local_access_works(tmp_path,monkeypatch):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'guard.sqlite3')
    backend.init()
    normal=TestClient(backend.app)
    assert normal.get('/api/health').status_code==200
    assert normal.get('/').status_code==200
    remote=TestClient(backend.app,base_url='http://my-public-host.example')
    assert remote.get('/api/health').status_code==403
    assert remote.get('/').status_code==403
    assert remote.get('/static/index.html').status_code==403
    hostile={'origin':'https://evil.example'}
    assert normal.post('/api/products',json={'sku':'A','name':'B'},headers=hostile).status_code==403
    assert normal.post('/api/products',json={'sku':'A','name':'B'},
        headers={'sec-fetch-site':'cross-site'}).status_code==403
    assert normal.post('/api/products',json={'sku':'A','name':'B'},
        headers={'origin':'http://testserver'}).status_code==200
    health=normal.get('/api/health')
    assert health.headers['cache-control']=='no-store'
    assert health.headers['x-content-type-options']=='nosniff'


def test_reference_status_has_explicit_ui_choice():
    from pathlib import Path
    html=(Path(__file__).resolve().parents[1]/'static'/'index.html').read_text(encoding='utf-8')
    assert '<option value="test_reference_approved">' in html
    assert 'Pass (bộ kiểm thử)' in html
    assert 'Chuẩn tham chiếu kiểm thử' in html
