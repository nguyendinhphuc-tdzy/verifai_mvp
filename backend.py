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
from verifai_core.envfile import load_env_file
load_env_file(Path(__file__).resolve().parent/'.env')
from verifai_core.dataset import ensure_dataset_schema, install_dataset_routes
from verifai_core.product_import import ensure_product_import_schema, install_product_import_routes
from verifai_core.recommendation import recommend_ai
from verifai_core.local_security import local_only_middleware
from verifai_core.session_export import install_export_routes
from verifai_core.sprint2_rules import check_variant, check_unapproved_high_risk_claims, check_brand_typo, check_unapproved_claims_fuzzy, check_brand_substitution, RULE_VERSION as SPRINT2_RULE_VERSION
from verifai_core.perception import OCRService, ASRService, ocr_installed, asr_installed, has_audio_stream
from verifai_core.video_ocr import iter_all_video_frames
from verifai_core.adaptive_ocr import AdaptiveOCRScanner, AdaptiveOCRConfig, OCREvent, ADAPTIVE_OCR_VERSION
from verifai_core.video_understanding import analyze_native_video
from verifai_core.evidence import RawEvidence, normalize_evidence
from verifai_core.price import assess_price, PRICE_PARSER_VERSION
from verifai_core.claims import CLAIM_RULE_VERSION, find_restricted_claims, validate_reference_claims
from verifai_core.verification import build_verification_report, attach_evidence_ids, VERIFICATION_VERSION
from verifai_core.visual import visual_pairs, evenly_spaced, select_pairs
from verifai_core.media_quality import video_stride, select_ocr_frames, OCRCoverage, SAMPLING_VERSION, count_decodable_frames
from verifai_core.vlm import VLMError, vlm_enabled, PROMPT_VERSION
from verifai_core.gemini import GeminiVLM, DEFAULT_MODEL, GeminiVLM as _ProductionGeminiVLM
from verifai_core.brand import detect_brand_inconsistencies, BRAND_RULE_VERSION
from verifai_core.ai_label import find_ai_disclosure, AI_GENERATED_VALUES, AI_LABEL_RULE_VERSION
from verifai_core.label_suggestion import suggest_label
from verifai_core.vlm_health import GEMINI_OUTAGE_CIRCUIT
from verifai_core.evaluation import predicted_error, sufficient_coverage, independent_consensus, calculate_metrics

BASE = Path(__file__).resolve().parent
DATA = Path(os.environ.get('VERIFAI_DATA', str(BASE/'data'))).resolve()
UPLOAD = DATA/'uploads'; FRAMES=DATA/'frames'; DB=DATA/'verifai.sqlite3'
MAX_UPLOAD=int(os.environ.get('MAX_VIDEO_MB','150'))*1024*1024
MAX_DURATION=int(os.environ.get('MAX_VIDEO_SECONDS','180'))
OCR_MAX_FRAMES=max(0,min(60,int(os.environ.get('OCR_MAX_FRAMES','12'))))
OCR_SAMPLING_MODE=os.environ.get('OCR_SAMPLING_MODE','hybrid').strip().lower()
OCR_SCAN_MODES=('adaptive','all','sampled')
# adaptive (default): check every frame, OCR on a <=0.5 s grid + visual changes,
# bisect text changes, re-read new numeric text at full resolution.
# all: OCR every decoded frame (exhaustive reference, slow). sampled: legacy.
OCR_SCAN_MODE=os.environ.get('OCR_SCAN_MODE','adaptive').strip().lower()

def adaptive_ocr_config():
    return AdaptiveOCRConfig(
        max_gap_seconds=float(os.environ.get('OCR_MAX_GAP_SECONDS','0.5')),
        min_gap_seconds=float(os.environ.get('OCR_MIN_GAP_SECONDS','0.25')),
        change_threshold=float(os.environ.get('OCR_CHANGE_THRESHOLD','12')),
        fullres_recheck=os.environ.get('OCR_FULLRES_RECHECK','1')=='1')
_ANALYSIS_SLOTS=threading.BoundedSemaphore(max(1,min(2,int(os.environ.get('MAX_CONCURRENT_JOBS','1')))))
for p in (DATA,UPLOAD,FRAMES): p.mkdir(parents=True,exist_ok=True)
# Cloud demo hosts have no persistent disk: start from a product-only seed.
_SEED_DB=os.environ.get('VERIFAI_SEED_DB','').strip()
if _SEED_DB and not DB.exists() and Path(_SEED_DB).is_file():
    _seed=sqlite3.connect(DB)
    _seed.executescript(Path(_SEED_DB).read_text(encoding='utf-8'))
    _seed.close()
@asynccontextmanager
async def app_lifespan(_app):
    recover_interrupted_jobs()
    yield

app=FastAPI(title='VerifAI MVP API',version='2.1.0',lifespan=app_lifespan)
app.middleware('http')(local_only_middleware)
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
            'jobs': {'recovery_attempts':'INTEGER NOT NULL DEFAULT 0',
                     'ai_generated':"TEXT NOT NULL DEFAULT 'unknown'"},
            'labels': {'ai_suggested_label':'TEXT','label_source':'TEXT'},
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
    ensure_product_import_schema(db)
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
        with db() as c:
            prof=c.execute('SELECT video_code,variant,expected_video_description,source_class,owner,notes,imported_at FROM product_import_profiles WHERE product_id=?',(d['id'],)).fetchone()
        if prof:
            d.update(dict(prof))
        else:
            d.update({'variant':'','expected_video_description':'','source_class':'',
                      'video_code':'','owner':'','notes':''})
        d['reference_scope']=reference_scope(d['reference_status'])
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
        if self.reference_status not in ('unverified','reviewed','test_reference_approved'):
            raise ValueError('reference_status phải là unverified, reviewed hoặc test_reference_approved')
        if self.reference_url:
            u=urlparse(self.reference_url)
            if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:
                raise ValueError('reference_url phải là URL http(s) hợp lệ không chứa credentials')
        if self.reference_status in ('reviewed','test_reference_approved') and not (self.reference_url or self.reference_note):
            raise ValueError('Cần nguồn tham chiếu hoặc ghi chú kiểm tra trước khi duyệt nguồn/chuẩn kiểm thử')
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

def reference_scope(status: str) -> str:
    """Never conflate benchmark approval with externally verified commerce data."""
    return ('test' if status == 'test_reference_approved'
            else 'commercial' if status == 'reviewed' else 'unverified')


@app.get('/')
def home():return FileResponse(BASE/'static'/'index.html')
@app.get('/healthz')
def healthz():
    return {'ok':True}
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

RIGHTS_VALUES=('unknown','self_created','permission_granted','public_review_only')

def cloud_upload_rights():
    """Declared usage rights that allow sending video/frames to Gemini.

    'unknown' is never eligible: media leaves the machine only after the
    uploader has declared a usage right (PO decision, Sprint 1).
    """
    raw=os.environ.get('VLM_CLOUD_RIGHTS','self_created,permission_granted,public_review_only')
    return {x.strip() for x in raw.split(',') if x.strip() in RIGHTS_VALUES}-{'unknown'}

def _container_frame_count(cap):
    """Frame count advertised by the container; <=0 means unknown."""
    import cv2
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    except (TypeError, ValueError, OverflowError):
        return 0

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
    job_rights=(j['rights'] or 'unknown')
    job_ai_generated=(j['ai_generated'] if 'ai_generated' in j.keys() else None) or 'unknown'
    vlm_rights_ok=job_rights in cloud_upload_rights()
    vlm_active=vlm_enabled() and vlm_rights_ok
    coverage={'ocr':'not_installed','asr':'not_installed','visual':'heuristic_screening',
              'c2pa':'not_implemented','vlm':'disabled' if not vlm_enabled() else 'pending'}
    raw=[]; findings=[]; sampled=[]; vlm_calls=0; vlm_errors=[]
    timings={}; ocr_calls=0; ocr_health=OCRCoverage()

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
        total=_container_frame_count(cap); frame_count_source='container'
        if total<=0:
            # WEBM/MKV often omit frame counts. Without a real duration the
            # length limit and the Gemini timestamp filter would be bypassed.
            total=count_decodable_frames(path,limit=int(fps*MAX_DURATION)+1)
            frame_count_source='decoded'
        if total<=0: raise RuntimeError('Không đọc được frame nào từ video.')
        duration=total/fps
        if duration>MAX_DURATION: raise RuntimeError(f'Video vượt giới hạn {MAX_DURATION} giây.')
        interval=video_stride(fps,duration,max_frames=60)
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
        # Keep B1 hybrid OCR sampling and PR10's CPU-saving opt-out.
        ocr_enabled = os.getenv('OCR_ENABLED','1') == '1'
        if OCR_SCAN_MODE not in OCR_SCAN_MODES:
            raise RuntimeError('OCR_SCAN_MODE phải là '+', '.join(OCR_SCAN_MODES))
        all_frames=ocr_enabled and OCR_SCAN_MODE=='all'
        adaptive=ocr_enabled and OCR_SCAN_MODE=='adaptive'
        scanner=None
        if adaptive:
            # Every decoded frame is checked; OCR only where text may differ.
            scanner=AdaptiveOCRScanner(
                frame_ocr,fps,adaptive_ocr_config(),
                progress=lambda checked,calls:_set_progress(
                    job_id,'ocr',done=checked,total=total,ocr_calls=calls,mode='adaptive'))
            events=scanner.scan(iter_all_video_frames(path,keep_full=scanner.config.fullres_recheck))
            expected_ocr_frames=total
        else:
            chosen=(iter_all_video_frames(path) if all_frames else
                    select_ocr_frames(sampled,min(OCR_MAX_FRAMES,len(sampled)),
                                      mode=OCR_SAMPLING_MODE) if ocr_enabled else [])
            expected_ocr_frames = max(0,total) if all_frames else len(chosen)
            def _plain_events(frames):
                for frame in frames:
                    results,status=frame_ocr(frame['image'])
                    yield OCREvent(frame,results,status,OCR_SCAN_MODE,visible_until=frame['at'])
            events=_plain_events(chosen)
        _set_progress(job_id,'ocr',done=0,total=expected_ocr_frames,mode=OCR_SCAN_MODE)
        stage_start=time.monotonic()
        for n,event in enumerate(events,1):
            frame=event.frame
            ocr_health.observe(event.status,len(event.results))
            if event.status=='ok':
                if (all_frames or adaptive) and event.results:
                    cv2.imwrite(str(frame_dir/frame['frame']),frame['image'],
                                [cv2.IMWRITE_JPEG_QUALITY,80])
                for text,score in event.results:
                    meta={'confidence_kind':'ocr_engine',
                          'scan_mode':OCR_SCAN_MODE,
                          'source_frame_index':frame.get('source_frame_index'),
                          'sampling_version':SAMPLING_VERSION}
                    if adaptive:
                        meta.update({'ocr_reason':event.reason,
                                     'inherited_frames':event.inherited_frames,
                                     'fullres_reread':event.fullres_used,
                                     'adaptive_version':ADAPTIVE_OCR_VERSION})
                        if event.visible_until>frame['at']:
                            meta['segment_end_seconds']=round(event.visible_until,3)
                    evidence('ocr',frame['at'],text,score,frame['frame'],source='paddleocr',meta=meta)
            ocr_calls+=1
            if not adaptive and (n==expected_ocr_frames or (all_frames and n%5==0) or (not all_frames and n%2==0)):
                _set_progress(job_id,'ocr',done=n,total=expected_ocr_frames,mode=OCR_SCAN_MODE)
        if not adaptive:
            _set_progress(job_id,'ocr',done=ocr_calls,total=expected_ocr_frames,mode=OCR_SCAN_MODE)
        ocr_health_data=ocr_health.snapshot()
        ocr_health_data['scan_mode']=OCR_SCAN_MODE
        ocr_health_data['expected_decoded_frames']=total if (all_frames or adaptive) else None
        checked_frames=(scanner.stats.decoded_frames if scanner else ocr_calls if all_frames else 0)
        ocr_health_data['complete_video_scan']=bool(
            (all_frames or adaptive) and (total<=0 or checked_frames>=total)
            and (scanner is None or scanner.stats.snapshot(scanner.config,fps)['all_frames_accounted']))
        if scanner:
            ocr_health_data['adaptive']=scanner.stats.snapshot(scanner.config,fps)
        if (all_frames or adaptive) and total>0 and checked_frames<total:
            ocr_health_data['status']='partial' if ocr_health.successful_frames else 'error'
            ocr_health_data['errors'].append('Decoder stopped before advertised frame count')
        if not ocr_enabled:
            ocr_health_data['status']='disabled'
        coverage['ocr']=ocr_health_data['status']
        timings['ocr_seconds']=round(time.monotonic()-stage_start,3)
        timings['ocr_frames']=ocr_calls
        timings['ocr_checked_frames']=checked_frames or ocr_calls
        if scanner:
            timings['ocr_fullres_calls']=scanner.stats.fullres_calls
        timings['ocr_avg_seconds_per_frame']=round(timings['ocr_seconds']/ocr_calls,3) if ocr_calls else None
        _set_progress(job_id,'asr')
        stage_start=time.monotonic()
        speeches,coverage['asr']=transcribe(path) if os.getenv('ASR_ENABLED','1') == '1' else ([], 'disabled')
        timings['asr_seconds']=round(time.monotonic()-stage_start,3)
        for seg in speeches:
            meta={'confidence_kind':'not_provided'}
            if seg.get('end') is not None:
                meta['segment_end_seconds']=seg['end']
            evidence('asr',seg['at'],seg['text'],seg.get('score'),source='faster-whisper',
                     meta=meta)

        _set_progress(job_id,'visual')
        stage_start=time.monotonic()
        signals=visual_pairs(sampled)
        candidates=[v for v in signals if v.candidate]
        for pair in evenly_spaced(candidates,3):
            uid=evidence('visual_signal',pair.at,
                         f'Biến động frame {pair.at:.1f}s → {pair.at2:.1f}s (chỉ báo heuristic, không chứng minh lỗi AI).',
                         None,pair.frame,pair.frame2,'opencv-temporal-v2',
                         {'pair_signal':pair.to_dict(),'paired_timestamp':pair.at2,'confidence_kind':'not_calibrated'})
            if not vlm_active:
                flag('VIS-SCREEN','low',pair.at,'Biến động hình ảnh cùng cảnh: cần reviewer xem hai frame; chưa có VLM xác nhận.',
                     uid,source='visual_heuristic',meta={'paired_timestamp':pair.at2})
        blurry=[f for f in sampled if f['blur']<24]
        if len(blurry)>=max(2,int(len(sampled)*.55)) and blurry:
            flag('VIS-06','low',blurry[0]['at'],
                 'Nhiều frame có độ nét thấp (heuristic), không đồng nghĩa lỗi tạo sinh.',source='visual_heuristic')

        timings['visual_seconds']=round(time.monotonic()-stage_start,3)
        _set_progress(job_id,'vlm')
        stage_start=time.monotonic()
        if vlm_enabled() and not vlm_rights_ok:
            # Fail closed: incomplete VLM coverage keeps the AI suggestion at Review.
            coverage['vlm']='skipped_rights'
            vlm_errors.append(f'Không gửi video/frame lên Gemini: quyền sử dụng video là '
                              f'"{job_rights}". Khai báo quyền rồi phân tích lại để dùng VLM.')
        elif vlm_enabled():
            try:
                client=GeminiVLM()
                readiness=client.check()
                if not readiness['ready']: raise VLMError(readiness['message'])
                # Circuit only applies to the actual cloud adapter, not
                # offline test mocks or other potential VLM backends.
                circuit_enabled=(isinstance(client,_ProductionGeminiVLM)
                                 and os.getenv('VLM_CIRCUIT_ENABLED','1') == '1')
                if circuit_enabled and not GEMINI_OUTAGE_CIRCUIT.allow():
                    remaining=round(GEMINI_OUTAGE_CIRCUIT.remaining_seconds())
                    raise VLMError(
                        f'Gemini API tạm thời không sẵn sàng (503/504); '
                        f'tạm bỏ qua VLM ~{remaining}s để OCR/ASR tiếp tục.')
                input_mode=os.environ.get('VLM_INPUT_MODE','video').strip().lower()
                if input_mode not in ('video','frames'):
                    raise VLMError('VLM_INPUT_MODE phải là video hoặc frames')
                # Preserve offline test adapters with image-only mocked Gemini.
                video_mode=(input_mode=='video' and
                            isinstance(client,_ProductionGeminiVLM) and
                            callable(getattr(client,'_get_client',None)))
                native_video_summary=''
                native_timeline_summary=''
                attempted_calls=0;skipped_calls=0;failed_calls=0
                native_request_started=False
                frame_limit=max(0,min(8,int(os.environ.get('VLM_MAX_FRAMES','1'))))
                pair_limit=max(0,min(6,int(os.environ.get('VLM_MAX_PAIRS','0'))))
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
                if video_mode:
                    _set_progress(job_id,'vlm',current='native full video',done=0,total=1)
                    attempted_calls=1
                    native_request_started=True
                    result=analyze_native_video(client,path,p)
                    vlm_calls+=1
                    if circuit_enabled:
                        GEMINI_OUTAGE_CIRCUIT.success()
                    native_video_summary=result.summary
                    native_timeline_summary=result.timeline_summary
                    for obs in result.observations:
                        if obs.timestamp_seconds>duration+1:
                            continue
                        evidence('vlm_video_observation',obs.timestamp_seconds,
                                 obs.description,obs.confidence,source=client.model,
                                 meta={'category':obs.category,'task':'video',
                                       'timestamp_source':'model_reported',
                                       'confidence_kind':'model_self_reported',
                                       'prompt_version':'gemini-native-video-v1'})
                    for issue in result.issues:
                        if issue.timestamp_seconds>duration+1:
                            continue
                        uid=evidence('vlm_issue',issue.timestamp_seconds,
                                     issue.visible_basis+' — '+issue.description,
                                     issue.confidence,source=client.model,
                                     meta={'code':issue.code,'task':'video',
                                           'timestamp_source':'model_reported',
                                           'visible_basis':issue.visible_basis,
                                           'confidence_kind':'model_self_reported'})
                        if issue.confidence>=0.70:
                            flag(issue.code,'medium',issue.timestamp_seconds,
                                 issue.description,uid,'vlm',issue.confidence,
                                 {'task':'video','timestamp_source':'model_reported'})
                    _set_progress(job_id,'vlm',done=1,total=1,current='native full video')
                requests=([('single',[f],f'frame {f["at"]}') for f in frame_selection]
                          if not video_mode else [])
                lookup={f['frame']:f for f in sampled}
                if not video_mode:
                    for pair in pair_selection:
                        try:
                            f1,f2=lookup[pair.frame],lookup[pair.frame2]
                            requests.append(('pair',[f1,f2],f'pair {pair.at}-{pair.at2}'))
                        except KeyError:
                            vlm_errors.append(f'pair {pair.at}-{pair.at2}: missing sampled frame')
                # Soft budget only prevents scheduling subsequent SDK calls.
                budget=max(15,min(600,int(os.environ.get('VLM_TOTAL_BUDGET_SECONDS','120'))))
                stop_failures=max(1,min(6,int(os.environ.get('VLM_STOP_AFTER_FAILURES','2'))))
                for n,(task,frames,label) in enumerate(requests,1):
                    elapsed=time.monotonic()-stage_start
                    if elapsed>=budget or failed_calls>=stop_failures:
                        skipped_calls=len(requests)-n+1
                        vlm_errors.append('Bỏ qua các request VLM còn lại: vượt soft budget hoặc lỗi API liên tiếp.')
                        break
                    _set_progress(job_id,'vlm',done=n-1,total=len(requests),
                                  current=label,failures=failed_calls,
                                  elapsed_seconds=round(elapsed,1))
                    attempted_calls+=1
                    try:
                        result=client.analyze([frame_dir/f['frame'] for f in frames],p,task)
                        vlm_calls+=1;failed_calls=0
                        if circuit_enabled:
                            GEMINI_OUTAGE_CIRCUIT.success()
                        collect(result,frames,task)
                    except (VLMError, OSError, ValueError, IndexError) as exc:
                        failed_calls+=1
                        vlm_errors.append(f'{label}: {str(exc)[:160]}')
                        if circuit_enabled:
                            opened=GEMINI_OUTAGE_CIRCUIT.failure(
                                str(exc),
                                threshold=int(os.getenv('VLM_CIRCUIT_FAILURES','2')),
                                cooldown_seconds=int(os.getenv('VLM_CIRCUIT_COOLDOWN_SECONDS','180')))
                            if opened:
                                failed_calls=stop_failures
                                vlm_errors.append(
                                    'Gemini outage circuit opened: skipping subsequent VLM calls; '
                                    'OCR/ASR continue and reviewer decides.')
                    _set_progress(job_id,'vlm',done=n,total=len(requests),
                                  current=label,failures=failed_calls,
                                  elapsed_seconds=round(time.monotonic()-stage_start,1))
                coverage['vlm']='ok' if vlm_calls and not vlm_errors else 'partial' if vlm_calls else 'error'
            except (VLMError, ValueError) as exc:
                coverage['vlm']='error';vlm_errors.append(str(exc)[:180])
                # Native-video exceptions bypass the legacy per-frame
                # exception handler. Count transient API failures here so
                # later jobs can be skipped while OCR/ASR still complete.
                # Do not count a circuit-open skip as another failed request.
                if locals().get('native_request_started',False) and circuit_enabled:
                    opened=GEMINI_OUTAGE_CIRCUIT.failure(
                        str(exc),
                        threshold=int(os.getenv('VLM_CIRCUIT_FAILURES','2')),
                        cooldown_seconds=int(os.getenv('VLM_CIRCUIT_COOLDOWN_SECONDS','180')))
                    if opened:
                        vlm_errors.append(
                            'Gemini outage circuit opened: subsequent jobs '
                            'skip VLM; OCR/ASR continue and reviewer decides.')
        else:
            coverage['vlm']='disabled'

        timings['vlm_seconds']=round(time.monotonic()-stage_start,3)
        _set_progress(job_id,'finalizing')
        normalized,raw_map=normalize_evidence(raw)
        for detected in detect_brand_inconsistencies(normalized,p.get('brand','')):
            # Repeated OCR brand transposition is an evidence-linked candidate;
            # unrelated labels are not automatically treated as brand mistakes.
            evidence_index=detected['canonical_index']
            brand_evidence=normalized[evidence_index]
            brand_evidence.metadata['brand_check']={
                **detected, 'reference_status':p.get('reference_status','unverified')}
            flag('SKU-01','high' if brand_evidence.kind=='ocr' else 'medium',brand_evidence.timestamp,
                 f'Thương hiệu trong video “{detected["observed_brand"]}” '
                 f'khác thứ tự tên tham chiếu “{detected["reference_brand"]}”; '
                 'reviewer cần kiểm tra nhãn bao bì, chữ quảng cáo và Product Truth.',
                 source='brand_rule_v1',confidence=brand_evidence.score,
                 meta={**detected,'reference_status':p.get('reference_status','unverified')})
        if job_ai_generated=='yes':
            # Dataset group "Thiếu nhãn AI": a declared AI-generated video must
            # display a disclosure. Absence is only conclusive with full OCR.
            text_items=[e for e in normalized if e.kind in ('ocr','asr')
                        or (e.kind in ('vlm_observation','vlm_video_observation')
                            and e.metadata.get('category')=='visible_text')]
            disclosure=find_ai_disclosure(e.content for e in text_items)
            full_ocr=coverage['ocr']=='ok' and bool(ocr_health_data.get('complete_video_scan'))
            ai_label_meta={'rule_version':AI_LABEL_RULE_VERSION,'declared_ai_generated':True,
                           'disclosure_found':disclosure,'complete_ocr_scan':full_ocr,
                           'texts_checked':len(text_items)}
            if disclosure is None and full_ocr:
                flag('AI-LABEL-01','high',0,
                     'Video được khai báo do AI tạo nhưng không tìm thấy nhãn công bố '
                     '(ví dụ "Nội dung được tạo bởi AI") ở bất kỳ frame nào đã quét OCR '
                     'hay lời nói. Cần bổ sung nhãn rồi xuất lại video.',
                     source='ai_label_rule_v1',confidence=None,
                     meta={**ai_label_meta,'absence_verified':True})
            elif disclosure is None:
                flag('AI-LABEL-01','medium',0,
                     'Chưa tìm thấy nhãn công bố nội dung AI, nhưng OCR chưa quét đủ toàn bộ video; '
                     'reviewer cần kiểm tra thủ công.',
                     source='ai_label_rule_v1',meta={**ai_label_meta,'absence_verified':False})
            details_ai_label={**ai_label_meta,'status':'found' if disclosure else 'missing'}
        else:
            details_ai_label={'rule_version':AI_LABEL_RULE_VERSION,'declared_ai_generated':job_ai_generated,
                              'status':'not_required'}
        if coverage['ocr']!='ok' and coverage['asr']!='ok':
            flag('COVERAGE','medium',0,'OCR/ASR chưa khả dụng; chữ do Gemini đọc chỉ là bằng chứng ứng viên, cần xác minh độc lập.')
        for n,e in enumerate(normalized):
            # Only visual-text observations can enter price/claim reconciliation.
            # Gemini self-reported confidence is NOT an accuracy calibration.
            is_vlm_text=(e.kind in ('vlm_observation','vlm_video_observation')
                         and e.metadata.get('category')=='visible_text'
                         and e.score is not None and e.score>=0.80)
            if e.kind not in ('ocr','asr') and not is_vlm_text: continue
            # Deterministic text read by OCR on >=2 frames at score>=0.90, or
            # heard by ASR, is strong enough to recommend Regenerate. Gemini
            # text never is (it stays a reviewer candidate).
            ocr_frames_seen={str(x.get('frame')) for x in e.metadata.get('sources',[])
                             if isinstance(x,dict) and x.get('frame')} or ({e.frame} if e.frame else set())
            strong=(e.kind=='asr' or (e.kind=='ocr' and e.score is not None and e.score>=0.90
                                      and len(ocr_frames_seen)>=2))
            strong_severity='high' if strong else 'medium'
            claim_mentions=find_restricted_claims(e.content,p['banned'])
            if claim_mentions:
                e.metadata['claim_v3']={'version':CLAIM_RULE_VERSION,
                                        'product_truth_revision':p.get('revision',1),
                                        'reference_status':p.get('reference_status','unverified'),
                                        'mentions':[m.to_dict() for m in claim_mentions]}
            for claim in claim_mentions:
                if claim.state!='asserted':
                    continue
                flag('CLAIM-01',strong_severity,e.timestamp,
                     f'Có cụm claim hạn chế “{claim.phrase}” trong nội dung; '
                     'reviewer cần xác minh ngữ cảnh và nguồn Product Truth.',
                     source='claim_rule_vlm' if is_vlm_text else 'claim_rule_v3',confidence=e.score,
                     meta={'canonical_index':n,'claim_assessment':claim.to_dict(),
                           'claim_rule_version':CLAIM_RULE_VERSION,
                           'product_truth_revision':p.get('revision',1),
                           'reference_status':p.get('reference_status','unverified'),
                           'evidence_origin':'gemini_visible_text' if is_vlm_text else e.kind})
            # Scenarios in Sprint-2 Sheet 2 informed these text candidates.
            # They are not labels or trained weights, and require reviewer signoff.
            for mismatch in (check_variant(e.content, p.get('variant',''))
                             if e.kind!='ocr' or e.score is None or e.score>=0.80
                             else []):
                flag(mismatch.code,'medium',e.timestamp,
                     f'Quy cách/dung tích quan sát "{mismatch.observed}" '
                     f'khác hoặc tự mâu thuẫn với tham chiếu "{mismatch.expected or p.get("variant","")}"; '
                     'cần kiểm tra đúng sản phẩm và ngữ cảnh.',
                     source='variant_rule_v1',confidence=e.score,
                     meta={'canonical_index':n,'reason':mismatch.reason,
                           'reference_variant':p.get('variant',''),
                           'rule_version':SPRINT2_RULE_VERSION,
                           'evidence_origin':'gemini_visible_text' if is_vlm_text else e.kind})
            exact_claims=check_unapproved_high_risk_claims(e.content,p['claims'],p['banned'])
            for claim in exact_claims:
                flag(claim.code,strong_severity,e.timestamp,
                     f'Phát hiện claim có rủi ro chưa nằm trong Approved Claims: "{claim.observed}". '
                     'Không mặc định vi phạm; reviewer cần xác minh nội dung và nguồn.',
                     source='claim_candidate_v1',confidence=e.score,
                     meta={'canonical_index':n,'rule_version':SPRINT2_RULE_VERSION,
                           'evidence_origin':'gemini_visible_text' if is_vlm_text else e.kind})
            if not exact_claims and not claim_mentions:
                # OCR often drops Vietnamese diacritics; match accent-free text.
                for claim in check_unapproved_claims_fuzzy(e.content,p['claims'],p['banned']):
                    curated=claim.reason=='high_risk_phrase_fuzzy'
                    flag(claim.code,strong_severity if curated else 'medium',e.timestamp,
                         f'Claim chưa nằm trong Approved Claims: "{claim.observed}"'
                         +(' (khớp cụm rủi ro cao).' if curated else ' (cách nói tuyệt đối hóa).')
                         +' Reviewer cần xác minh nguồn chứng minh.',
                         source='claim_fuzzy_v1',confidence=e.score,
                         meta={'canonical_index':n,'reason':claim.reason,'rule_version':SPRINT2_RULE_VERSION,
                               'evidence_origin':'gemini_visible_text' if is_vlm_text else e.kind})
            if e.kind=='ocr':
                source_frames={str(x.get('frame')) for x in e.metadata.get('sources',[])
                               if isinstance(x,dict) and x.get('frame')}
                if not source_frames and e.frame:source_frames={e.frame}
                if e.score is not None and e.score>=0.90:
                    for typo in check_brand_typo(e.content,p.get('brand',''),
                                                 supporting_frames=len(source_frames)):
                        flag(typo.code,'medium',e.timestamp,
                             f'Chữ thương hiệu "{typo.observed}" có thể bị lỗi chính tả '
                             f'(tham chiếu: "{typo.expected}"). Cần kiểm tra frame gốc.',
                             source='text_typo_v1',confidence=e.score,
                             meta={'canonical_index':n,'rule_version':SPRINT2_RULE_VERSION,
                                   'supporting_frames':sorted(source_frames)})
                    for sub in check_brand_substitution(e.content,p.get('brand',''),
                                                        supporting_frames=len(source_frames)):
                        flag(sub.code,strong_severity,e.timestamp,
                             f'Video hiển thị thương hiệu "{sub.observed}" thay vì "{sub.expected}" '
                             f'(đọc trên {len(source_frames)} frame). Cần kiểm tra bao bì và Product Truth.',
                             source='brand_substitution_v1',confidence=e.score,
                             meta={'canonical_index':n,'observed_brand':sub.observed,
                                   'reference_brand':sub.expected,'rule_version':SPRINT2_RULE_VERSION,
                                   'supporting_frames':sorted(source_frames)})
            price_check = assess_price(e.content, p['price'])
            if price_check.mentions:
                e.metadata['price_v3'] = price_check.to_dict()
            if price_check.status == 'MISMATCH':
                flag('PRICE-01',strong_severity,e.timestamp,
                     f'Giá quan sát {price_check.compared_vnd:,} ₫ khác giá tham chiếu '
                     f'{p["price"]:,} ₫; cần kiểm tra sản phẩm, giá khuyến mãi và bối cảnh.',
                     source='price_rule_vlm' if is_vlm_text else 'price_rule_v3',confidence=e.score,
                     meta={'canonical_index':n,'price_assessment':price_check.to_dict(),
                           'price_parser_version':PRICE_PARSER_VERSION,
                           'evidence_origin':'gemini_visible_text' if is_vlm_text else e.kind,
                           'reference_status':p.get('reference_status','unverified')})
        if not any(e.kind in ('ocr','asr','vlm_observation','vlm_video_observation','vlm_issue') for e in normalized):
            flag('EVIDENCE-LOW','medium',0,'Chưa có bằng chứng nội dung từ OCR/ASR/VLM; cần reviewer kiểm tra.')
        # A3 aggregates the existing A1/A2/VLM evidence without changing the
        # candidate findings or the human's final decision.
        verification=build_verification_report(normalized,findings,coverage,p,raw_map)
        timings['total_seconds']=round(time.monotonic()-t0,3)
        details={'verification_version':VERIFICATION_VERSION,
                 'timings':timings,'duration':round(duration,2),'fps':round(fps,2),'sampled_frames':processed,
                 'frame_count':total,'frame_count_source':frame_count_source,
                 'coverage':coverage,'elapsed_seconds':round(time.monotonic()-t0,2),
                 'ai_label':details_ai_label,
                 'perception_quality':{
                     'sampling_version':SAMPLING_VERSION,
                     'sampling_stride_frames':interval,
                     'ocr_sampling_mode':OCR_SAMPLING_MODE,
                     'ocr_scan_mode':OCR_SCAN_MODE,
                     'ocr':ocr_health_data,
                     'asr':{'status':coverage['asr'],
                            'segments':len(speeches),
                            'segments_with_end':sum(seg.get('end') is not None for seg in speeches),
                            'speech_observed':bool(speeches),
                            'audio_stream':has_audio_stream(path)},
                 },
                 'rule_version':'rules-0.4','price_parser_version':PRICE_PARSER_VERSION,
                 'claim_rule_version':CLAIM_RULE_VERSION,
                 'product_truth_snapshot':{key:p.get(key) for key in
                     ('sku','name','brand','price','variant','expected_video_description',
                      'claims','banned','reference_url','reference_note','reference_status','revision')},'normalization_version':'evidence-2.0',
                 'frame_timeline':[{'at':f['at'],'frame':f['frame'],'blur':f['blur']} for f in sampled],
                 'normalization':{'raw_count':len(raw),'canonical_count':len(normalized),
                                  'merged_count':len(raw)-len(normalized)},
                 'visual':{'pairs_checked':len(signals),'scene_cuts':sum(x.scene_cut for x in signals),
                           'same_shot_pairs':sum(x.likely_same_shot for x in signals),
                           'change_candidates':len(candidates)},
                 'vlm':{'enabled':vlm_enabled(),'model':os.environ.get('VLM_MODEL',DEFAULT_MODEL),
                         'rights':job_rights,'cloud_upload_allowed':vlm_rights_ok,
                         'input_mode':'video' if locals().get('video_mode',False) else 'frames',
                         'video_summary':locals().get('native_video_summary',''),
                         'timeline_summary':locals().get('native_timeline_summary',''),
                        'calls_succeeded':vlm_calls,
                         'calls_attempted':locals().get('attempted_calls',0),
                         'calls_skipped':locals().get('skipped_calls',0),
                         'soft_budget_seconds':int(os.environ.get('VLM_TOTAL_BUDGET_SECONDS','120')),
                         'outage_circuit_remaining_seconds':round(GEMINI_OUTAGE_CIRCUIT.remaining_seconds())
                             if os.getenv('VLM_CIRCUIT_ENABLED','1') == '1' else 0,
                         'errors':vlm_errors[:12],
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
                f['evidence_id']=eid
                f['evidence_refs']=refs
                c.execute("""INSERT INTO findings(job_id,code,severity,timestamp,detail,evidence_id,source,confidence,evidence_refs,metadata)
                             VALUES(?,?,?,?,?,?,?,?,?,?)""",
                          (job_id,f['code'],f['severity'],f['at'],f['detail'],eid,f['source'],f['confidence'],
                           json.dumps(refs),json.dumps(f['metadata'],ensure_ascii=False)))
            details['verification']=attach_evidence_ids(verification,ids)
            recommendation=recommend_ai(details['verification'],findings)
            details['ai_recommendation']=recommendation
            decision=recommendation['decision']
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
async def upload_video(file:UploadFile=File(...),product_id:str=Form(...),source_url:str=Form(''),rights:str=Form('unknown'),case_code:str=Form(''),ai_generated:str=Form('unknown')):
    with db() as c:
        if not c.execute('SELECT 1 FROM products WHERE id=?',(product_id,)).fetchone():raise HTTPException(404,'Product not found')
    case_code=case_code.strip().upper()
    if case_code:
        with db() as c:
            case=c.execute('SELECT product_id FROM dataset_cases WHERE code=?',(case_code,)).fetchone()
            if not case:raise HTTPException(404,'Dataset case not found')
            if case['product_id'] and case['product_id']!=product_id:
                raise HTTPException(409,'Dataset case liên kết Product Truth khác với sản phẩm đã chọn')
    rights=(rights or '').strip() or 'unknown'
    if rights not in RIGHTS_VALUES:
        raise HTTPException(400,'rights phải là một trong: '+', '.join(RIGHTS_VALUES))
    ai_generated=(ai_generated or '').strip().lower() or 'unknown'
    if ai_generated not in AI_GENERATED_VALUES:
        raise HTTPException(400,'ai_generated phải là một trong: '+', '.join(AI_GENERATED_VALUES))
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
        c.execute('INSERT INTO jobs(id,filename,stored_name,product_id,status,source_url,rights,created_at,details,case_code,ai_generated) VALUES(?,?,?,?,?,?,?,?,?,?,?)',(jid,Path(file.filename).name,stored,product_id,'queued',source_url[:500],rights,utc(),'{}',case_code or None,ai_generated))
        if case_code:
            c.execute('UPDATE dataset_cases SET product_id=COALESCE(product_id,?),updated_at=? WHERE code=?',
                      (product_id,utc(),case_code))
        audit(c,jid,'system','uploaded',{'size_bytes':size,'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'source_url':source_url,'rights':rights,'ai_generated':ai_generated})
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
    with db() as c:
        rows=[dict(r) for r in c.execute(
            'SELECT j.id,j.filename,j.status,j.decision,j.review_decision,j.created_at,'
            'j.details,p.sku,p.name AS product_name '
            'FROM jobs j JOIN products p ON j.product_id=p.id ORDER BY j.created_at DESC')]
        findings_by_job={}
        for r in c.execute(
            'SELECT job_id,severity,source,evidence_id,evidence_refs,flag_review FROM findings'):
            f=dict(r)
            f['evidence_refs']=json.loads(f.get('evidence_refs') or '[]')
            findings_by_job.setdefault(f.pop('job_id'),[]).append(f)
    for item in rows:
        details=json.loads(item.pop('details') or '{}')
        item['ai_recommendation']=(recommend_ai(details.get('verification'),
            findings_by_job.get(item['id'],[]))
            if item['status']=='completed' else None)
    return rows
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
        d['ai_recommendation']=(recommend_ai(d['details'].get('verification'),d['findings'])
                                 if d['status']=='completed' else None)
        d['label_suggestion']=suggest_label(d['ai_recommendation'],d['findings'])
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
               'ai_recommendation':result['ai_recommendation'],
               'review_decision':result.get('review_decision'),
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
    # \d{3}.jpg = UI timeline thumbnails; ocr-\d{8}.jpg = frames saved by full/adaptive OCR.
    if not re.fullmatch(r'[0-9a-f]{12}',jid) or not re.fullmatch(r'(?:\d{3}|ocr-\d{8})\.jpg',name):raise HTTPException(400,'Invalid frame')
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
    error_types:list[str]=Field(default_factory=list)
@app.post('/api/jobs/{jid}/labels')
def label_job(jid:str,v:LabelIn):
    if v.label not in ('clean','error','uncertain'):raise HTTPException(400,'Invalid label')
    with db() as c:
        if not c.execute('SELECT 1 FROM jobs WHERE id=?',(jid,)).fetchone():raise HTTPException(404,'Job not found')
    # Record what the AI suggested at labeling time, so agreement is auditable.
    job=get_job(jid)
    suggestion=job.get('label_suggestion') or {}
    suggested=suggestion.get('label')
    source=('accepted_ai_suggestion' if suggested==v.label else
            'reviewer_override' if suggested else 'reviewer_only')
    notes=v.notes
    if v.error_types:
        notes=(notes+' | ' if notes else '')+'Loại lỗi: '+', '.join(t[:60] for t in v.error_types[:8])
    with db() as c:
        c.execute('INSERT INTO labels(job_id,annotator,label,notes,created_at,ai_suggested_label,label_source) VALUES(?,?,?,?,?,?,?)',
                  (jid,v.annotator,v.label,notes,utc(),suggested,source))
        audit(c,jid,v.annotator,'ground_truth_label',{'label':v.label,'notes':notes,
              'ai_suggested_label':suggested,'label_source':source,
              'ai_suggestion_codes':suggestion.get('codes',[])})
    return {'ok':True,'label_source':source,'ai_suggested_label':suggested}
@app.get('/api/metrics')
def metrics():
    """Actual-only candidate metrics; same policy as /api/dataset/summary."""
    with db() as c:
        jobs=[dict(r) for r in c.execute('SELECT id,status,review_decision,details FROM jobs')]
        completed=[j for j in jobs if j['status']=='completed']
        evaluated=[]
        coverage_excluded=0
        reviewer_truth=consensus_truth=accepted=overridden=0
        for j in completed:
            coverage=json.loads(j['details'] or '{}').get('coverage',{})
            if not sufficient_coverage(coverage):
                coverage_excluded+=1
                continue
            labels=[dict(r) for r in c.execute('SELECT annotator,label,label_source FROM labels WHERE job_id=? ORDER BY id',(j['id'],))]
            truth=independent_consensus(labels)
            if truth is None:
                # PO decision 02/11/2026: the session reviewer confirms the AI
                # suggestion. Use the reviewer's latest clean/error label, but
                # report it separately: it is not independent of the AI.
                latest=[l for l in labels if l['label'] in ('clean','error')]
                if not latest:continue
                truth=latest[-1]['label']
                reviewer_truth+=1
            else:
                consensus_truth+=1
            if any(l.get('label_source')=='accepted_ai_suggestion' for l in labels):accepted+=1
            if any(l.get('label_source')=='reviewer_override' for l in labels):overridden+=1
            findings=[dict(r) for r in c.execute('SELECT code,severity FROM findings WHERE job_id=?',(j['id'],))]
            evaluated.append((truth=='error',predicted_error(findings)))
        result=calculate_metrics(evaluated)
        result.update({'total':len(jobs),'completed':len(completed),
                       'reviewed':sum(bool(j['review_decision']) for j in jobs),
                       'excluded_insufficient_coverage':coverage_excluded,
                       'truth_from_independent_consensus':consensus_truth,
                       'truth_from_session_reviewer':reviewer_truth,
                       'reviewer_accepted_ai_suggestion':accepted,
                       'reviewer_overrode_ai_suggestion':overridden,
                       'note':('Truth = >=2 agreeing annotators when available, else the session reviewer label. '
                               'Reviewer labels are given after seeing the AI suggestion, so they measure '
                               'reviewer agreement with the AI, not independent accuracy.')})
        return result


# Additive, backwards-compatible Sprint-2 evaluation dataset routes.
install_dataset_routes(app,db,utc)
install_product_import_routes(app,db,utc)
install_export_routes(app, db, get_job, utc)
