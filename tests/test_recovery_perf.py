"""Restart recovery and performance telemetry without real model downloads."""
import json
import time
from pathlib import Path

import cv2
import numpy as np
from fastapi.testclient import TestClient


def _db_job(backend, tmp_path, status, jid='recovery001'):
    with backend.db() as conn:
        conn.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?,?)',
                     ('ref','REF','Reference','test',100000,'[]','[]',backend.utc()))
        conn.execute('INSERT INTO jobs(id,filename,stored_name,product_id,status,created_at,details) VALUES(?,?,?,?,?,?,?)',
                     (jid,'test.mp4',jid+'.mp4','ref',status,backend.utc(),'{}'))
    (tmp_path/'uploads'/f'{jid}.mp4').write_bytes(b'test')
    return jid


def _setup(monkeypatch,tmp_path):
    import backend
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    backend.UPLOAD.mkdir();backend.FRAMES.mkdir()
    backend.init()
    return backend


def test_restart_recovers_processing_job_but_has_retry_limit(monkeypatch,tmp_path):
    backend=_setup(monkeypatch,tmp_path)
    jid=_db_job(backend,tmp_path,'processing')
    started=[]
    monkeypatch.setattr(backend,'_start_job',started.append)
    assert backend.recover_interrupted_jobs()==[jid]
    assert started==[jid]
    with backend.db() as conn:
        j=conn.execute('SELECT status,recovery_attempts FROM jobs WHERE id=?',(jid,)).fetchone()
        assert (j['status'],j['recovery_attempts'])==('queued',1)
        conn.execute("UPDATE jobs SET status='processing' WHERE id=?",(jid,))
    assert backend.recover_interrupted_jobs()==[jid]
    with backend.db() as conn:
        j=conn.execute('SELECT recovery_attempts FROM jobs WHERE id=?',(jid,)).fetchone()
        assert j['recovery_attempts']==2
        conn.execute("UPDATE jobs SET status='processing' WHERE id=?",(jid,))
    assert backend.recover_interrupted_jobs()==[]
    with backend.db() as conn:
        j=conn.execute('SELECT status,details FROM jobs WHERE id=?',(jid,)).fetchone()
        assert j['status']=='failed'
        assert 'gián đoạn' in json.loads(j['details'])['error']
        events=[x['action'] for x in conn.execute('SELECT action FROM audits WHERE job_id=?',(jid,))]
        assert events.count('job_recovered')==2
        assert 'recovery_failed' in events


def test_missing_video_is_failed_on_restart(monkeypatch,tmp_path):
    backend=_setup(monkeypatch,tmp_path)
    jid=_db_job(backend,tmp_path,'queued')
    (tmp_path/'uploads'/f'{jid}.mp4').unlink()
    started=[]
    monkeypatch.setattr(backend,'_start_job',started.append)
    assert backend.recover_interrupted_jobs()==[]
    assert not started
    with backend.db() as conn:
        assert conn.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()['status']=='failed'


def test_processing_job_cannot_be_claimed_twice(monkeypatch,tmp_path):
    backend=_setup(monkeypatch,tmp_path)
    jid=_db_job(backend,tmp_path,'processing')
    # A worker should reject a second concurrent execution before touching any video.
    backend._analyze_job(jid)
    with backend.db() as conn:
        assert conn.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()['status']=='processing'


def test_real_video_pipeline_records_stage_timing(monkeypatch,tmp_path,stub_perception):
    backend=_setup(monkeypatch,tmp_path)
    monkeypatch.setenv('VLM_ENABLED','0')
    monkeypatch.setattr(backend,'OCR_MAX_FRAMES',2)
    from fastapi.testclient import TestClient
    client=TestClient(backend.app)
    product=client.post('/api/products',json={'sku':'S2','name':'Baby','brand':'A','claims':[],'banned':[]}).json()
    video=tmp_path/'test.mp4'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),5,(160,96))
    assert writer.isOpened()
    for i in range(17):
        frame=np.full((96,160,3),110,dtype=np.uint8)
        cv2.putText(frame,str(i),(10,55),cv2.FONT_HERSHEY_SIMPLEX,.8,(240,240,240),2)
        writer.write(frame)
    writer.release()
    with video.open('rb') as file:
        r=client.post('/api/jobs',data={'product_id':product['id']},files={'file':('test.mp4',file,'video/mp4')})
    assert r.status_code==200
    jid=r.json()['id']
    for _ in range(100):
        job=client.get('/api/jobs/'+jid).json()
        if job['status'] in ('completed','failed'):break
        time.sleep(.05)
    assert job['status']=='completed',job['details']
    timing=job['details']['timings']
    assert timing['ocr_frames']==2
    for stage in ('ocr_seconds','asr_seconds','sampling_seconds','visual_seconds','vlm_seconds','total_seconds'):
        assert stage in timing and timing[stage]>=0
    assert job['details']['coverage']['vlm']=='disabled'
