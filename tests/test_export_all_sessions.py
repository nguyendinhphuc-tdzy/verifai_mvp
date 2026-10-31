"""Export All Sessions end-to-end regression against the current FastAPI app."""
import csv
import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient


def _prepare(monkeypatch, tmp_path):
    import backend
    monkeypatch.setattr(backend, 'DB', tmp_path / 'all-sessions.sqlite3')
    backend.init()
    client = TestClient(backend.app)
    product = client.post('/api/products', json={
        'sku':'SKU001', 'name':'BabyGentle', 'brand':'BabyGentle',
        'price':149000, 'claims':[], 'banned':[],
        'reference_status':'test_reference_approved',
        'reference_note':'Reference accepted for test dataset only',
    })
    assert product.status_code == 200, product.text
    return backend, client, product.json()['id']


def _insert_sessions(backend, product_id):
    clean = 'abcabcabc123'
    failed = 'defdefdef456'
    report = {
        'status':'REVIEW_REQUIRED',
        'reference_status':'test_reference_approved',
        'reference_scope':'test',
        'coverage': {'ocr':'ok','asr':'ok','vlm':'ok'},
        'reason':'candidate_or_conflict_requires_human_review',
    }
    details = {
        'verification': report,
        'coverage': {'ocr':'ok','asr':'ok','vlm':'ok'},
        'vlm': {'model':'gemini-3.5-flash-lite', 'calls_succeeded':1},
        'product_truth_snapshot':{'sku':'SKU001','reference_scope':'test',
                                  'reference_status':'test_reference_approved'},
    }
    with backend.db() as conn:
        conn.execute(
            '''INSERT INTO jobs
            (id,filename,stored_name,product_id,status,decision,review_decision,
             reviewer,review_note,created_at,finished_at,details)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
            (clean,'VID_LOI01.mp4',clean+'.mp4',product_id,
             'completed','Needs Review','Regenerate','Reviewer A',
             'Video sai giá ở 1,5 giây','2026-10-30T10:00:00Z',
             '2026-10-30T10:01:00Z',json.dumps(details)))
        conn.execute(
            '''INSERT INTO jobs
            (id,filename,stored_name,product_id,status,created_at,details)
            VALUES(?,?,?,?,?,?,?)''',
            (failed,'corrupt.mp4',failed+'.mp4',product_id,'failed',
             '2026-10-30T10:20:00Z',
             json.dumps({'error':'Không đọc được video', 'coverage':{'ocr':'error'}})))
        conn.execute(
            '''INSERT INTO evidence(job_id,kind,timestamp,content,score,frame,
               source_model,metadata) VALUES(?,?,?,?,?,?,?,?)''',
            (clean,'ocr',1.5,'99.000đ',0.93,'0001.jpg','paddleocr','{}'))
        eid = conn.execute(
            'SELECT id FROM evidence WHERE job_id=?',(clean,)
        ).fetchone()['id']
        conn.execute(
            '''INSERT INTO findings(job_id,code,severity,timestamp,detail,
                evidence_id,source,confidence,evidence_refs,metadata)
            VALUES(?,?,?,?,?,?,?,?,?,?)''',
            (clean,'PRICE-01','medium',1.5,'Giá 99.000đ khác 149.000đ',
             eid,'price_rule_v3',0.93,json.dumps([eid]),'{}'))
        conn.execute(
            '''INSERT INTO labels(job_id,annotator,label,notes,created_at)
            VALUES(?,?,?,?,?)''',
            (clean,'Reviewer B','error','Incorrect price', '2026-10-30T10:05:00Z'))
        conn.execute(
            '''INSERT INTO audits(job_id,actor,action,payload,created_at)
            VALUES(?,?,?,?,?)''',
            (clean,'Reviewer A','review_decision',
             '{"decision":"Regenerate"}','2026-10-30T10:03:00Z'))
    return clean, failed


def test_export_all_includes_failed_and_complete_ai_and_human_results(monkeypatch,tmp_path):
    backend,client,pid = _prepare(monkeypatch,tmp_path)
    complete,failed = _insert_sessions(backend,pid)
    response = client.get('/api/sessions/export')
    assert response.status_code == 200, response.text[:400]
    assert response.headers['content-type'].startswith('application/zip')
    assert 'attachment;' in response.headers['content-disposition']
    assert 'no-store' in response.headers['cache-control']
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        entries = archive.namelist()
        assert {'session_summary.csv','ai_findings.csv','README.txt'} <= set(entries)
        session_names = [name for name in entries if name.startswith('sessions/')]
        assert len(session_names)==2
        docs=[json.loads(archive.read(name)) for name in session_names]
        by_id={job['id']:job for job in docs}
        assert set(by_id)=={complete,failed}
        assert by_id[complete]['review_decision']=='Regenerate'
        assert by_id[complete]['review_note']=='Video sai giá ở 1,5 giây'
        assert by_id[complete]['findings'][0]['code']=='PRICE-01'
        assert by_id[complete]['findings'][0]['evidence_id'] is not None
        assert by_id[complete]['evidence'][0]['content']=='99.000đ'
        assert by_id[complete]['labels'][0]['label']=='error'
        assert by_id[complete]['audits'][0]['action']=='review_decision'
        assert by_id[complete]['ai_recommendation']['decision']=='Needs Review'
        assert by_id[failed]['details']['error']=='Không đọc được video'
        summary=list(csv.DictReader(io.StringIO(archive.read(
            'session_summary.csv').decode('utf-8-sig'))))
        assert len(summary)==2
        first=next(row for row in summary if row['job_id']==complete)
        assert first['ai_decision']=='Needs Review'
        assert first['reviewer_decision']=='Regenerate'
        assert first['finding_codes']=='PRICE-01'
        assert first['ocr_coverage']=='ok'
        issues=list(csv.DictReader(io.StringIO(archive.read(
            'ai_findings.csv').decode('utf-8-sig'))))
        assert len(issues)==1
        assert issues[0]['detail']=='Giá 99.000đ khác 149.000đ'
        assert issues[0]['linked_evidence_id']
        assert issues[0]['reviewer_decision']=='Regenerate'
        assert not any(name.endswith(('.mp4','.jpg')) for name in entries)
    # Export is non-destructive and does not change reviewer decisions.
    assert len(client.get('/api/jobs').json())==2
    assert client.get('/api/jobs/'+complete).json()['review_decision']=='Regenerate'


def test_empty_session_archive_is_valid(monkeypatch,tmp_path):
    _,client,_ = _prepare(monkeypatch,tmp_path)
    response=client.get('/api/sessions/export')
    assert response.status_code==200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        assert archive.namelist()==[
            'session_summary.csv','ai_findings.csv','README.txt',
        ]


def test_spreadsheet_formula_injection_is_escaped():
    from verifai_core.session_export import _csv_bytes
    data=_csv_bytes(['detail','filename'],[{
        'detail':'=HYPERLINK("evil","click")',
        'filename':'-dangerous filename',
    }]).decode('utf-8-sig')
    assert "'=HYPERLINK" in data
    assert "'-dangerous filename" in data


def test_export_denies_public_host(monkeypatch,tmp_path):
    backend,_,_ = _prepare(monkeypatch,tmp_path)
    remote=TestClient(backend.app,base_url='http://public.example')
    assert remote.get('/api/sessions/export').status_code==403


def test_export_buttons_visible_in_overview_and_queue():
    html=(Path(__file__).resolve().parents[1] /
          'static' / 'index.html').read_text(encoding='utf-8')
    assert 'id="exportAllSessionsQueue"' in html
    assert 'id="exportAllSessionsOverview"' in html
    assert html.count('href="/api/sessions/export"')==2
    for section in ('queue','overview'):
        block=html.split('<section id="'+section+'"',1)[1].split('</section>',1)[0]
        assert 'Export All Sessions' in block
        assert 'href="/api/sessions/export"' in block
