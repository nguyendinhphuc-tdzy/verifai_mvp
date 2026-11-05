"""Integration test with mocked VLM. Does not claim real model quality."""
import os,time
from pathlib import Path
import cv2
import numpy as np
from fastapi.testclient import TestClient
from verifai_core.vlm import VLMResult


def test_vlm_end_to_end_with_mock(tmp_path,monkeypatch,stub_perception):
    import backend
    monkeypatch.setenv('VLM_ENABLED','1')
    monkeypatch.setenv('VLM_MAX_FRAMES','2')
    monkeypatch.setenv('VLM_MAX_PAIRS','1')
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    backend.UPLOAD.mkdir();backend.FRAMES.mkdir()
    backend.init()

    class MockVLM:
        model='mock-gemini'
        def __init__(self):pass
        def check(self):return {'ready':True,'message':'ready'}
        def analyze(self,images,product,task):
            if task=='pair':
                return VLMResult.model_validate({'summary':'Pair checked','observations':[],
                    'issues':[{'code':'VIS-02','description':'Packaging appears different between frames',
                               'visible_basis':'Brand mark changes color and letters','confidence':0.87,'frame_index':0}]})
            return VLMResult.model_validate({'summary':'Single frame checked',
                'observations':[{'description':'A baby product in a box','category':'product',
                                 'confidence':0.8,'frame_index':0}], 'issues':[]})
    monkeypatch.setattr(backend,'GeminiVLM',MockVLM)
    client=TestClient(backend.app)
    p=client.post('/api/products',json={'sku':'MB-01','name':'Baby item','brand':'Brand','price':100000,
                                        'claims':[],'banned':[]}).json()
    vid=tmp_path/'clip.mp4';writer=cv2.VideoWriter(str(vid),cv2.VideoWriter_fourcc(*'mp4v'),5,(320,180))
    assert writer.isOpened()
    for i in range(35):
        image=np.zeros((180,320,3),np.uint8);image[:]=(95,115,120)
        cv2.rectangle(image,(25+i,25),(160+i,140),(20,30,180),-1)
        cv2.putText(image,'BRAND',(40+i,75),cv2.FONT_HERSHEY_SIMPLEX,0.65,(255,255,255),2)
        writer.write(image)
    writer.release()
    with vid.open('rb') as f:
        resp=client.post('/api/jobs',data={'product_id':p['id'],'rights':'self_created'},files={'file':('clip.mp4',f,'video/mp4')})
    assert resp.status_code==200,resp.text
    jid=resp.json()['id']
    for _ in range(100):
        job=client.get(f'/api/jobs/{jid}').json()
        if job['status'] in ('completed','failed'):break
        time.sleep(.1)
    assert job['status']=='completed',job['details']
    assert job['details']['coverage']['vlm']=='ok'
    assert job['details']['vlm']['calls_succeeded']>=3
    assert any(f['code']=='VIS-02' and f['source']=='vlm' for f in job['findings'])
    assert job['details']['normalization']['canonical_count']>=1
    assert any(e['kind']=='vlm_observation' for e in job['evidence'])
    # A candidate may be absent if the synthetic video is classified as cuts;
    # the VLM single-frame observations must still be persisted and auditable.
    for finding in job['findings']:
        if finding['source']=='vlm':
            assert finding['severity']=='medium'
            assert finding['evidence_id'] in [e['id'] for e in job['evidence']]
    export=client.get(f'/api/jobs/{jid}/evidence/export')
    assert export.status_code==200
    assert export.json()['schema_version']=='verifai-evidence-2.0'
    assert export.json()['evidence']==job['evidence']
    review=client.post(f'/api/jobs/{jid}/review',json={'decision':'Pass','reviewer':'Reviewer A'})
    assert review.status_code==200
    rerun=client.post(f'/api/jobs/{jid}/reanalyze')
    assert rerun.status_code==200
    assert client.get(f'/api/jobs/{jid}').json()['review_decision'] is None
    for _ in range(100):
        rerun_job=client.get(f'/api/jobs/{jid}').json()
        if rerun_job['status'] in ('completed','failed'):break
        time.sleep(.1)
    assert rerun_job['status']=='completed',rerun_job['details']
    assert any(a['action']=='reanalyze_requested' for a in rerun_job['audits'])


def test_unavailable_vlm_degrades_to_review_without_fake_issues(tmp_path,monkeypatch,stub_perception):
    import backend
    monkeypatch.setenv('VLM_ENABLED','1')
    monkeypatch.setattr(backend,'DATA',tmp_path)
    monkeypatch.setattr(backend,'DB',tmp_path/'verifai.sqlite3')
    monkeypatch.setattr(backend,'UPLOAD',tmp_path/'uploads')
    monkeypatch.setattr(backend,'FRAMES',tmp_path/'frames')
    backend.UPLOAD.mkdir();backend.FRAMES.mkdir();backend.init()

    class UnavailableVLM:
        def __init__(self):pass
        def check(self):return {'ready':False,'message':'model not installed'}
    monkeypatch.setattr(backend,'GeminiVLM',UnavailableVLM)
    client=TestClient(backend.app)
    p=client.post('/api/products',json={'sku':'A','name':'B','brand':'C','claims':[],'banned':[]}).json()
    video=tmp_path/'short.mp4';writer=cv2.VideoWriter(str(video),cv2.VideoWriter_fourcc(*'mp4v'),5,(100,80))
    for i in range(15):writer.write(np.full((80,100,3),130,dtype=np.uint8))
    writer.release()
    with video.open('rb') as f:
        jid=client.post('/api/jobs',data={'product_id':p['id'],'rights':'self_created'},files={'file':('short.mp4',f,'video/mp4')}).json()['id']
    for _ in range(100):
        job=client.get('/api/jobs/'+jid).json()
        if job['status'] in ('completed','failed'):break
        time.sleep(.1)
    assert job['status']=='completed',job['details']
    assert job['details']['coverage']['vlm']=='error'
    assert job['details']['vlm']['calls_succeeded']==0
    assert not [e for e in job['evidence'] if e['kind'].startswith('vlm')]
    assert job['decision']=='Needs Review'
