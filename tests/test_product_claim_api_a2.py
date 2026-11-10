"""Product Truth API source/revision migration and claim evidence integration."""
import json
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient


def setup_backend(monkeypatch,tmp_path):
    import backend
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    backend.UPLOAD.mkdir(exist_ok=True)
    backend.FRAMES.mkdir(exist_ok=True)
    backend.init()
    return backend,TestClient(backend.app)


def reference(**kwargs):
    return {'sku':'BABY-01','name':'Sản phẩm cho bé','brand':'Sample',
            'price':149000,'claims':['Dưỡng ẩm'], 'banned':['chữa khỏi hoàn toàn'],
            'reference_url':'https://example.org/reference',
            'reference_note':'Đối chiếu nhãn sản phẩm',
            'reference_status':'reviewed',**kwargs}


def test_reference_creation_revision_update_and_history(tmp_path,monkeypatch):
    backend,client=setup_backend(monkeypatch,tmp_path)
    p=client.post('/api/products',json=reference())
    assert p.status_code==200,p.text
    pid=p.json()['id']
    original=client.get('/api/products/'+pid).json()
    assert original['revision']==1 and original['reference_status']=='reviewed'
    assert original['reference_url']=='https://example.org/reference'
    assert original['banned']==['chữa khỏi hoàn toàn']

    duplicate=client.post('/api/products',json={**reference(),'sku':'baby-01'})
    assert duplicate.status_code==409

    payload=reference()
    payload.update(expected_revision=1,price=159000,reference_note='Giá tham chiếu đã được đối chiếu lại')
    updated=client.put('/api/products/'+pid,json=payload)
    assert updated.status_code==200,updated.text
    assert updated.json()['revision']==2
    assert client.put('/api/products/'+pid,json=payload).status_code==409
    p2=client.get('/api/products/'+pid).json()
    assert p2['price']==159000 and p2['revision']==2
    history=client.get('/api/products/'+pid+'/history').json()
    assert [h['revision'] for h in history]==[1,2]
    assert [h['event'] for h in history]==['created','updated']
    assert json.loads(history[-1]['snapshot'])['price']==159000


def test_invalid_truth_is_rejected(tmp_path,monkeypatch):
    _,client=setup_backend(monkeypatch,tmp_path)
    cases=[
        {**reference(),'sku':' '},
        {**reference(),'claims':['chữa khỏi hoàn toàn']},
        {**reference(),'reference_url':'javascript:alert(1)'},
        {**reference(),'reference_status':'reviewed','reference_url':'','reference_note':''},
        {**reference(),'reference_status':'validated_automatically'},
    ]
    for payload in cases:
        r=client.post('/api/products',json=payload)
        assert r.status_code==422,(r.status_code,r.text)


def test_legacy_products_remain_usable_without_meta(tmp_path,monkeypatch):
    backend,client=setup_backend(monkeypatch,tmp_path)
    with backend.db() as conn:
        conn.execute('''INSERT INTO products VALUES(?,?,?,?,?,?,?,?)''',
                     ('legacy-id','LEGACY','Legacy Name','Brand',100000,'["dưỡng ẩm"]',
                      '["chữa khỏi hoàn toàn"]',backend.utc()))
    p=client.get('/api/products/legacy-id')
    assert p.status_code==200
    assert p.json()['reference_status']=='unverified' and p.json()['revision']==1
    payload={**reference(),'sku':'LEGACY','expected_revision':1}
    out=client.put('/api/products/legacy-id',json=payload)
    assert out.status_code==200,out.text
    assert out.json()['revision']==2


def test_claim_evidence_and_product_truth_snapshot(tmp_path,monkeypatch):
    backend,client=setup_backend(monkeypatch,tmp_path)
    monkeypatch.setenv('VLM_ENABLED','0')
    monkeypatch.setattr(backend,'frame_ocr',lambda frame: ([
        ('Sản phẩm chữa khỏi hoàn toàn',.9),
        ('Sản phẩm không chữa khỏi hoàn toàn',.9),
        ('Nghe nói chữa khỏi hoàn toàn',.8),
    ],'ok'))
    monkeypatch.setattr(backend,'transcribe',lambda path: ([
        {'at':0.0,'text':'Không có tác dụng chữa khỏi hoàn toàn','score':None},
    ],'ok'))
    product=client.post('/api/products',json=reference()).json()
    video=tmp_path/'clip.mp4'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),5,(128,80))
    assert writer.isOpened()
    for i in range(13):
        writer.write(np.full((80,128,3),110,dtype=np.uint8))
    writer.release()
    with video.open('rb') as f:
        job=client.post('/api/jobs',data={'product_id':product['id']},
                        files={'file':('clip.mp4',f,'video/mp4')})
    assert job.status_code==200,job.text
    jid=job.json()['id']
    for _ in range(100):
        d=client.get('/api/jobs/'+jid).json()
        if d['status'] in ('completed','failed'):break
        time.sleep(.05)
    assert d['status']=='completed',d['details']
    # Reviewed Product Truth + asserted restricted claim read by OCR on every frame.
    assert d['decision']=='Regenerate'
    assert d['details']['claim_rule_version']=='claim-v3.0-alpha2'
    snapshot=d['details']['product_truth_snapshot']
    assert snapshot['revision']==1 and snapshot['reference_status']=='reviewed'
    flags=[f for f in d['findings'] if f['code']=='CLAIM-01']
    assert flags
    assert all(f['severity'] in ('high','medium') and f['source']=='claim_rule_v3' for f in flags)
    assert all(f['metadata']['claim_assessment']['state']=='asserted' for f in flags)
    assert all(f['evidence_id'] in {e['id'] for e in d['evidence']} for f in flags)
    events=[m for e in d['evidence'] if e['kind'] in ('ocr','asr')
            for m in e.get('metadata',{}).get('claim_v3',{}).get('mentions',[])]
    assert {'asserted','negated','uncertain'} <= {m['state'] for m in events}
    export=client.get('/api/jobs/'+jid+'/evidence/export')
    assert export.status_code==200
    assert export.json()['evidence']==d['evidence']
    assert client.post('/api/jobs/'+jid+'/review',
                       json={'decision':'Needs Review','reviewer':'Local Reviewer'}).status_code==200
    assert d['details']['product_truth_snapshot']['price']==149000
