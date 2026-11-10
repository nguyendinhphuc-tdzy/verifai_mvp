"""A3 full API persistence/export test on a real generated MP4 with stubbed OCR/ASR."""
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient


def test_verification_report_persisted_and_exported(tmp_path, monkeypatch):
    import backend
    monkeypatch.setenv('VLM_ENABLED', '0')
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    backend.UPLOAD.mkdir()
    backend.FRAMES.mkdir()
    backend.init()
    monkeypatch.setattr(backend,'frame_ocr',lambda frame: ([
        ('Giá bán 99k',0.94),
        ('Sản phẩm chữa khỏi hoàn toàn',0.9),
    ],'ok'))
    monkeypatch.setattr(backend,'transcribe',lambda path: ([
        {'at':0.0,'text':'Giá bán 149k','score':None},
        {'at':1.0,'text':'Sản phẩm không chữa khỏi hoàn toàn','score':None},
    ],'ok'))
    client=TestClient(backend.app)
    product=client.post('/api/products',json={
        'sku':'A3-REF','name':'Mẫu hàng mẹ và bé','brand':'Test',
        'price':149000,'claims':[],'banned':['chữa khỏi hoàn toàn'],
        'reference_status':'reviewed','reference_note':'Nhãn mẫu đối chiếu thủ công',
    })
    assert product.status_code==200,product.text
    video=tmp_path/'a3-sample.mp4'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),5,(128,80))
    assert writer.isOpened()
    for i in range(20):
        writer.write(np.full((80,128,3),110,dtype=np.uint8))
    writer.release()
    with video.open('rb') as f:
        uploaded=client.post('/api/jobs',data={'product_id':product.json()['id']},
               files={'file':('a3-sample.mp4',f,'video/mp4')})
    assert uploaded.status_code==200,uploaded.text
    jid=uploaded.json()['id']
    for _ in range(160):
        job=client.get('/api/jobs/'+jid).json()
        if job['status'] in ('completed','failed'):
            break
        time.sleep(.05)
    assert job['status']=='completed',job['details']
    assert job['review_decision'] is None
    # Reviewed reference + OCR-read wrong price and asserted restricted claim.
    assert job['decision']=='Regenerate'
    assert job['details']['verification_version']=='verification-v3.0-alpha3'
    verify=job['details']['verification']
    assert verify['status']=='REVIEW_REQUIRED'
    assert verify['requires_human_review'] is True and verify['is_final_decision'] is False
    assert verify['conflict_count']==2
    assert {c['category'] for c in verify['checks'] if c['status']=='CONFLICT'}=={'price','claim'}
    valid_ids={item['id'] for item in job['evidence']}
    for check in verify['checks']:
        assert all(eid in valid_ids for eid in check['evidence_ids'])
    assert any(f['code']=='PRICE-01' for f in job['findings'])
    assert any(f['code']=='CLAIM-01' for f in job['findings'])

    direct=client.get('/api/jobs/'+jid+'/verification')
    assert direct.status_code==200 and direct.json()==verify
    export=client.get('/api/jobs/'+jid+'/evidence/export')
    assert export.status_code==200
    assert export.json()['details']['verification']==verify
    review=client.post('/api/jobs/'+jid+'/review',
                       json={'decision':'Needs Review','reviewer':'Local Tester'})
    assert review.status_code==200
    assert client.get('/api/jobs/'+jid+'/verification').json()==verify


def test_unfinished_job_verification_not_available(tmp_path,monkeypatch):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    backend.UPLOAD.mkdir()
    backend.FRAMES.mkdir()
    backend.init()
    product=TestClient(backend.app).post('/api/products',json={
        'sku':'A3-UNFINISHED','name':'Sample','brand':'Test','claims':[],'banned':[],
    }).json()['id']
    with backend.db() as c:
        c.execute('''INSERT INTO jobs(id,filename,stored_name,product_id,status,created_at,details)
                     VALUES(?,?,?,?,?,?,?)''',
                  ('pending-a3','waiting.mp4','waiting.mp4',product,'queued',backend.utc(),'{}'))
    api=TestClient(backend.app)
    assert api.get('/api/jobs/pending-a3/verification').status_code==409
    with backend.db() as c:
        c.execute('UPDATE jobs SET status=? WHERE id=?',('completed','pending-a3'))
    assert api.get('/api/jobs/pending-a3/verification').status_code==404
