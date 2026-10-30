"""AI recommendation is NOT a human reviewer decision."""
import json

from fastapi.testclient import TestClient

from verifai_core.recommendation import recommend_ai


def report(status='NO_ISSUES_OBSERVED', truth='reviewed', **coverage):
    return {
        'status': status, 'reference_status': truth,
        'coverage': {'ocr':'ok', 'asr':'ok','vlm':'ok', **coverage},
        'checks': [], 'requires_human_review': True,
        'is_final_decision': False,
    }


def test_pass_only_with_reviewed_product_and_complete_coverage():
    suggestion=recommend_ai(report())
    assert suggestion['decision']=='Pass'
    assert suggestion['reason']=='no_issues_in_checked_scope'
    assert suggestion['is_final_decision'] is False


def test_user_uploaded_clean_video_is_review_because_truth_unverified():
    # VID_GOC01 evidence: 0 findings, 3 modules covered, price consistent,
    # but its source is an illustrative unverified reference.
    case=report('INSUFFICIENT_EVIDENCE',truth='unverified')
    case['checks']=[{'category':'price','status':'CONSISTENT','values':[149000]}]
    suggestion=recommend_ai(case)
    assert suggestion['decision']=='Needs Review'
    assert suggestion['reason']=='product_truth_unverified'


def test_incomplete_coverage_and_unresolved_checks_are_review():
    assert recommend_ai(report(vlm='error'))['decision']=='Needs Review'
    assert recommend_ai(report('REVIEW_REQUIRED'))['decision']=='Needs Review'
    assert recommend_ai(report('INSUFFICIENT_EVIDENCE'))['decision']=='Needs Review'
    assert recommend_ai(None)['decision']=='Needs Review'


def test_high_severity_requires_evidence_and_not_vlm_only():
    high={'code':'PRICE-01','severity':'high','source':'price_rule_v3',
          'evidence_id':12,'flag_review':'unreviewed'}
    assert recommend_ai(report('REVIEW_REQUIRED'),[high])['decision']=='Regenerate'
    assert recommend_ai(report('REVIEW_REQUIRED'),[{**high,'evidence_id':None}])['decision']=='Needs Review'
    assert recommend_ai(report('REVIEW_REQUIRED'),[{**high,'source':'vlm'}])['decision']=='Needs Review'
    assert recommend_ai(report('REVIEW_REQUIRED'),[{**high,'flag_review':'rejected'}])['decision']=='Needs Review'


def test_old_completed_job_receives_ai_recommendation_without_reanalysis(monkeypatch,tmp_path):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'recommendations.sqlite3')
    backend.init()
    client=TestClient(backend.app)
    result=client.post('/api/products',json={
        'sku':'DEMO-001','name':'BabyGentle','brand':'BabyGentle',
        'price':149000,'claims':[],'banned':[],
        'reference_status':'unverified',
    })
    assert result.status_code==200,result.text
    pid=result.json()['id']
    j='abc123abc123'
    with backend.db() as c:
        c.execute('''INSERT INTO jobs(id,filename,stored_name,product_id,status,
                     decision,created_at,details) VALUES(?,?,?,?,?,?,?,?)''',(
            j,'VID_GOC01.mp4',j+'.mp4',pid,'completed',
            'Needs Review','2026-10-30T00:00:00Z',
            json.dumps({'verification':report('INSUFFICIENT_EVIDENCE','unverified'),
                        'product_truth_snapshot':{'reference_status':'unverified','revision':1}})))
    detail=client.get('/api/jobs/'+j).json()
    listed=client.get('/api/jobs').json()
    assert detail['ai_recommendation']['decision']=='Needs Review'
    assert detail['ai_recommendation']['reason']=='product_truth_unverified'
    assert listed[0]['ai_recommendation']['decision']=='Needs Review'
    assert detail['review_decision'] is None
    response=client.post('/api/jobs/'+j+'/review',json={
        'decision':'Pass','reviewer':'Human evaluator','note':'Manually checked source',
    })
    assert response.status_code==200,response.text
    after=client.get('/api/jobs/'+j).json()
    assert after['review_decision']=='Pass'
    assert after['ai_recommendation']['decision']=='Needs Review'
    assert after['details']['product_truth_snapshot']['reference_status']=='unverified'


def test_legacy_verified_clean_job_can_show_pass_but_review_stays_separate(monkeypatch,tmp_path):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'pass.sqlite3')
    backend.init()
    client=TestClient(backend.app)
    created=client.post('/api/products',json={
        'sku':'DEMO-002','name':'Sample','brand':'Brand','price':149000,
        'reference_status':'reviewed','reference_note':'Checked demo reference manually',
    })
    assert created.status_code==200,created.text
    pid=created.json()['id']
    j='def456def456'
    with backend.db() as c:
        c.execute('''INSERT INTO jobs(id,filename,stored_name,product_id,status,
                     decision,created_at,details) VALUES(?,?,?,?,?,?,?,?)''',(
            j,'demo.mp4',j+'.mp4',pid,'completed',
            'Needs Review','2026-10-30T00:00:00Z',
            json.dumps({'verification':report()})))
    actual=client.get('/api/jobs/'+j).json()
    assert actual['ai_recommendation']['decision']=='Pass'
    assert actual['decision']=='Needs Review'  # original historical column not changed
    assert actual['review_decision'] is None
    assert client.get('/api/jobs').json()[0]['ai_recommendation']['decision']=='Pass'
