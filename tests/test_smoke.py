"""v1 compatibility smoke test with isolated storage."""
import time
from fastapi.testclient import TestClient
import cv2
import numpy as np


def test_end_to_end(tmp_path, monkeypatch, stub_perception):
    import backend
    monkeypatch.setenv('VLM_ENABLED','0')
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    backend.UPLOAD.mkdir();backend.FRAMES.mkdir()
    backend.init()
    client=TestClient(backend.app)
    assert client.get('/api/health').status_code==200
    p=client.post('/api/products',json={'sku':'S1','name':'Test stroller','brand':'demo','price':100000,'claims':[],'banned':['test forbidden']})
    assert p.status_code==200,p.text
    video=tmp_path/'sample.mp4';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),5,(160,100))
    assert writer.isOpened()
    for i in range(20):
        frame=np.full((100,160,3),160,dtype=np.uint8)
        cv2.putText(frame,str(i),(30,50),cv2.FONT_HERSHEY_SIMPLEX,1,(30,30,30),2)
        writer.write(frame)
    writer.release()
    with video.open('rb') as f:
        r=client.post('/api/jobs',data={'product_id':p.json()['id'],'rights':'self_created'},
                      files={'file':('sample.mp4',f,'video/mp4')})
    assert r.status_code==200,r.text
    jid=r.json()['id']
    for _ in range(100):
        j=client.get('/api/jobs/'+jid).json()
        if j['status'] in ('completed','failed'):break
        time.sleep(.1)
    assert j['status']=='completed',j['details']
    assert j['decision']=='Needs Review'
    assert j['details']['coverage']['vlm']=='disabled'
    assert client.post('/api/jobs/'+jid+'/review',json={'decision':'Pass','reviewer':'Test Reviewer'}).status_code==200
    assert client.post('/api/jobs/'+jid+'/labels',json={'annotator':'A','label':'clean'}).status_code==200
    metrics=client.get('/api/metrics').json()
    assert metrics['evaluated']==0  # single label is insufficient for actual evaluation
    assert metrics['prediction_policy']=='candidate-v1-2026-10'
    home_page=client.get('/')
    assert home_page.status_code==200
    assert 'Bắt đầu kiểm duyệt' in home_page.text and 'href="/app"' in home_page.text
    workspace=client.get('/app')
    assert workspace.status_code==200
    assert 'Danh sách duyệt' in workspace.text
