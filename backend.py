"""VerifAI feasibility MVP. Local-only, modular evidence-first analysis."""
import json, os, re, sqlite3, threading, time, uuid, hashlib, subprocess, shutil
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager, asynccontextmanager
from typing import Optional
from urllib.parse import urlparse
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator
from verifai_core.dataset import ensure_dataset_schema, install_dataset_routes
from verifai_core.perception import OCRService, ASRService, ocr_installed, asr_installed
from verifai_core.evidence import RawEvidence, normalize_evidence
from verifai_core.price import assess_price, PRICE_PARSER_VERSION
from verifai_core.claims import CLAIM_RULE_VERSION, find_restricted_claims, validate_reference_claims
from verifai_core.verification import build_verification_report, attach_evidence_ids, VERIFICATION_VERSION
from verifai_core.visual import visual_pairs, evenly_spaced, select_pairs
from verifai_core.vlm import VLMError, vlm_enabled, PROMPT_VERSION
from verifai_core.gemini import GeminiVLM, DEFAULT_MODEL
from verifai_core.evaluation import predicted_error, sufficient_coverage, independent_consensus, calculate_metrics

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('VERIFAI_DATA', str(BASE/'data'))).resolve()
UPLOAD = DATA/'uploads'; FRAMES=DATA/'frames'; DB=DATA/'verifai.sqlite3'
MAX_UPLOAD=int(os.environ.get('MAX_VIDEO_MB','150'))*1024*1024
MAX_DURATION=int(os.environ.get('MAX_VIDEO_SECONDS','180'))
OCR_MAX_FRAMES=max(0,min(60,int(os.environ.get('OCR_MAX_FRAMES','12'))))
_ANALYSIS_SLOTS=threading.BoundedSemaphore(max(1,min(2,int(os.environ.get('MAX_CONCURRENT_JOBS','1')))))
for p in (DATA,UPLOAD,FRAMES): p.mkdir(parents=True,exist_ok=True)
@asynccontextmanager
async def app_lifespan(_app):
    recover_interrupted_jobs()
    yield

app=FastAPI(title='VerifAI MVP API',version='2.1.0',lifespan=app_lifespan)
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
        c.executescript('''CREATE TABLE IF NOT EXISTS product_truth_meta(
            product_id TEXT PRIMARY KEY,
            reference_url TEXT NOT NULL DEFAULT '',
            reference_note TEXT NOT NULL DEFAULT '',
            reference_status TEXT NOT NULL DEFAULT 'unverified',
            revision INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS product_truth_audits(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id TEXT NOT NULL,
            event TEXT NOT NULL,
            revision INTEGER NOT NULL,
            snapshot TEXT NOT NULL,
            created_at TEXT NOT NULL);''')
        # Non-destructive migration: old v1 databases retain all jobs/reviews/labels.
        migrations = {
            'jobs': {'recovery_attempts':'INTEGER NOT NULL DEFAULT 0'},
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
    ensure_dataset_schema(db)
init()

def audit(c,jid,actor,action,payload):c.execute('INSERT INTO audits(job_id,actor,action,payload,created_at) VALUES(?,?,?,?,?)',(jid,actor,action,json.dumps(payload,ensure_ascii=False),utc()))

def rowdict(r):return dict(r) if r else None

def product_dict(r):
    d=rowdict(r)
    if d:
        d['claims']=json.loads(d['claims']);d['banned']=json.loads(d['banned'])
        with db() as c:
            meta=c.execute('SELECT * FROM product_truth_meta WHERE product_id=?',(d['id'],)).fetchone()
        d.update(dict(meta) if meta else {
            'reference_url':'','reference_note':'','reference_status':'unverified',
            'revision':1,'updated_at':d['created_at']})
        d.pop('product_id',None)
    return d

class ProductIn(BaseModel):
    sku:str=Field(min_length=1,max_length=80)
    name:str=Field(min_length=1,max_length=180)
    brand:str=Field(default='',max_length=100)
    price:Optional[int]=Field(default=None,ge=0)
    claims:list[str]=Field(default_factory=list)
    banned:list[str]=Field(default_factory=list)
    reference_url:str=Field(default='',max_length=500)
    reference_note:str=Field(default='',max_length=800)
    reference_status:str=Field(default='unverified')

    @model_validator(mode='after')
    def validate_product_truth(self):
        self.sku=self.sku.strip()
        self.name=self.name.strip()
        self.brand=self.brand.strip()
        self.reference_url=self.reference_url.strip()
        self.reference_note=self.reference_note.strip()
        if not self.sku or not self.name:
            raise ValueError('SKU và tên sản phẩm không được để trống')
        if self.reference_status not in ('unverified','reviewed'):
            raise ValueError('reference_status phải là unverified hoặc reviewed')
        if self.reference_url:
            u=urlparse(self.reference_url)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:
                raise ValueError('reference_url phải là URL http(s) hợp lệ không chứa credentials')
        if self.reference_status=='reviewed' and not (self.reference_url or self.reference_note):
            raise ValueError('Cần nguồn tham chiếu hoặc ghi chú kiểm tra trước khi đánh dấu đã xem xét')
        self.claims,self.banned=validate_reference_claims(self.claims,self.banned)
        return self

class ProductUpdateIn(ProductIn):
    expected_revision:int=Field(ge=1)

def _assert_sku_available(conn, sku, skip_id=None):
    for existing in conn.execute('SELECT id,sku FROM products'):
        if existing['id']!=skip_id and existing['sku'].casefold()==sku.casefold():
            raise HTTPException(409,'SKU đã tồn tại; hãy chỉnh sửa sản phẩm hiện có')

def _product_snapshot(v):
    return {key:getattr(v,key) for key in ('sku','name','brand','price','claims','banned',
            'reference_url','reference_note','reference_status')}

@app.get('/')
def home():return FileResponse(BASE/'static'/'index.html')
@app.get('/api/health')
def health():
    enabled = vlm_enabled()
    status = {'ready': False, 'message': 'VLM_ENABLED=0'}
    if enabled:
        try: status = GeminiVLM().check()
        except VLMError as exc: status = {'ready': False, 'message': str(exc)}
    return {'ok':True,'ocr':_has_paddle(),'asr':_has_whisper(),
            'ffmpeg':bool(shutil.which('ffmpeg')),'database':'sqlite',
            'mode':'local feasibility MVP', 'version':'2.1.0',
            'vlm':{'enabled':enabled,'model':os.environ.get('VLM_MODEL',DEFAULT_MODEL),**status}}
@app.post('/api/products')
def create_product(v:ProductIn):
    pid=uuid.uuid4().hex[:12];now=utc()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        _assert_sku_available(c,v.sku)
        c.execute('''INSERT INTO products(id,sku,name,brand,price,claims,banned,created_at)
                     VALUES(?,?,?,?,?,?,?,?)''',
                  (pid,v.sku,v.name,v.brand,v.price,json.dumps(v.claims,ensure_ascii=False),
                   json.dumps(v.banned,ensure_ascii=False),now))
        c.execute('''INSERT INTO product_truth_meta(product_id,reference_url,reference_note,reference_status,revision,updated_at)
                     VALUES(?,?,?,?,?,?)''',
                  (pid,v.reference_url,v.reference_note,v.reference_status,1,now))
        c.execute('''INSERT INTO product_truth_audits(product_id,event,revision,snapshot,created_at)
                     VALUES(?,?,?,?,?)''',
                  (pid,'created',1,json.dumps(_product_snapshot(v),ensure_ascii=False),now))
    return {'id':pid,'revision':1}

@app.get('/api/products')
def products():
    with db() as c:
        rows=c.execute('SELECT * FROM products ORDER BY created_at DESC').fetchall()
    return [product_dict(r) for r in rows]

@app.get('/api/products/{pid}')
def get_product(pid:str):
    with db() as c:r=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
    if not r:raise HTTPException(404,'Product not found')
    return product_dict(r)

@app.put('/api/products/{pid}')
def update_product(pid:str,v:ProductUpdateIn):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=c.execute('SELECT id FROM products WHERE id=?',(pid,)).fetchone()
        if not existing:raise HTTPException(404,'Product not found')
        meta=c.execute('SELECT revision FROM product_truth_meta WHERE product_id=?',(pid,)).fetchone()
        revision=int(meta['revision']) if meta else 1
        if v.expected_revision!=revision:
            raise HTTPException(409,'Product Truth đã được cập nhật; tải lại trước khi lưu')
        _assert_sku_available(c,v.sku,pid)
        new_revision=revision+1;now=utc()
        c.execute('''UPDATE products SET sku=?,name=?,brand=?,price=?,claims=?,banned=? WHERE id=?''',
                  (v.sku,v.name,v.brand,v.price,json.dumps(v.claims,ensure_ascii=False),
                   json.dumps(v.banned,ensure_ascii=False),pid))
        c.execute('''INSERT INTO product_truth_meta(product_id,reference_url,reference_note,reference_status,revision,updated_at)
                     VALUES(?,?,?,?,?,?) ON CONFLICT(product_id) DO UPDATE SET
                     reference_url=excluded.reference_url, reference_note=excluded.reference_note,
                     reference_status=excluded.reference_status,revision=excluded.revision,
                     updated_at=excluded.updated_at''',
                  (pid,v.reference_url,v.reference_note,v.reference_status,new_revision,now))
        c.execute('''INSERT INTO product_truth_audits(product_id,event,revision,snapshot,created_at)
                     VALUES(?,?,?,?,?)''',
                  (pid,'updated',new_revision,json.dumps(_product_snapshot(v),ensure_ascii=False),now))
    return {'id':pid,'revision':new_revision}

@app.get('/api/products/{pid}/history')
def product_history(pid:str):
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone():
            raise HTTPException(404,'Product not found')
        return [dict(row) for row in c.execute(
            'SELECT revision,event,snapshot,created_at FROM product_truth_audits WHERE product_id=? ORDER BY revision',
            (pid,))]

# Separate, lazy-loaded OCR and ASR engines. Do not download models at startup.
_ocr_service = OCRService()
_asr_service = ASRService()

def _has_paddle():
    return ocr_installed()

def _has_whisper():
    return asr_installed()

def frame_ocr(frame):
    return _ocr_service.extract(frame)

def transcribe(path):
    return _asr_service.extract(path)

def normalize(t):
    import unicodedata
    t=unicodedata.normalize('NFKC',str(t)).lower()
    return re.sub(r'\s+',' ',t).strip()

def analyze(job_id):
    # A bounded local worker pool prevents multiple videos simultaneously loading
    # expensive inference engines on a single CPU workstation.
    with _ANALYSIS_SLOTS:
        return _analyze_job(job_id)

def _set_progress(job_id, stage, **data):
    details={'progress':{'stage':stage,'updated_at':utc(),**data}}
    with db() as c:
        c.execute('UPDATE jobs SET details=? WHERE id=? AND status=?',
                  (json.dumps(details,ensure_ascii=False),job_id,'processing'))

def _analyze_job(job_id):
    """One local job; only an atomically claimed queued job may run."""
    import cv2
    t0=time.monotonic(); cap=None
    with db() as c:
        j=c.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone()
        if not j: return
        p=product_dict(c.execute('SELECT * FROM products WHERE id=?',(j['product_id'],)).fetchone())
        if not p: return
        # Claim exactly once. Duplicate startup/retry threads cannot run together.
        claim=c.execute('UPDATE jobs SET status=?,decision=NULL,finished_at=NULL WHERE id=? AND status=?',
                        ('processing',job_id,'queued'))
        if claim.rowcount!=1:return
        c.execute('DELETE FROM findings WHERE job_id=?',(job_id,))
        c.execute('DELETE FROM evidence WHERE job_id=?',(job_id,))
    path=UPLOAD/j['stored_name']
    coverage={'ocr':'not_installed','asr':'not_installed','visual':'heuristic_screening',
              'c2pa':'not_implemented','vlm':'disabled' if not vlm_enabled() else 'pending'}
    raw=[]; findings=[]; sampled=[]; vlm_calls=0; vlm_errors=[]
    timings={}; ocr_calls=0

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
        _set_progress(job_id,'sampling',sampled_frames=0)
        stage_start=time.monotonic()
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
                processed+=1
            idx+=1
        cap.release();cap=None
        timings['sampling_seconds']=round(time.monotonic()-stage_start,3)
        # Video frame sampling and OCR frame selection have different purposes:
        # visual signals may need up to 60 frames, but OCR only needs a smaller
        # representative subset (default 12) to keep CPU latency bounded.
        chosen=evenly_spaced(sampled,min(OCR_MAX_FRAMES,len(sampled))) if os.getenv('OCR_ENABLED','1') == '1' else []
        _set_progress(job_id,'ocr',done=0,total=len(chosen))
        stage_start=time.monotonic()
        if not chosen: coverage['ocr']='disabled' if os.getenv('OCR_ENABLED','1') != '1' else 'skipped'
        for n,frame in enumerate(chosen,1):
            ocr,ocr_status=frame_ocr(frame['image'])
            if ocr_status=='ok' or coverage['ocr']!='ok':coverage['ocr']=ocr_status
            for text,score in ocr:
                evidence('ocr',frame['at'],text,score,frame['frame'],source='paddleocr',meta={'confidence_kind':'ocr_engine'})
            ocr_calls+=1
            if n==len(chosen) or n%2==0:
                _set_progress(job_id,'ocr',done=n,total=len(chosen))
        timings['ocr_seconds']=round(time.monotonic()-stage_start,3)
        timings['ocr_frames']=ocr_calls
        timings['ocr_avg_seconds_per_frame']=round(timings['ocr_seconds']/ocr_calls,3) if ocr_calls else None
        _set_progress(job_id,'asr')
        stage_start=time.monotonic()
        speeches,coverage['asr']=transcribe(path) if os.getenv('ASR_ENABLED','1') == '1' else ([], 'disabled')
        timings['asr_seconds']=round(time.monotonic()-stage_start,3)
        for seg in speeches:
            evidence('asr',seg['at'],seg['text'],seg.get('score'),source='faster-whisper',
                     meta={'confidence_kind':'not_provided'})

        _set_progress(job_id,'visual')
        stage_start=time.monotonic()
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

        timings['visual_seconds']=round(time.monotonic()-stage_start,3)
        _set_progress(job_id,'vlm')
        stage_start=time.monotonic()
        if vlm_enabled():
            try:
                client=GeminiVLM()
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

        timings['vlm_seconds']=round(time.monotonic()-stage_start,3)
        _set_progress(job_id,'finalizing')
        normalized,raw_map=normalize_evidence(raw)
        if coverage['ocr']!='ok' and coverage['asr']!='ok':
            flag('COVERAGE','medium',0,'OCR/ASR chưa khả dụng; không thể xác nhận lời nói/chữ trong video.')
        for n,e in enumerate(normalized):
            if e.kind not in ('ocr','asr'): continue
            tx=normalize(e.content)
            claim_mentions=find_restricted_claims(e.content,p['banned'])
            if claim_mentions:
                e.metadata['claim_v3']={'version':CLAIM_RULE_VERSION,
                                        'product_truth_revision':p.get('revision',1),
                                        'reference_status':p.get('reference_status','unverified'),
                                        'mentions':[m.to_dict() for m in claim_mentions]}
            for claim in claim_mentions:
                if claim.state!='asserted':
                    continue
                flag('CLAIM-01','medium',e.timestamp,
                     f'Có cụm claim hạn chế “{claim.phrase}” trong nội dung; '
                     'reviewer cần xác minh ngữ cảnh và nguồn Product Truth.',
                     source='claim_rule_v3',confidence=e.score,
                     meta={'canonical_index':n,'claim_assessment':claim.to_dict(),
                           'claim_rule_version':CLAIM_RULE_VERSION,
                           'product_truth_revision':p.get('revision',1),
                           'reference_status':p.get('reference_status','unverified')})
            price_check = assess_price(e.content, p['price'])
            if price_check.mentions:
                e.metadata['price_v3'] = price_check.to_dict()
            if price_check.status == 'MISMATCH':
                flag('PRICE-01','medium',e.timestamp,
                     f'Giá quan sát {price_check.compared_vnd:,} ₫ khác giá tham chiếu '
                     f'{p["price"]:,} ₫; cần kiểm tra sản phẩm, giá khuyến mãi và bối cảnh.',
                     source='price_rule_v3',confidence=e.score,
                     meta={'canonical_index':n,'price_assessment':price_check.to_dict(),
                           'price_parser_version':PRICE_PARSER_VERSION})
        if not any(e.kind in ('ocr','asr','vlm_observation','vlm_issue') for e in normalized):
            flag('EVIDENCE-LOW','medium',0,'Chưa có bằng chứng nội dung từ OCR/ASR/VLM; cần reviewer kiểm tra.')
        # A3 aggregates the existing A1/A2/VLM evidence without changing the
        # candidate findings or the human's final decision.
        verification=build_verification_report(normalized,findings,coverage,p,raw_map)
        decision='Regenerate' if any(f['severity']=='high' for f in findings) else 'Needs Review'
        timings['total_seconds']=round(time.monotonic()-t0,3)
        details={'verification_version':VERIFICATION_VERSION,
                 'timings':timings,'duration':round(duration,2),'fps':round(fps,2),'sampled_frames':processed,
                 'coverage':coverage,'elapsed_seconds':round(time.monotonic()-t0,2),
                 'rule_version':'rules-0.4','price_parser_version':PRICE_PARSER_VERSION,
                 'claim_rule_version':CLAIM_RULE_VERSION,
                 'product_truth_snapshot':{key:p.get(key) for key in
                     ('sku','name','brand','price','claims','banned','reference_url',
                      'reference_note','reference_status','revision')},'normalization_version':'evidence-2.0',
                 'frame_timeline':[{'at':f['at'],'frame':f['frame'],'blur':f['blur']} for f in sampled],
                 'normalization':{'raw_count':len(raw),'canonical_count':len(normalized),
                                  'merged_count':len(raw)-len(normalized)},
                 'visual':{'pairs_checked':len(signals),'scene_cuts':sum(x.scene_cut for x in signals),
                           'same_shot_pairs':sum(x.likely_same_shot for x in signals),
                           'change_candidates':len(candidates)},
                 'vlm':{'enabled':vlm_enabled(),'model':os.environ.get('VLM_MODEL',DEFAULT_MODEL),
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
            details['verification']=attach_evidence_ids(verification,ids)
            c.execute('UPDATE jobs SET status=?,decision=?,finished_at=?,details=? WHERE id=?',
                      ('completed',decision,utc(),json.dumps(details,ensure_ascii=False),job_id))
            audit(c,job_id,'system','analysis_completed',{'decision':decision,'coverage':coverage,
                  'finding_count':len(findings),'canonical_evidence_count':len(normalized),
                  'vlm_calls_succeeded':vlm_calls,
                  'verification_status':verification['status'],
                  'verification_conflicts':verification['conflict_count']})
    except Exception as exc:
        with db() as c:
            c.execute('UPDATE jobs SET status=?,details=?,finished_at=? WHERE id=?',
                      ('failed',json.dumps({'error':str(exc)},ensure_ascii=False),utc(),job_id))
            audit(c,job_id,'system','analysis_failed',{'error':str(exc)[:500]})
    finally:
        if cap is not None:cap.release()

# A restart ends Python worker threads but does not change SQLite status.
# Recover only on application startup, when the prior single-worker server has
# already exited. Never start duplicate analysis while the server is running.
def _start_job(jid):
    threading.Thread(target=analyze,args=(jid,),name=f'VerifAI-{jid}',daemon=True).start()

def recover_interrupted_jobs():
    resumed=[]
    with db() as c:
        items=c.execute("SELECT id,status,stored_name,recovery_attempts FROM jobs WHERE status IN ('queued','processing')").fetchall()
        for job in items:
            jid=job['id']
            source=(UPLOAD/job['stored_name']).resolve()
            # No recovery for missing / malformed storage paths.
            valid=source.parent==UPLOAD.resolve() and source.is_file()
            attempts=int(job['recovery_attempts'] or 0)
            if not valid or (job['status']=='processing' and attempts>=2):
                message=('Video gốc không còn trên ổ đĩa.' if not valid else
                         'Job bị gián đoạn nhiều lần; vui lòng kiểm tra và phân tích lại thủ công.')
                c.execute('UPDATE jobs SET status=?,details=?,finished_at=? WHERE id=?',
                          ('failed',json.dumps({'error':message},ensure_ascii=False),utc(),jid))
                audit(c,jid,'system','recovery_failed',{'reason':message,'attempts':attempts})
                continue
            if job['status']=='processing':
                attempts+=1
                c.execute('UPDATE jobs SET status=?,recovery_attempts=?,details=? WHERE id=?',
                          ('queued',attempts,json.dumps({'progress':{'stage':'recovered','updated_at':utc()}},ensure_ascii=False),jid))
                audit(c,jid,'system','job_recovered',{'attempt':attempts})
            resumed.append(jid)
    for jid in resumed:
        _start_job(jid)
    return resumed

@app.post('/api/jobs')
async def upload_video(file:UploadFile=File(...),product_id:str=Form(...),source_url:str=Form(''),rights:str=Form('unknown'),case_code:str=Form('')):
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=?',(product_id,)).fetchone():raise HTTPException(404,'Product not found')
    case_code=case_code.strip().upper()
    if case_code:
        with db() as c:
            case=c.execute('SELECT product_id FROM dataset_cases WHERE code=?',(case_code,)).fetchone()
            if not case:raise HTTPException(404,'Dataset case not found')
            if case['product_id'] and case['product_id']!=product_id:
                raise HTTPException(409,'Dataset case liên kết Product Truth khác với sản phẩm đã chọn')
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
        c.execute('INSERT INTO jobs(id,filename,stored_name,product_id,status,source_url,rights,created_at,details,case_code) VALUES(?,?,?,?,?,?,?,?,?,?)',(jid,Path(file.filename).name,stored,product_id,'queued',source_url[:500],rights[:100],utc(),'{}',case_code or None))
        if case_code:
            c.execute('UPDATE dataset_cases SET product_id=COALESCE(product_id,?),updated_at=? WHERE code=?',
                      (product_id,utc(),case_code))
        audit(c,jid,'system','uploaded',{'size_bytes':size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'source_url':source_url,'rights':rights})
    _start_job(jid)
    return {'id':jid,'status':'queued'}

@app.post('/api/jobs/{jid}/reanalyze')
def reanalyze(jid: str):
    """Re-run existing uploaded video with current model settings; keep historical audits."""
    with db() as c:
        j=c.execute('SELECT status,stored_name FROM jobs WHERE id=?',(jid,)).fetchone()
        if not j: raise HTTPException(404,'Job not found')
        if j['status'] in ('queued','processing'): raise HTTPException(409,'Job is already running')
        if not (UPLOAD/j['stored_name']).is_file(): raise HTTPException(404,'Uploaded video missing')
        c.execute('UPDATE jobs SET status=?,review_decision=NULL,reviewer=NULL,review_note=NULL,recovery_attempts=0 WHERE id=?',('queued',jid))
        audit(c,jid,'system','reanalyze_requested',{'previous_status':j['status'],
              'previous_review_cleared':True,'vlm_enabled':vlm_enabled()})
    _start_job(jid)
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
@app.get('/api/jobs/{jid}/verification')
def get_verification(jid: str):
    with db() as c:
        j=c.execute('SELECT status,details FROM jobs WHERE id=?',(jid,)).fetchone()
    if not j:raise HTTPException(404,'Job not found')
    if j['status']!='completed':raise HTTPException(409,'Job not completed')
    details=json.loads(j['details'] or '{}')
    if 'verification' not in details:
        raise HTTPException(404,'Verification not available for this analysis; re-analyze to calculate')
    return details['verification']

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
    """Actual-only candidate metrics; same policy as /api/dataset/summary."""
    with db() as c:
        jobs=[dict(r) for r in c.execute('SELECT id,status,review_decision,details FROM jobs')]
        completed=[j for j in jobs if j['status']=='completed']
        evaluated=[]
        coverage_excluded=0
        for j in completed:
            coverage=json.loads(j['details'] or '{}').get('coverage',{})
            if not sufficient_coverage(coverage):
                coverage_excluded+=1
                continue
            labels=[dict(r) for r in c.execute('SELECT annotator,label FROM labels WHERE job_id=?',(j['id'],))]
            truth=independent_consensus(labels)
            if truth is None:continue
            findings=[dict(r) for r in c.execute('SELECT code,severity FROM findings WHERE job_id=?',(j['id'],))]
            evaluated.append((truth=='error',predicted_error(findings)))
        result=calculate_metrics(evaluated)
        result.update({'total':len(jobs),'completed':len(completed),
                       'reviewed':sum(bool(j['review_decision']) for j in jobs),
                       'excluded_insufficient_coverage':coverage_excluded,
                       'note':'Actual-only candidate detection; requires >=2 agreeing annotators and available OCR/ASR/VLM. Dataset endpoint adds case-link constraints.'})
        return result


# Additive, backwards-compatible Sprint-2 evaluation dataset routes.
install_dataset_routes(app,db,utc)
