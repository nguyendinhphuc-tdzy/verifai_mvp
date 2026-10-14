"""VerifAI feasibility MVP. Local-only, modular evidence-first analysis."""
import json, os, re, sqlite3, threading, time, uuid, hashlib, subprocess, shutil
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Optional
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from verifai_core.evidence import RawEvidence, normalize_evidence
from verifai_core.visual import visual_pairs, evenly_spaced, select_pairs
from verifai_core.vlm import OllamaVLM, VLMError, vlm_enabled, PROMPT_VERSION

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('VERIFAI_DATA', str(BASE/'data'))).resolve()
UPLOAD = DATA/'uploads'; FRAMES=DATA/'frames'; DB=DATA/'verifai.sqlite3'
MAX_UPLOAD=int(os.environ.get('MAX_VIDEO_MB','150'))*1024*1024
MAX_DURATION=int(os.environ.get('MAX_VIDEO_SECONDS','180'))
for p in (DATA,UPLOAD,FRAMES): p.mkdir(parents=True,exist_ok=True)
app=FastAPI(title='VerifAI MVP API',version='2.0.0')
app.mount('/static',StaticFiles(directory=str(BASE/'static')),name='static')

def utc(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
@contextmanager
def db():
    conn=sqlite3.connect(DB,timeout=30)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    try: yield conn; conn.commit()
    finally: conn.close()

def init():
    with db() as c:
        c.executescript('''CREATE TABLE IF NOT EXISTS products(id TEXT PRIMARY KEY,sku TEXT NOT NULL,name TEXT NOT NULL,brand TEXT NOT NULL,price INTEGER,claims TEXT NOT NULL,banned TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,filename TEXT NOT NULL,stored_name TEXT NOT NULL,product_id TEXT NOT NULL,status TEXT NOT NULL,decision TEXT,review_decision TEXT,reviewer TEXT,review_note TEXT,source_url TEXT,rights TEXT,created_at TEXT NOT NULL,finished_at TEXT,details TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS evidence(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,kind TEXT NOT NULL,timestamp REAL NOT NULL,content TEXT NOT NULL,score REAL,frame TEXT);
        CREATE TABLE IF NOT EXISTS findings(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,code TEXT NOT NULL,severity TEXT NOT NULL,timestamp REAL NOT NULL,detail TEXT NOT NULL,evidence_id INTEGER,flag_review TEXT DEFAULT 'unreviewed');
        CREATE TABLE IF NOT EXISTS audits(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,actor TEXT NOT NULL,action TEXT NOT NULL,payload TEXT NOT NULL,created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS labels(id INTEGER PRIMARY KEY AUTOINCREMENT,job_id TEXT NOT NULL,annotator TEXT NOT NULL,label TEXT NOT NULL,notes TEXT,created_at TEXT NOT NULL);''')
        # Non-destructive migration: old v1 databases retain all jobs/reviews/labels.
        migrations = {
            'evidence': {
                'end_timestamp': 'REAL', 'frame2': 'TEXT', 'source_model': 'TEXT',
                'fingerprint': 'TEXT', 'metadata': "TEXT NOT NULL DEFAULT '{}'"
            },
            'findings': {
                'source': "TEXT NOT NULL DEFAULT 'rule'", 'confidence': 'REAL',
                'evidence_refs': "TEXT NOT NULL DEFAULT '[]'", 'metadata': "TEXT NOT NULL DEFAULT '{}'"
            }
        }
        for table, additions in migrations.items():
            existing = {r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
            for name, ddl in additions.items():
                if name not in existing:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {ddl}')
init()

def audit(c,jid,actor,action,payload):c.execute('INSERT INTO audits(job_id,actor,action,payload,created_at) VALUES(?,?,?,?,?)',(jid,actor,action,json.dumps(payload,ensure_ascii=False),utc()))

def rowdict(r):return dict(r) if r else None

def product_dict(r):
    d=rowdict(r)
    if d:
        d['claims']=json.loads(d['claims']);d['banned']=json.loads(d['banned'])
    return d

class ProductIn(BaseModel):
    sku:str=Field(min_length=1,max_length=80)
    name:str=Field(min_length=1,max_length=180)
    brand:str=Field(default='',max_length=100)
    price:Optional[int]=Field(default=None,ge=0)
    claims:list[str]=Field(default_factory=list)
    banned:list[str]=Field(default_factory=list)

@app.get('/')
def home():return FileResponse(BASE/'static'/'index.html')
@app.get('/api/health')
def health():
    enabled = vlm_enabled()
    status = {'ready': False, 'message': 'VLM_ENABLED=0'}
    if enabled:
        try: status = OllamaVLM().check()
        except VLMError as exc: status = {'ready': False, 'message': str(exc)}
    return {'ok':True,'ocr':_has_paddle(),'asr':_has_whisper(),
            'ffmpeg':bool(shutil.which('ffmpeg')),'database':'sqlite',
            'mode':'local feasibility MVP', 'version':'2.0.0',
            'vlm':{'enabled':enabled,'model':os.environ.get('VLM_MODEL','qwen3-vl:4b-instruct'),**status}}
@app.post('/api/products')
def create_product(v:ProductIn):
    pid=uuid.uuid4().hex[:12]
    with db() as c:c.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?,?)',(pid,v.sku.strip(),v.name.strip(),v.brand.strip(),v.price,json.dumps(v.claims,ensure_ascii=False),json.dumps(v.banned,ensure_ascii=False),utc()))
    return {'id':pid}
@app.get('/api/products')
def products():
    with db() as c:return [product_dict(r) for r in c.execute('SELECT * FROM products ORDER BY created_at DESC')]

_ocr=None;_whisper=None;_model_lock=threading.Lock()
def _has_paddle():
    try: import importlib.util;return importlib.util.find_spec('paddleocr') is not None
    except Exception:return False
def _has_whisper():
    try: import importlib.util;return importlib.util.find_spec('faster_whisper') is not None
    except Exception:return False

def frame_ocr(frame):
    global _ocr
    if not _has_paddle():return [],'not_installed'
    try:
        import cv2
        from paddleocr import PaddleOCR
        with _model_lock:
            if _ocr is None:_ocr=PaddleOCR(use_doc_orientation_classify=False,use_doc_unwarping=False,use_textline_orientation=False)
            result=_ocr.predict(frame)
        lines=[]
        for item in result:
            r=item.json if hasattr(item,'json') else item
            if callable(r):r=r()
            if isinstance(r,dict):
                r=r.get('res',r)
                for txt,score in zip(r.get('rec_texts',[]),r.get('rec_scores',[])):
                    if str(txt).strip():lines.append((str(txt),float(score)))
        return lines,'ok'
    except Exception as e:return [],f'error: {str(e)[:180]}'

def transcribe(path):
    global _whisper
    if not _has_whisper():return [],'not_installed'
    try:
        from faster_whisper import WhisperModel
        with _model_lock:
            if _whisper is None:_whisper=WhisperModel(os.environ.get('WHISPER_MODEL','tiny'),device='cpu',compute_type='int8')
            segments,_=_whisper.transcribe(str(path),beam_size=2,vad_filter=True,language='vi')
            return [{'at':round(float(s.start),2),'text':s.text.strip(),'score':None} for s in segments if s.text.strip()],'ok'
    except Exception as e:return [],f'error: {str(e)[:180]}'

def normalize(t):
    import unicodedata
    t=unicodedata.normalize('NFKC',str(t)).lower()
    return re.sub(r'\s+',' ',t).strip()

def numeric_prices(s):
    vals=[]
    for m in re.finditer(r'(?<!\d)(\d{1,3}(?:[.,]\d{3})+|\d{4,9})\s*(?:đ|₫|vnd|vnđ|đồng)?',s,re.I):
        raw=m.group(1)
        try:
            n=int(re.sub(r'[.,]','',raw))
            if 1000<=n<=100000000:vals.append((n,m.group(0)))
        except ValueError:pass
    return vals

def analyze(job_id):
    """Asynchronous local prototype pipeline: perception -> normalization -> rules -> review."""
    import cv2
    t0=time.monotonic(); cap=None
    with db() as c:
        j=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not j: return
        p=product_dict(c.execute('SELECT * FROM products WHERE id=?',(j['product_id'],)).fetchone())
        if not p: return
        c.execute('UPDATE jobs SET status=?,decision=NULL,finished_at=NULL WHERE id=?',('processing',job_id))
        c.execute('DELETE FROM findings WHERE job_id=?',(job_id,))
        c.execute('DELETE FROM evidence WHERE job_id=?',(job_id,))
    path=UPLOAD/j['stored_name']
    coverage={'ocr':'not_installed','asr':'not_installed','visual':'heuristic_screening',
              'c2pa':'not_implemented','vlm':'disabled' if not vlm_enabled() else 'pending'}
    raw=[]; findings=[]; sampled=[]; vlm_calls=0; vlm_errors=[]

    def evidence(kind, at, text, score=None, frame=None, frame2=None, source='unknown', meta=None):
        uid=f'ev-{len(raw)}'
        raw.append(RawEvidence(uid,kind,at,text,score,frame,frame2,source,meta or {}))
        return uid

    def flag(code,severity,at,detail,raw_uid=None,source='rule',confidence=None,meta=None):
        findings.append({'code':code,'severity':severity,'at':at,'detail':detail,
                         'uid':raw_uid,'source':source,'confidence':confidence,'metadata':meta or {}})

    try:
        cap=cv2.VideoCapture(str(path))
        if not cap.isOpened(): raise RuntimeError('OpenCV không thể mở video; vui lòng dùng MP4/H.264.')
        fps=float(cap.get(cv2.CAP_PROP_FPS) or 25)
        fps=fps if 0<fps<240 else 25
        total=int(cap.get(cv2.CAP_PROP_FRAME_COUNT)); duration=total/fps if total else 0
        if duration>MAX_DURATION: raise RuntimeError(f'Video vượt giới hạn {MAX_DURATION} giây.')
        interval=max(1,int(fps*max(2, duration/60)))
        processed=0;idx=0; frame_dir=FRAMES/job_id;frame_dir.mkdir(parents=True,exist_ok=True)
        while processed<60:
            ok,frame=cap.read()
            if not ok: break
            if idx%interval==0:
                at=round(idx/fps,2)
                scale=min(1.0,800/max(frame.shape[:2]))
                small=cv2.resize(frame,(max(1,round(frame.shape[1]*scale)),max(1,round(frame.shape[0]*scale))))
                frame_name=f'{processed:03d}.jpg'
                cv2.imwrite(str(frame_dir/frame_name),small,[cv2.IMWRITE_JPEG_QUALITY,80])
                gray=cv2.cvtColor(small,cv2.COLOR_BGR2GRAY)
                blur=float(cv2.Laplacian(gray,cv2.CV_64F).var())
                sampled.append({'at':at,'frame':frame_name,'image':small,'blur':round(blur,1)})
                ocr,ocr_status=frame_ocr(small)
                if ocr_status=='ok' or coverage['ocr']!='ok': coverage['ocr']=ocr_status
                for text,score in ocr:
                    evidence('ocr',at,text,score,frame_name,source='paddleocr',meta={'confidence_kind':'ocr_engine'})
                processed+=1
            idx+=1
        cap.release();cap=None
        speeches,coverage['asr']=transcribe(path)
        for seg in speeches:
            evidence('asr',seg['at'],seg['text'],seg.get('score'),source='faster-whisper',
                     meta={'confidence_kind':'not_provided'})

        signals=visual_pairs(sampled)
        candidates=[v for v in signals if v.candidate]
        for pair in evenly_spaced(candidates,3):
            uid=evidence('visual_signal',pair.at,
                         f'Biến động frame {pair.at:.1f}s → {pair.at2:.1f}s (chỉ báo heuristic, không chứng minh lỗi AI).',
                         None,pair.frame,pair.frame2,'opencv-temporal-v2',
                         {'pair_signal':pair.to_dict(),'paired_timestamp':pair.at2,'confidence_kind':'not_calibrated'})
            if not vlm_enabled():
                flag('VIS-SCREEN','low',pair.at,'Biến động hình ảnh cùng cảnh: cần reviewer xem hai frame; chưa có VLM xác nhận.',
                     uid,source='visual_heuristic',meta={'paired_timestamp':pair.at2})
        blurry=[f for f in sampled if f['blur']<24]
        if len(blurry)>=max(2,int(len(sampled)*.55)) and blurry:
            flag('VIS-06','low',blurry[0]['at'],
                 'Nhiều frame có độ nét thấp (heuristic), không đồng nghĩa lỗi tạo sinh.',source='visual_heuristic')

        if vlm_enabled():
            try:
                client=OllamaVLM()
                readiness=client.check()
                if not readiness['ready']: raise VLMError(readiness['message'])
                frame_limit=max(0,min(8,int(os.environ.get('VLM_MAX_FRAMES','4'))))
                pair_limit=max(0,min(6,int(os.environ.get('VLM_MAX_PAIRS','2'))))
                frame_selection=evenly_spaced(sampled,frame_limit)
                pair_selection=select_pairs(signals,pair_limit)
                def collect(result, selected_frames, task):
                    model=client.model
                    for obs in result.observations:
                        frame=selected_frames[obs.frame_index]
                        evidence('vlm_observation',frame['at'],obs.description,obs.confidence,
                                 frame['frame'],source=model,
                                 meta={'category':obs.category,'task':task,'prompt_version':PROMPT_VERSION,
                                       'confidence_kind':'model_self_reported'})
                    for issue in result.issues:
                        anchor=selected_frames[issue.frame_index]
                        if issue.code=='VIS-02' and task!='pair': continue
                        paired=selected_frames[1-issue.frame_index] if task=='pair' else None
                        uid=evidence('vlm_issue',anchor['at'],
                                     f'{issue.visible_basis} — {issue.description}',issue.confidence,
                                     anchor['frame'],paired['frame'] if paired else None,model,
                                     {'code':issue.code,'task':task,'prompt_version':PROMPT_VERSION,
                                      'visible_basis':issue.visible_basis,
                                      'confidence_kind':'model_self_reported',
                                      'paired_timestamp':paired['at'] if paired else None})
                        # Candidate only: no VLM-only high severity or automatic Regenerate.
                        if issue.confidence>=0.70 and len(issue.visible_basis.strip())>=10:
                            flag(issue.code,'medium',anchor['at'],issue.description,uid,'vlm',issue.confidence,
                                 {'prompt_version':PROMPT_VERSION,'paired_timestamp':paired['at'] if paired else None})
                for f in frame_selection:
                    try:
                        result=client.analyze([frame_dir/f['frame']],p,'single')
                        vlm_calls+=1;collect(result,[f],'single')
                    except (VLMError, OSError, ValueError, IndexError) as exc:
                        vlm_errors.append(f'frame {f["at"]}: {str(exc)[:160]}')
                lookup={f['frame']:f for f in sampled}
                for pair in pair_selection:
                    try:
                        f1,f2=lookup[pair.frame],lookup[pair.frame2]
                        result=client.analyze([frame_dir/f1['frame'],frame_dir/f2['frame']],p,'pair')
                        vlm_calls+=1;collect(result,[f1,f2],'pair')
                    except (VLMError, OSError, ValueError, IndexError) as exc:
                        vlm_errors.append(f'pair {pair.at}-{pair.at2}: {str(exc)[:160]}')
                coverage['vlm']='ok' if vlm_calls and not vlm_errors else 'partial' if vlm_calls else 'error'
            except (VLMError, ValueError) as exc:
                coverage['vlm']='error';vlm_errors.append(str(exc)[:180])
        else:
            coverage['vlm']='disabled'

        normalized,raw_map=normalize_evidence(raw)
        if coverage['ocr']!='ok' and coverage['asr']!='ok':
            flag('COVERAGE','medium',0,'OCR/ASR chưa khả dụng; không thể xác nhận lời nói/chữ trong video.')
        for n,e in enumerate(normalized):
            if e.kind not in ('ocr','asr'): continue
            tx=normalize(e.content)
            # Reference matches are exact text rules; ASR/OCR can still be wrong.
            for banned in p['banned']:
                if banned.strip() and normalize(banned) in tx:
                    flag('CLAIM-01','high',e.timestamp,f'Cụm từ cần kiểm tra: “{banned}”',
                         source='rule',confidence=e.score,meta={'canonical_index':n})
            for price,price_text in numeric_prices(tx):
                if p['price'] is not None and price!=p['price']:
                    flag('PRICE-01','high',e.timestamp,
                         f'Giá quan sát {price_text} khác giá tham chiếu {p["price"]:,} ₫ (cần reviewer xác nhận ngữ cảnh).',
                         source='rule',confidence=e.score,meta={'canonical_index':n})
        if not any(e.kind in ('ocr','asr','vlm_observation','vlm_issue') for e in normalized):
            flag('EVIDENCE-LOW','medium',0,'Chưa có bằng chứng nội dung từ OCR/ASR/VLM; cần reviewer kiểm tra.')
        decision='Regenerate' if any(f['severity']=='high' for f in findings) else 'Needs Review'
        details={'duration':round(duration,2),'fps':round(fps,2),'sampled_frames':processed,
                 'coverage':coverage,'elapsed_seconds':round(time.monotonic()-t0,2),
                 'rule_version':'rules-0.2','normalization_version':'evidence-2.0',
                 'frame_timeline':[{'at':f['at'],'frame':f['frame'],'blur':f['blur']} for f in sampled],
                 'normalization':{'raw_count':len(raw),'canonical_count':len(normalized),
                                  'merged_count':len(raw)-len(normalized)},
                 'visual':{'pairs_checked':len(signals),'scene_cuts':sum(x.scene_cut for x in signals),
                           'same_shot_pairs':sum(x.likely_same_shot for x in signals),
                           'change_candidates':len(candidates)},
                 'vlm':{'enabled':vlm_enabled(),'model':os.environ.get('VLM_MODEL','qwen3-vl:4b-instruct'),
                        'calls_succeeded':vlm_calls,'errors':vlm_errors[:12],
                        'prompt_version':PROMPT_VERSION},
                 'limitations':'VLM findings chỉ là giả thuyết cần xác nhận; không có ảnh SKU tham chiếu, không chứng minh deepfake/AI artifact. Confidence VLM chưa hiệu chuẩn.'}
        with db() as c:
            ids=[]
            for e in normalized:
                cur=c.execute("""INSERT INTO evidence(job_id,kind,timestamp,end_timestamp,content,score,frame,frame2,source_model,fingerprint,metadata)
                                 VALUES(?,?,?,?,?,?,?,?,?,?,?)""",(job_id,*e.to_db()))
                ids.append(cur.lastrowid)
            for f in findings:
                idx=f['metadata'].get('canonical_index')
                if idx is None and f['uid'] is not None: idx=raw_map.get(f['uid'])
                eid=ids[idx] if idx is not None and 0<=idx<len(ids) else None
                refs=[eid] if eid else []
                c.execute("""INSERT INTO findings(job_id,code,severity,timestamp,detail,evidence_id,source,confidence,evidence_refs,metadata)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (job_id,f['code'],f['severity'],f['at'],f['detail'],eid,f['source'],f['confidence'],
                           json.dumps(refs),json.dumps(f['metadata'],ensure_ascii=False)))
            c.execute('UPDATE jobs SET status=?,decision=?,finished_at=?,details=? WHERE id=?',
                      ('completed',decision,utc(),json.dumps(details,ensure_ascii=False),job_id))
            audit(c,job_id,'system','analysis_completed',{'decision':decision,'coverage':coverage,
                  'finding_count':len(findings),'canonical_evidence_count':len(normalized),
                  'vlm_calls_succeeded':vlm_calls})
    except Exception as exc:
        with db() as c:
            c.execute('UPDATE jobs SET status=?,details=?,finished_at=? WHERE id=?',
                      ('failed',json.dumps({'error':str(exc)},ensure_ascii=False),utc(),job_id))
            audit(c,job_id,'system','analysis_failed',{'error':str(exc)[:500]})
    finally:
        if cap is not None:cap.release()

@app.post('/api/jobs')
async def upload_video(file:UploadFile=File(...),product_id:str=Form(...),source_url:str=Form(''),rights:str=Form('unknown')):
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=?',(product_id,)).fetchone():raise HTTPException(404,'Product not found')
    ext=Path(file.filename or '').suffix.lower()
    if ext not in ('.mp4','.mov','.mkv','.webm'):raise HTTPException(400,'Chỉ nhận MP4/MOV/MKV/WEBM')
    jid=uuid.uuid4().hex[:12];stored=f'{jid}{ext}';target=UPLOAD/stored
    size=0
    with target.open('wb') as out:
        while chunk:=await file.read(1024*1024):
            size+=len(chunk)
            if size>MAX_UPLOAD:
                out.close();target.unlink(missing_ok=True);raise HTTPException(413,'Video vượt giới hạn upload')
            out.write(chunk)
    if not size:target.unlink(missing_ok=True);raise HTTPException(400,'Video rỗng')
    with db() as c:
        c.execute('INSERT INTO jobs(id,filename,stored_name,product_id,status,source_url,rights,created_at,details) VALUES(?,?,?,?,?,?,?,?,?)',(jid,Path(file.filename).name,stored,product_id,'queued',source_url[:500],rights[:100],utc(),'{}'))
        audit(c,jid,'system','uploaded',{'size_bytes':size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'source_url':source_url,'rights':rights})
    threading.Thread(target=analyze,args=(jid,),daemon=True).start()
    return {'id':jid,'status':'queued'}

@app.post('/api/jobs/{jid}/reanalyze')
def reanalyze(jid: str):
    """Re-run existing uploaded video with current model settings; keep historical audits."""
    with db() as c:
        j=c.execute('SELECT status,stored_name FROM jobs WHERE id=?',(jid,)).fetchone()
        if not j: raise HTTPException(404,'Job not found')
        if j['status'] in ('queued','processing'): raise HTTPException(409,'Job is already running')
        if not (UPLOAD/j['stored_name']).is_file(): raise HTTPException(404,'Uploaded video missing')
        c.execute('UPDATE jobs SET status=?,review_decision=NULL,reviewer=NULL,review_note=NULL WHERE id=?',('queued',jid))
        audit(c,jid,'system','reanalyze_requested',{'previous_status':j['status'],
              'previous_review_cleared':True,'vlm_enabled':vlm_enabled()})
    threading.Thread(target=analyze,args=(jid,),daemon=True).start()
    return {'id':jid,'status':'queued'}

@app.get('/api/jobs')
def list_jobs():
    with db() as c:return [dict(r) for r in c.execute('SELECT j.id,j.filename,j.status,j.decision,j.review_decision,j.created_at,p.sku,p.name AS product_name FROM jobs j JOIN products p ON j.product_id=p.id ORDER BY j.created_at DESC')]
@app.get('/api/jobs/{jid}')
def get_job(jid:str):
    with db() as c:
        j=c.execute('SELECT * FROM jobs WHERE id=?',(jid,)).fetchone()
        if not j:raise HTTPException(404,'Job not found')
        d=dict(j);d['details']=json.loads(d['details']);d['product']=product_dict(c.execute('SELECT * FROM products WHERE id=?',(d['product_id'],)).fetchone())
        d['evidence']=[dict(r) for r in c.execute('SELECT * FROM evidence WHERE job_id=? ORDER BY timestamp',(jid,))]
        for e in d['evidence']:
            e['metadata']=json.loads(e.get('metadata') or '{}')
            e['end_timestamp']=e.get('end_timestamp') if e.get('end_timestamp') is not None else e['timestamp']
        d['findings']=[dict(r) for r in c.execute('SELECT * FROM findings WHERE job_id=? ORDER BY timestamp',(jid,))]
        for f in d['findings']:
            f['metadata']=json.loads(f.get('metadata') or '{}')
            f['evidence_refs']=json.loads(f.get('evidence_refs') or '[]')
        d['audits']=[dict(r) for r in c.execute('SELECT * FROM audits WHERE job_id=? ORDER BY id DESC',(jid,))]
        d['labels']=[dict(r) for r in c.execute('SELECT * FROM labels WHERE job_id=? ORDER BY id DESC',(jid,))]
        return d
@app.get('/api/jobs/{jid}/evidence/export')
def export_evidence(jid: str):
    from fastapi.responses import JSONResponse
    result = get_job(jid)
    payload = {'schema_version':'verifai-evidence-2.0','job_id':jid,
               'product':result['product'],'details':result['details'],
               'evidence':result['evidence'],'findings':result['findings'],
               'exported_at':utc()}
    return JSONResponse(payload,headers={'Content-Disposition':f'attachment; filename="verifai-evidence-{jid}.json"'})

@app.get('/api/jobs/{jid}/video')
def get_video(jid:str):
    with db() as c:j=c.execute('SELECT stored_name FROM jobs WHERE id=?',(jid,)).fetchone()
    if not j:raise HTTPException(404,'Not found')
    return FileResponse(UPLOAD/j['stored_name'],media_type='video/mp4')
@app.get('/api/jobs/{jid}/frames/{name}')
def get_frame(jid:str,name:str):
    if not re.fullmatch(r'[0-9a-f]{12}',jid) or not re.fullmatch(r'\d{3}\.jpg',name):raise HTTPException(400,'Invalid frame')
    p=FRAMES/jid/name
    if not p.is_file():raise HTTPException(404,'Frame missing')
    return FileResponse(p,media_type='image/jpeg')
class ReviewIn(BaseModel):
    decision:str
    reviewer:str=Field(min_length=1,max_length=100)
    note:str=Field(default='',max_length=2000)
@app.post('/api/jobs/{jid}/review')
def review(jid:str,v:ReviewIn):
    if v.decision not in ('Pass','Needs Review','Regenerate'):raise HTTPException(400,'Invalid decision')
    with db() as c:
        j=c.execute('SELECT status FROM jobs WHERE id=?',(jid,)).fetchone()
        if not j or j['status']!='completed':raise HTTPException(400,'Job not ready')
        c.execute('UPDATE jobs SET review_decision=?,reviewer=?,review_note=? WHERE id=?',(v.decision,v.reviewer.strip(),v.note,jid))
        audit(c,jid,v.reviewer,'review_decision',{'decision':v.decision,'note':v.note})
    return {'ok':True}
class FlagIn(BaseModel):
    state:str
    reviewer:str
@app.patch('/api/jobs/{jid}/findings/{fid}')
def set_flag(jid:str,fid:int,v:FlagIn):
    if v.state not in ('confirmed','rejected','unreviewed'):raise HTTPException(400,'Invalid state')
    with db() as c:
        cur=c.execute('UPDATE findings SET flag_review=? WHERE id=? AND job_id=?',(v.state,fid,jid))
        if cur.rowcount<1:raise HTTPException(404,'Finding not found')
        audit(c,jid,v.reviewer,'flag_review',{'finding_id':fid,'state':v.state})
    return {'ok':True}
class LabelIn(BaseModel):
    annotator:str=Field(min_length=1,max_length=100)
    label:str
    notes:str=''
@app.post('/api/jobs/{jid}/labels')
def label_job(jid:str,v:LabelIn):
    if v.label not in ('clean','error','uncertain'):raise HTTPException(400,'Invalid label')
    with db() as c:
        if not c.execute('SELECT 1 FROM jobs WHERE id=?',(jid,)).fetchone():raise HTTPException(404,'Job not found')
        c.execute('INSERT INTO labels(job_id,annotator,label,notes,created_at) VALUES(?,?,?,?,?)',(jid,v.annotator,v.label,v.notes,utc()))
        audit(c,jid,v.annotator,'ground_truth_label',{'label':v.label,'notes':v.notes})
    return {'ok':True}
@app.get('/api/metrics')
def metrics():
    with db() as c:
        jobs=[dict(r) for r in c.execute('SELECT id,status,decision,review_decision,details FROM jobs')]
        total=len(jobs);done=sum(j['status']=='completed' for j in jobs);rev=sum(bool(j['review_decision']) for j in jobs)
        samples=[]
        for j in jobs:
            labels=[r['label'] for r in c.execute('SELECT label FROM labels WHERE job_id=?',(j['id'],))]
            if j['status']=='completed' and labels and len(set(labels))==1 and labels[0] in ('clean','error'):
                # prediction positive if AI has high-severity content finding; exclude coverage warnings
                pred=bool(c.execute("SELECT 1 FROM findings WHERE job_id=? AND severity='high' AND code!='COVERAGE'",(j['id'],)).fetchone())
                samples.append((labels[0]=='error',pred))
        tp=sum(g and p for g,p in samples);fp=sum(not g and p for g,p in samples);fn=sum(g and not p for g,p in samples)
        vlm_jobs=0;vlm_flagged_jobs=0;visual_candidate_jobs=0;canonical_evidence=0;raw_evidence=0
        for j in jobs:
            if j['status']!='completed':continue
            detail=json.loads(j['details'] or '{}')
            if detail.get('coverage',{}).get('vlm') in ('ok','partial'):vlm_jobs+=1
            if c.execute("SELECT 1 FROM findings WHERE job_id=? AND source='vlm'",(j['id'],)).fetchone():vlm_flagged_jobs+=1
            if detail.get('visual',{}).get('change_candidates',0)>0:visual_candidate_jobs+=1
            norm=detail.get('normalization',{})
            canonical_evidence+=norm.get('canonical_count',0)
            raw_evidence+=norm.get('raw_count',0)
        return {'total':total,'completed':done,'reviewed':rev,'evaluated':len(samples),
                'precision':round(tp/(tp+fp),3) if tp+fp else None,
                'recall':round(tp/(tp+fn),3) if tp+fn else None,
                'tp':tp,'fp':fp,'fn':fn,
                'vlm_jobs':vlm_jobs,'vlm_flagged_jobs':vlm_flagged_jobs,
                'visual_candidate_jobs':visual_candidate_jobs,
                'canonical_evidence':canonical_evidence,'raw_evidence':raw_evidence,
                'note':'Precision/Recall chỉ tính high-severity rule flags với nhãn video-level; VLM medium candidates KHÔNG nằm trong các chỉ số này. Chưa có benchmark VLM theo loại lỗi.'}
