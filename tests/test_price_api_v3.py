"""Real upload/DB/findings/export integration using fixed OCR and ASR evidence.

Exercises the production API path without downloading any inference weights.
"""
import time

import cv2
import numpy as np
from fastapi.testclient import TestClient


def test_price_v3_findings_and_evidence_are_persisted(tmp_path, monkeypatch):
    import backend
    monkeypatch.setenv('VLM_ENABLED', '0')
    monkeypatch.setattr(backend, 'DATA', tmp_path)
    monkeypatch.setattr(backend, 'DB', tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend, 'UPLOAD', tmp_path/'uploads')
    monkeypatch.setattr(backend, 'FRAMES', tmp_path/'frames')
    backend.UPLOAD.mkdir()
    backend.FRAMES.mkdir()
    backend.init()
    monkeypatch.setattr(backend, 'frame_ocr', lambda frame: ([
        ('99.000dd', 0.95),
        ('99.000đd', 0.93),
        ('Giá sale 99k, giá gốc 149k', 0.91),
        ('Năm sản xuất 2026', 0.89),
    ], 'ok'))
    monkeypatch.setattr(backend, 'transcribe', lambda path: ([
        {'at':0.0,'text':'Giá gốc 149k và giá khuyến mãi 99k', 'score':None},
    ],'ok'))
    client=TestClient(backend.app)
    product=client.post('/api/products',json={
        'sku':'MB-PRICE', 'name':'Sản phẩm dành cho bé', 'brand':'Test',
        'price':149000, 'claims':[], 'banned':[],
    })
    assert product.status_code==200,product.text
    video=tmp_path/'price.mp4'
    writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),5,(128,80))
    assert writer.isOpened()
    for _ in range(15):
        writer.write(np.full((80,128,3),150,dtype=np.uint8))
    writer.release()
    with video.open('rb') as file:
        r=client.post('/api/jobs',data={'product_id':product.json()['id']},
                      files={'file':('price.mp4',file,'video/mp4')})
    assert r.status_code==200,r.text
    jid=r.json()['id']
    for _ in range(100):
        job=client.get('/api/jobs/'+jid).json()
        if job['status'] in ('completed','failed'):
            break
        time.sleep(.05)
    assert job['status']=='completed',job['details']
    assert job['details']['price_parser_version']=='price-v3.0-alpha2'
    assert job['decision']=='Needs Review', 'Price mismatch is reviewer candidate, not automatic rejection'
    price_flags=[f for f in job['findings'] if f['code']=='PRICE-01']
    assert price_flags,job['findings']
    assert all(f['severity']=='medium' and f['source']=='price_rule_v3' for f in price_flags)
    assert all(f['evidence_id'] in {e['id'] for e in job['evidence']} for f in price_flags)
    assert all(f['metadata']['price_assessment']['status']=='MISMATCH' for f in price_flags)
    # Real OCR variants from VID_LOI01: preserve the raw string and its
    # timestamp while creating review-only candidate findings.
    corrupted=[e for e in job['evidence']
               if e['kind']=='ocr' and e['content'] in ('99.000dd','99.000đd')]
    assert corrupted,job['evidence']
    assert all(e['metadata']['price_v3']['status']=='MISMATCH' for e in corrupted)
    assert any(f['evidence_id'] in {e['id'] for e in corrupted}
               for f in price_flags)
    sale_evidence=[e for e in job['evidence'] if 'Giá sale' in e['content']]
    assert sale_evidence
    assert all(e['metadata']['price_v3']['status']=='INSUFFICIENT_EVIDENCE' for e in sale_evidence)
    assert not [f for f in job['findings'] if '2026' in f['detail']]
    exported=client.get('/api/jobs/'+jid+'/evidence/export')
    assert exported.status_code==200
    assert exported.json()['evidence']==job['evidence']
