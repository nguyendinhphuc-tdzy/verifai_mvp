import json
from pathlib import Path
import cv2
import numpy as np
import pytest
from verifai_core.evidence import RawEvidence, normalize_evidence
from verifai_core.visual import compare_frames, select_pairs, visual_pairs
from verifai_core.vlm import OllamaVLM, VLMError


def test_evidence_normalization_merges_only_adjacent_same_source():
    raw = [
        RawEvidence('ocr0','ocr',0,' Giá   100.000đ ',0.6,'000.jpg',source_model='paddleocr'),
        RawEvidence('asr0','asr',1,'Giá 100.000đ',None,source_model='whisper'),
        RawEvidence('ocr1','ocr',2,'Giá 100.000đ',0.9,'001.jpg',source_model='paddleocr'),
        RawEvidence('ocr2','ocr',12,'Giá 100.000đ',0.7,'006.jpg',source_model='paddleocr'),
        RawEvidence('vlm0','vlm_issue',2,'Giá 100.000đ',0.8,'001.jpg',source_model='qwen3-vl'),
    ]
    items,mapping=normalize_evidence(raw)
    assert len(items)==4
    assert mapping['ocr0']==mapping['ocr1']
    assert mapping['ocr2']!=mapping['ocr1']
    assert mapping['asr0']!=mapping['ocr0']
    assert mapping['vlm0']!=mapping['ocr0']
    merged=items[mapping['ocr0']]
    assert merged.timestamp==0 and merged.end_timestamp==2
    assert merged.score==0.9 and len(merged.metadata['sources'])==2
    assert merged.metadata['frames']==['000.jpg','001.jpg']
    assert len({e.fingerprint for e in items})==len(items)


def test_visual_signals_are_conservative_and_shot_aware():
    a=np.zeros((200,300,3),np.uint8);a[:]=(90,110,120)
    b=a.copy();cv2.rectangle(b,(30,30),(160,150),(20,20,230),-1)
    cut=np.zeros_like(a);cut[:]=(220,30,20)
    def frame(image,t,name):return {'image':image,'at':t,'frame':name}
    unchanged=compare_frames(frame(a,0,'000.jpg'),frame(a,2,'001.jpg'))
    changed=compare_frames(frame(a,0,'000.jpg'),frame(b,2,'001.jpg'))
    transition=compare_frames(frame(a,0,'000.jpg'),frame(cut,2,'001.jpg'))
    assert not unchanged.candidate and unchanged.likely_same_shot
    assert changed.candidate and changed.likely_same_shot
    assert transition.scene_cut and not transition.likely_same_shot
    assert select_pairs([unchanged,changed,transition],1)[0].frame2=='001.jpg'


def test_ollama_adapter_json_schema_and_safety(monkeypatch,tmp_path):
    frame=tmp_path/'000.jpg';frame.write_bytes(b'fake-jpeg')
    vlm=OllamaVLM(model='qwen3-vl:4b-instruct',base_url='http://127.0.0.1:11434')
    seen=[]
    def fake_request(path,body,timeout=None):
        seen.append((path,body))
        return {'message':{'content':json.dumps({'summary':'Product in view',
            'observations':[{'description':'Blue bottle','category':'product','confidence':0.85,'frame_index':0}],
            'issues':[{'code':'VIS-02','description':'Morph','visible_basis':'Label changes','confidence':0.91,'frame_index':0},
                      {'code':'VIS-03','description':'Visible text distorted','visible_basis':'Text is irregular','confidence':0.72,'frame_index':0}]})}}
    monkeypatch.setattr(vlm,'_request',fake_request)
    p={'sku':'ABC','name':'Milk','brand':'Brand','claims':[],'banned':[]}
    result=vlm.analyze([frame],p,'single')
    assert [issue.code for issue in result.issues]==['VIS-03']
    assert seen[0][0]=='/api/chat'
    assert seen[0][1]['stream'] is False
    assert isinstance(seen[0][1]['format'],dict)
    assert len(seen[0][1]['messages'][0]['images'])==1
    with pytest.raises(VLMError):
        OllamaVLM(base_url='https://untrusted.example.com')


def test_vlm_invalid_json_is_rejected(monkeypatch,tmp_path):
    frame=tmp_path/'000.jpg';frame.write_bytes(b'x')
    vlm=OllamaVLM()
    monkeypatch.setattr(vlm,'_request',lambda *args,**kw:{'message':{'content':'not-json'}})
    p={'sku':'A','name':'B','brand':'C','claims':[],'banned':[]}
    with pytest.raises(VLMError):vlm.analyze([frame],p,'single')


def test_v1_sqlite_migration_preserves_existing_records(tmp_path,monkeypatch):
    import sqlite3
    import backend
    db_path=tmp_path/'old.sqlite3'
    with sqlite3.connect(db_path) as c:
        c.executescript('''
        CREATE TABLE evidence(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,kind TEXT NOT NULL,timestamp REAL NOT NULL,content TEXT NOT NULL,score REAL,frame TEXT);
        CREATE TABLE findings(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,code TEXT NOT NULL,severity TEXT NOT NULL,timestamp REAL NOT NULL,detail TEXT NOT NULL,evidence_id INTEGER,flag_review TEXT DEFAULT 'unreviewed');
        INSERT INTO evidence(job_id,kind,timestamp,content,score,frame) VALUES('job-old','ocr',1,'100000',0.7,'000.jpg');
        INSERT INTO findings(job_id,code,severity,timestamp,detail,evidence_id) VALUES('job-old','PRICE-01','high',1,'old finding',1);
        ''')
    monkeypatch.setattr(backend,'DB',db_path)
    backend.init()
    with sqlite3.connect(db_path) as c:
        assert c.execute('SELECT content FROM evidence').fetchone()[0]=='100000'
        assert c.execute('SELECT detail FROM findings').fetchone()[0]=='old finding'
        ev_columns={r[1] for r in c.execute('PRAGMA table_info(evidence)')}
        finding_columns={r[1] for r in c.execute('PRAGMA table_info(findings)')}
        assert {'metadata','fingerprint','end_timestamp','source_model','frame2'} <= ev_columns
        assert {'source','confidence','evidence_refs','metadata'} <= finding_columns
    backend.init()  # idempotent
