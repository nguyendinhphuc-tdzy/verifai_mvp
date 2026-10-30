"""Session archive/reset and Excel reset regression tests, all offline."""
import csv
import io
import json
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient

def setup_local(monkeypatch, tmp_path):
    import backend
    monkeypatch.setattr(backend, 'DB', tmp_path / 'verifai.sqlite3')
    monkeypatch.setattr(backend, 'UPLOAD', tmp_path / 'uploads')
    monkeypatch.setattr(backend, 'FRAMES', tmp_path / 'frames')
    backend.UPLOAD.mkdir(parents=True, exist_ok=True)
    backend.FRAMES.mkdir(parents=True, exist_ok=True)
    backend.init()
    client = TestClient(backend.app)
    created = client.post('/api/products', json={
        'sku': 'SKU-A', 'name': 'Sample product', 'brand': 'Baby',
        'price': 149000, 'claims': [], 'banned': [],
    })
    assert created.status_code == 200, created.text
    return backend, client, created.json()['id']

def seed_job(backend, product_id, *, job_id='a' * 12, status='completed'):
    details = {
        'coverage': {'ocr': 'ok', 'asr': 'ok', 'vlm': 'error'},
        'vlm': {'model': 'gemini-3.5-flash-lite', 'calls_succeeded': 0},
        'verification': {'status': 'REVIEW_REQUIRED', 'reason': 'needs_human_review'},
        'product_truth_snapshot': {'sku': 'SKU-A', 'revision': 1},
    }
    with backend.db() as c:
        c.execute("""INSERT INTO jobs
            (id,filename,stored_name,product_id,status,decision,review_decision,
             reviewer,review_note,created_at,details)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)""", (
            job_id, 'VID_LOI12.mp4', job_id + '.mp4', product_id, status,
            'Needs Review', 'Regenerate', 'Reviewer A', 'Overlay sai brand',
            '2026-10-30T08:00:00Z', json.dumps(details)))
        c.execute("""INSERT INTO evidence(job_id,kind,timestamp,content,source_model,metadata)
            VALUES(?,?,?,?,?,?)""", (job_id, 'ocr', 1.5, 'SkinBaby', 'paddleocr', '{}'))
        evidence_id = c.execute(
            'SELECT id FROM evidence WHERE job_id=?', (job_id,)
        ).fetchone()['id']
        c.execute("""INSERT INTO findings(job_id,code,severity,timestamp,detail,evidence_id,
                     source,confidence,flag_review)
                     VALUES(?,?,?,?,?,?,?,?,?)""",(
            job_id,'SKU-01','medium',1.5,'SkinBaby khác BabySkin',
            evidence_id,'brand_rule_v1',0.94,'confirmed'))
        c.execute("""INSERT INTO labels(job_id,annotator,label,notes,created_at)
                     VALUES(?,?,?,?,?)""",(
            job_id,'Reviewer B','error','Ground Truth', '2026-10-30T08:10:00Z'))
        c.execute("""INSERT INTO audits(job_id,actor,action,payload,created_at)
                     VALUES(?,?,?,?,?)""",(
            job_id,'Reviewer A','review_decision','{"decision":"Regenerate"}',
            '2026-10-30T08:11:00Z'))
    (backend.UPLOAD / (job_id + '.mp4')).write_bytes(b'test video fixture')
    frame_dir = backend.FRAMES / job_id
    frame_dir.mkdir(exist_ok=True)
    (frame_dir / '000.jpg').write_bytes(b'fixture frame')
    return job_id

def test_full_archive_has_ai_comments_reviewer_and_evidence(monkeypatch,tmp_path):
    backend, client, pid = setup_local(monkeypatch,tmp_path)
    jid=seed_job(backend,pid)
    response=client.get('/api/sessions/export')
    assert response.status_code==200, response.text
    assert response.headers['content-type'].startswith('application/zip')
    with zipfile.ZipFile(io.BytesIO(response.content)) as z:
        names=z.namelist()
        assert 'session_summary.csv' in names
        assert 'ai_findings.csv' in names
        assert 'README.txt' in names
        sessions=[x for x in names if x.startswith('sessions/')]
        assert len(sessions)==1
        job=json.loads(z.read(sessions[0]))
        assert job['id']==jid
        assert job['review_decision']=='Regenerate'
        assert job['review_note']=='Overlay sai brand'
        assert job['findings'][0]['code']=='SKU-01'
        assert job['findings'][0]['detail']=='SkinBaby khác BabySkin'
        assert job['findings'][0]['flag_review']=='confirmed'
        assert job['evidence'][0]['content']=='SkinBaby'
        assert len(job['labels'])==1 and len(job['audits'])==1
        summary=list(csv.DictReader(io.StringIO(z.read('session_summary.csv').decode('utf-8-sig'))))
        assert summary[0]['ai_decision']=='Needs Review'
        assert summary[0]['vlm_coverage']=='error'
        assert summary[0]['reviewer_decision']=='Regenerate'
        flags=list(csv.DictReader(io.StringIO(z.read('ai_findings.csv').decode('utf-8-sig'))))
        assert flags[0]['code']=='SKU-01'
        assert flags[0]['source']=='brand_rule_v1'
        assert not any(name.endswith('.mp4') for name in names)

def test_reset_requires_phrase_and_export_remains_non_destructive(monkeypatch,tmp_path):
    backend, client, pid = setup_local(monkeypatch,tmp_path)
    jid=seed_job(backend,pid)
    keep = backend.UPLOAD / 'keep.txt'
    keep.write_text('not owned')
    assert client.get('/api/sessions/export').status_code==200
    assert len(client.get('/api/jobs').json())==1
    invalid=client.post('/api/sessions/reset',json={'confirmation':'wrong'})
    assert invalid.status_code==400
    assert len(client.get('/api/jobs').json())==1
    deleted=client.post('/api/sessions/reset',
                        json={'confirmation':'XOA TAT CA PHIEN'})
    assert deleted.status_code==200, deleted.text
    assert deleted.json()['deleted_sessions']==1
    assert deleted.json()['removed_uploaded_videos']==1
    assert deleted.json()['removed_frame_directories']==1
    assert not (backend.UPLOAD / (jid+'.mp4')).exists()
    assert not (backend.FRAMES / jid).exists()
    assert keep.read_text()=='not owned'
    assert client.get('/api/jobs').json()==[]
    assert len(client.get('/api/products').json())==1
    with backend.db() as c:
        for table in ('jobs','evidence','findings','labels','audits'):
            assert c.execute('SELECT COUNT(*) n FROM '+table).fetchone()['n']==0

def test_reset_denied_during_active_job(monkeypatch,tmp_path):
    backend, client, pid = setup_local(monkeypatch,tmp_path)
    jid=seed_job(backend,pid,status='processing')
    response=client.post('/api/sessions/reset',json={'confirmation':'XOA TAT CA PHIEN'})
    assert response.status_code==409
    assert (backend.UPLOAD / (jid+'.mp4')).exists()
    assert len(client.get('/api/jobs').json())==1

def test_dataset_reset_preserves_sessions_and_products(monkeypatch,tmp_path):
    backend, client, pid = setup_local(monkeypatch,tmp_path)
    jid=seed_job(backend,pid)
    with backend.db() as c:
        c.execute("""INSERT INTO dataset_cases(code,case_group,updated_at,product_id)
                      VALUES(?,?,?,?)""",('VID_GOC01','original','2026-10-30',pid))
        c.execute("""INSERT INTO dataset_annotations(code,annotator,label,created_at)
                      VALUES(?,?,?,?)""",('VID_GOC01','R1','error','2026-10-30'))
        c.execute("""INSERT INTO dataset_simulated(code,source_sheet) VALUES(?,?)""",
                  ('VID_GOC01','controlled'))
        c.execute("""INSERT INTO dataset_imports(id,checksum,created_at,case_count,note)
                      VALUES(?,?,?,?,?)""",('import1','hash','2026-10-30',1,'import'))
        c.execute('UPDATE jobs SET case_code=? WHERE id=?',('VID_GOC01',jid))
    wrong=client.post('/api/dataset/reset',json={'confirmation':'incorrect'})
    assert wrong.status_code==400
    response=client.post('/api/dataset/reset',json={'confirmation':'XOA EXCEL'})
    assert response.status_code==200, response.text
    assert response.json()['deleted_cases']==1
    assert response.json()['deleted_case_annotations']==1
    assert len(client.get('/api/jobs').json())==1
    assert len(client.get('/api/products').json())==1
    assert (backend.UPLOAD / (jid + '.mp4')).exists()
    assert client.get('/api/dataset/cases').json()==[]
    with backend.db() as c:
        assert c.execute('SELECT case_code FROM jobs WHERE id=?',(jid,)).fetchone()['case_code'] is None
        for name in ('dataset_cases','dataset_annotations','dataset_imports','dataset_simulated'):
            assert c.execute('SELECT COUNT(*) n FROM '+name).fetchone()['n']==0

def test_session_admin_blocks_remote_host(monkeypatch,tmp_path):
    backend, client, pid = setup_local(monkeypatch,tmp_path)
    from fastapi.testclient import TestClient
    remote=TestClient(backend.app,base_url='http://not-local.example')
    assert remote.get('/api/sessions/export').status_code==403
    assert remote.post('/api/sessions/reset',
        json={'confirmation':'XOA TAT CA PHIEN'}).status_code==403
    assert remote.post('/api/dataset/reset',
        json={'confirmation':'XOA EXCEL'}).status_code==403


def test_export_empty_archive_is_valid_and_csv_formula_is_escaped(monkeypatch,tmp_path):
    backend, client, pid = setup_local(monkeypatch,tmp_path)
    empty=client.get('/api/sessions/export')
    assert empty.status_code==200
    with zipfile.ZipFile(io.BytesIO(empty.content)) as z:
        assert 'session_summary.csv' in z.namelist()
        assert 'ai_findings.csv' in z.namelist()
    from verifai_core.session_management import _csv_bytes
    encoded=_csv_bytes(['detail'], [{'detail': '=HYPERLINK("bad","click")'}])
    assert '"=HYPERLINK' not in encoded.decode('utf-8')
    assert "'=HYPERLINK" in encoded.decode('utf-8')

def test_loopback_peer_with_localhost_host_permitted():
    from starlette.requests import Request
    from verifai_core.session_management import require_local
    request=Request({
        'type':'http','scheme':'http','path':'/', 'root_path':'',
        'query_string':b'', 'method':'POST',
        'headers':[(b'host',b'localhost:8001')],
        'server':('localhost',8001), 'client':('127.0.0.1',23456),
    })
    require_local(request)
