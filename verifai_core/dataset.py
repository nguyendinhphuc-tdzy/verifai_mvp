"""Dataset-driven evaluation layer for the official Sprint-2 workbook.

The workbook is an evaluation *plan*, not 80 observed model runs. Sheet 5/6
predictions are kept separately and NEVER used as actual model metrics.
No xlsx data is sent to an external service; this import is local only.
"""
from __future__ import annotations
from verifai_core.evaluation import calculate_metrics, predicted_error, sufficient_coverage, independent_consensus

from collections import Counter
from datetime import datetime, timezone
from io import BytesIO
import hashlib
import json
import posixpath
import re
from typing import Any
import uuid
import xml.etree.ElementTree as ET
import zipfile

from fastapi import File, HTTPException, UploadFile
from pydantic import BaseModel, Field

X = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
REL = '{http://schemas.openxmlformats.org/officeDocument/2006/relationships}'
PACKAGE_REL = '{http://schemas.openxmlformats.org/package/2006/relationships}'
CASE_PATTERN = re.compile(r'^(VID_GOC\d{2}|VID_LOI\d{2}|PUB\d{3})$')
GROUP_NAMES = {'original': 'Video gốc', 'controlled_error': 'Video lỗi có kiểm soát', 'public': 'Video công khai'}
MAX_XLSX_BYTES = 8 * 1024 * 1024
MAX_EXPANDED_BYTES = 28 * 1024 * 1024


def _as_text(value: Any) -> str:
    return '' if value is None else str(value).strip()


def _sheet_rows(raw: bytes) -> dict[str, list[list[Any]]]:
    """Read values from XLSX OOXML with only Python standard library.

    Handles sharedStrings, inline strings and cached formula values. File size and
    decompressed sizes are bounded before parsing.
    """
    try:
        zf = zipfile.ZipFile(BytesIO(raw))
        infos = zf.infolist()
        if len(infos) > 400 or sum(z.file_size for z in infos) > MAX_EXPANDED_BYTES:
            raise ValueError('Workbook chứa quá nhiều dữ liệu để nhập an toàn')
        names = set(zf.namelist())
        if not {'xl/workbook.xml', 'xl/_rels/workbook.xml.rels'}.issubset(names):
            raise ValueError('Không tìm thấy cấu trúc workbook XLSX')
        strings = []
        if 'xl/sharedStrings.xml' in names:
            doc = ET.fromstring(zf.read('xl/sharedStrings.xml'))
            for si in doc.findall(f'{X}si'):
                strings.append(''.join(t.text or '' for t in si.iter(f'{X}t')))
        wb = ET.fromstring(zf.read('xl/workbook.xml'))
        rels_doc = ET.fromstring(zf.read('xl/_rels/workbook.xml.rels'))
        rels = {r.attrib.get('Id'):r.attrib.get('Target','') for r in rels_doc.findall(f'{PACKAGE_REL}Relationship')}
        sheets: dict[str, list[list[Any]]] = {}
        for sheet in wb.findall(f'{X}sheets/{X}sheet'):
            sheet_name = sheet.attrib.get('name','')
            target = rels.get(sheet.attrib.get(f'{REL}id'))
            if not target: continue
            if target.startswith('/'):
                path=target.lstrip('/')
            else:
                path=posixpath.normpath(posixpath.join('xl',target))
            if not path.startswith('xl/worksheets/') or path not in names:
                raise ValueError('Đường dẫn worksheet không hợp lệ')
            root=ET.fromstring(zf.read(path))
            data=[]
            for row in root.findall(f'{X}sheetData/{X}row'):
                values={}
                for cell in row.findall(f'{X}c'):
                    coord=cell.attrib.get('r','')
                    match=re.match(r'^([A-Z]{1,3})\d+$',coord)
                    if not match: continue
                    col=0
                    for character in match.group(1): col=col*26+ord(character)-64
                    col-=1
                    if col>30: continue
                    v=cell.find(f'{X}v')
                    kind=cell.attrib.get('t')
                    if kind=='inlineStr':
                        inline=cell.find(f'{X}is')
                        value=''.join(t.text or '' for t in inline.iter(f'{X}t')) if inline is not None else None
                    elif v is None or v.text is None: value=None
                    elif kind=='s':
                        idx=int(v.text);value=strings[idx] if idx<len(strings) else None
                    elif kind in ('str','e'):value=v.text
                    elif kind=='b':value=v.text=='1'
                    else:
                        try:
                            number=float(v.text)
                            value=int(number) if number.is_integer() else number
                        except ValueError:value=v.text
                    values[col]=value
                if values:
                    data.append([values.get(i) for i in range(max(values)+1)])
            sheets[sheet_name]=data
        return sheets
    except (zipfile.BadZipFile, ET.ParseError, KeyError, IndexError) as exc:
        raise ValueError(f'File XLSX không hợp lệ: {exc}') from exc


def _val(row: list[Any], index: int) -> Any:
    return row[index] if index<len(row) else None


def _vn_label(value: Any) -> str:
    x=_as_text(value).casefold()
    return 'error' if x=='có' else 'clean' if x=='không' else 'unknown'


def _int_price(value: Any) -> int | None:
    # Do NOT treat ranges, foreign currencies or unspecified prices as a verified VND price.
    if isinstance(value,(int,float)) and value>=0 and float(value).is_integer():return int(value)
    if isinstance(value,str) and re.fullmatch(r'[\d.,\s]+\s*(?:đ|₫|vnd|vnđ)',value.strip(),re.I):
        return int(re.sub(r'[^\d]','',value))
    return None


def _rows_named(sheets: dict, start: str) -> list[list[Any]]:
    matches=[rows for name,rows in sheets.items() if name.strip().casefold().startswith(start.casefold())]
    if len(matches)!=1:raise ValueError(f'Workbook cần đúng một sheet bắt đầu bằng "{start}"')
    return matches[0]


def parse_official_workbook(data: bytes) -> dict[str, Any]:
    sheets=_sheet_rows(data)
    originals=_rows_named(sheets,'1. Kich ban goc')
    errors=_rows_named(sheets,'2. Kich ban loi')
    public=_rows_named(sheets,'3. Mo ta video cong khai')
    manual=_rows_named(sheets,'4. Gan nhan video cong khai')
    controlled_cmp=_rows_named(sheets,'5. So sanh video kiem soat')
    public_cmp=_rows_named(sheets,'6. So sanh video cong khai')
    policies=_rows_named(sheets,'7. Policy Rules')
    cases={};sku_ref={}
    for row in originals:
        code=_as_text(_val(row,0))
        if not re.fullmatch(r'VID_GOC\d{2}',code):continue
        sku=_as_text(_val(row,1));sku_ref[code]=sku
        cases[code]={'code':code,'group':'original','base_code':'','sku':sku,'name':_as_text(_val(row,2)),
         'brand':_as_text(_val(row,3)),'price':_int_price(_val(row,4)),'price_raw':_as_text(_val(row,4)),
         'variant':_as_text(_val(row,5)),'product_context':_as_text(_val(row,6)),
         'approved_claims':[q.strip() for q in _as_text(_val(row,7)).split(';') if q.strip()],
         'data_origin':_as_text(_val(row,8)),'source_url':'','product_url':'','platform':'',
         'issue_type':'','description':'','expected':'','observed':'','location':'','severity':'',
         'source_status':'script_reference','expected_truth':'clean','truth_origin':'scenario_design'}
    for row in errors:
        code=_as_text(_val(row,0))
        if not re.fullmatch(r'VID_LOI\d{2}',code):continue
        base_code=_as_text(_val(row,1))
        if base_code not in cases:raise ValueError(f'{code}: không tìm thấy video gốc {base_code}')
        source=cases[base_code]
        cases[code]={**source,'code':code,'group':'controlled_error','base_code':base_code,
         'issue_type':_as_text(_val(row,2)),'description':_as_text(_val(row,3)),
         'expected':_as_text(_val(row,4)),'observed':_as_text(_val(row,5)),
         'location':_as_text(_val(row,6)),'severity':_as_text(_val(row,7)),
         'source_status':_as_text(_val(row,10)) or 'not_recorded',
         'expected_truth':'error','truth_origin':'scenario_design'}
    manual_map={}
    for row in manual:
        code=_as_text(_val(row,0))
        if re.fullmatch(r'PUB\d{3}',code):
            manual_map[code]={'label':_vn_label(_val(row,2)),'annotator':_as_text(_val(row,1)),
              'issue_type':_as_text(_val(row,3)), 'description':_as_text(_val(row,4)),
              'location':_as_text(_val(row,5)), 'severity':_as_text(_val(row,6)),
              'expected':_as_text(_val(row,7)), 'observed':_as_text(_val(row,8))}
    for row in public:
        code=_as_text(_val(row,0))
        if not re.fullmatch(r'PUB\d{3}',code):continue
        ann=manual_map.get(code,{})
        cases[code]={'code':code,'group':'public','base_code':'','sku':_as_text(_val(row,5)),
         'name':_as_text(_val(row,4)),'brand':'','price':_int_price(_val(row,6)),
         'price_raw':_as_text(_val(row,6)),'variant':'','product_context':_as_text(_val(row,7)),
         'approved_claims':[],'data_origin':'public_product_page_unverified',
         'source_url':_as_text(_val(row,1)),'product_url':_as_text(_val(row,3)),
         'platform':_as_text(_val(row,2)),'issue_type':ann.get('issue_type',''),
         'description':ann.get('description',''),'expected':ann.get('expected',''),
         'observed':ann.get('observed',''),'location':ann.get('location',''),
         'severity':ann.get('severity',''),'source_status':'url_only',
         'expected_truth':ann.get('label','unknown'),'truth_origin':'single_annotator' if ann.get('annotator') else 'unlabeled',
         'source_annotator':ann.get('annotator','')}
    counts=Counter(c['group'] for c in cases.values())
    if counts!={'original':6,'controlled_error':44,'public':30}:
        raise ValueError(f'Số case không khớp phạm vi đã chốt (6/44/30): {dict(counts)}')
    simulated={}
    for source,rows in [('controlled',controlled_cmp),('public',public_cmp)]:
        for row in rows:
            code=_as_text(_val(row,0))
            if not CASE_PATTERN.fullmatch(code):continue
            simulated[code]={'code':code,'sheet':source,'truth':_vn_label(_val(row,1)),
              'truth_type':_as_text(_val(row,2)),'prediction':_vn_label(_val(row,3)),
              'prediction_type':_as_text(_val(row,4)),'classification':_as_text(_val(row,5))}
    rules=[]
    for row in policies:
        rid=_as_text(_val(row,0))
        if not re.fullmatch(r'RULE\d{2}',rid):continue
        rules.append({'rule_id':rid,'name':_as_text(_val(row,1)),
         'source_type':_as_text(_val(row,2)),'source_reference':_as_text(_val(row,3)),
         'linked_error_code':_as_text(_val(row,7)),'severity':_as_text(_val(row,8)),
         'verification_status':_as_text(_val(row,11)),'notes':_as_text(_val(row,10))})
    return {'cases':list(cases.values()), 'simulated':list(simulated.values()),'rules':rules,
            'counts':dict(counts),'checksum':hashlib.sha256(data).hexdigest()}


class HumanAnnotation(BaseModel):
    annotator: str = Field(min_length=2,max_length=100)
    label: str
    issue_type: str = Field(default='',max_length=120)
    severity: str = Field(default='',max_length=40)
    timestamp: str = Field(default='',max_length=100)
    notes: str = Field(default='',max_length=2000)


class CaseLink(BaseModel):
    product_id: str | None = None
    job_id: str | None = None


def ensure_dataset_schema(db) -> None:
    """Run on every backend.init(), including isolated test databases."""
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS dataset_cases(
          code TEXT PRIMARY KEY, case_group TEXT NOT NULL, base_code TEXT, sku TEXT,
          name TEXT, brand TEXT, price INTEGER, price_raw TEXT, variant TEXT,
          product_context TEXT, approved_claims TEXT, data_origin TEXT,
          source_url TEXT, product_url TEXT, platform TEXT, issue_type TEXT,
          description TEXT, expected TEXT, observed TEXT, location TEXT,
          severity TEXT, source_status TEXT, expected_truth TEXT, truth_origin TEXT,
          source_annotator TEXT, product_id TEXT, verified_truth TEXT, verified_by TEXT,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dataset_simulated(
          code TEXT PRIMARY KEY, source_sheet TEXT NOT NULL, truth TEXT,
          truth_type TEXT, prediction TEXT, prediction_type TEXT, classification TEXT);
        CREATE TABLE IF NOT EXISTS dataset_rules(
          rule_id TEXT PRIMARY KEY, name TEXT, source_type TEXT, source_reference TEXT,
          linked_error_code TEXT, severity TEXT, verification_status TEXT, notes TEXT);
        CREATE TABLE IF NOT EXISTS dataset_imports(
          id TEXT PRIMARY KEY, checksum TEXT NOT NULL, created_at TEXT NOT NULL,
          case_count INTEGER NOT NULL, note TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS dataset_annotations(
          code TEXT NOT NULL, annotator TEXT NOT NULL, label TEXT NOT NULL,
          issue_type TEXT, severity TEXT, timestamp TEXT, notes TEXT, created_at TEXT NOT NULL,
          PRIMARY KEY (code, annotator));
        ''')
        existing={r['name'] for r in c.execute('PRAGMA table_info(jobs)')}
        if 'case_code' not in existing:c.execute('ALTER TABLE jobs ADD COLUMN case_code TEXT')


def install_dataset_routes(app, db, utc) -> None:
    """Extends v2 without modifying existing API semantics or past job data."""
    ensure_dataset_schema(db)

    @app.post('/api/dataset/import')
    async def dataset_import(file: UploadFile = File(...)):
        if not (file.filename or '').lower().endswith('.xlsx'):
            raise HTTPException(400,'Chỉ hỗ trợ workbook .xlsx')
        content=await file.read(MAX_XLSX_BYTES+1)
        if len(content)>MAX_XLSX_BYTES:raise HTTPException(413,'Workbook vượt 8MB')
        try: data=parse_official_workbook(content)
        except (ValueError, TypeError, OverflowError) as exc:raise HTTPException(400,str(exc)) from exc
        now=utc();added_products=0
        with db() as c:
            for item in data['cases']:
                product_id=None
                if item['group'] in ('original','controlled_error'):
                    row=c.execute('SELECT id FROM products WHERE sku=? ORDER BY created_at DESC LIMIT 1',(item['sku'],)).fetchone()
                    if row:product_id=row['id']
                    else:
                        product_id=uuid.uuid4().hex[:12]
                        c.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?,?)',(
                            product_id,item['sku'],item['name'],item['brand'],item['price'],
                            json.dumps(item['approved_claims'],ensure_ascii=False),'[]',now))
                        added_products+=1
                old=c.execute('SELECT product_id,verified_truth,verified_by FROM dataset_cases WHERE code=?',(item['code'],)).fetchone()
                if old:
                    product_id=old['product_id'] or product_id
                values=(item['code'],item['group'],item['base_code'],item['sku'],item['name'],item['brand'],
                    item['price'],item['price_raw'],item['variant'],item['product_context'],
                    json.dumps(item['approved_claims'],ensure_ascii=False),item['data_origin'],
                    item['source_url'],item['product_url'],item['platform'],item['issue_type'],item['description'],
                    item['expected'],item['observed'],item['location'],item['severity'],item['source_status'],
                    item['expected_truth'],item['truth_origin'],item.get('source_annotator',''),product_id,
                    old['verified_truth'] if old else None,old['verified_by'] if old else None,now)
                c.execute('''INSERT INTO dataset_cases VALUES ('''+','.join('?' for _ in values)+''')
                    ON CONFLICT(code) DO UPDATE SET case_group=excluded.case_group,base_code=excluded.base_code,
                    sku=excluded.sku,name=excluded.name,brand=excluded.brand,price=excluded.price,
                    price_raw=excluded.price_raw,variant=excluded.variant,product_context=excluded.product_context,
                    approved_claims=excluded.approved_claims,data_origin=excluded.data_origin,
                    source_url=excluded.source_url,product_url=excluded.product_url,platform=excluded.platform,
                    issue_type=excluded.issue_type,description=excluded.description,expected=excluded.expected,
                    observed=excluded.observed,location=excluded.location,severity=excluded.severity,
                    source_status=excluded.source_status,expected_truth=excluded.expected_truth,
                    truth_origin=excluded.truth_origin,source_annotator=excluded.source_annotator,
                    product_id=excluded.product_id,updated_at=excluded.updated_at''',values)
            for x in data['simulated']:
                c.execute('''INSERT OR REPLACE INTO dataset_simulated VALUES (?,?,?,?,?,?,?)''',
                          (x['code'],x['sheet'],x['truth'],x['truth_type'],x['prediction'],x['prediction_type'],x['classification']))
            for x in data['rules']:
                c.execute('''INSERT OR REPLACE INTO dataset_rules VALUES (?,?,?,?,?,?,?,?)''',
                          (x['rule_id'],x['name'],x['source_type'],x['source_reference'],
                           x['linked_error_code'],x['severity'],x['verification_status'],x['notes']))
            c.execute('INSERT INTO dataset_imports VALUES(?,?,?,?,?)',
                      (uuid.uuid4().hex[:12],data['checksum'],now,len(data['cases']),
                       'Workbook official 80 cases. Predictions sheet 5/6 are simulated, not actual runs.'))
        return {'ok':True,'cases':len(data['cases']),'groups':data['counts'],'products_created':added_products,
                'simulated_rows':len(data['simulated']),'reference_rules':len(data['rules']),
                'note':'Đã nhập kịch bản đánh giá. Chưa chạy model trên 80 video; metrics giả lập tách riêng.'}

    @app.get('/api/dataset/cases')
    def dataset_cases():
        with db() as c:
            rows=c.execute('''SELECT d.*, (SELECT COUNT(*) FROM jobs j WHERE j.case_code=d.code) AS actual_runs,
              (SELECT COUNT(*) FROM dataset_annotations a WHERE a.code=d.code) AS annotation_count
              FROM dataset_cases d ORDER BY CASE d.case_group WHEN 'original' THEN 0 WHEN 'controlled_error' THEN 1 ELSE 2 END,d.code''').fetchall()
            result=[dict(r) for r in rows]
            for d in result:d['approved_claims']=json.loads(d['approved_claims'] or '[]')
            return result

    @app.get('/api/dataset/policies')
    def dataset_policies():
        with db() as c:return [dict(r) for r in c.execute('SELECT * FROM dataset_rules ORDER BY rule_id')]

    @app.post('/api/dataset/cases/{code}/link')
    def dataset_link(code:str,payload:CaseLink):
        with db() as c:
            case=c.execute('SELECT code,product_id FROM dataset_cases WHERE code=?',(code,)).fetchone()
            if not case:raise HTTPException(404,'Case not found')
            if payload.product_id:
                if not c.execute('SELECT 1 FROM products WHERE id=?',(payload.product_id,)).fetchone():
                    raise HTTPException(404,'Product not found')
                c.execute('UPDATE dataset_cases SET product_id=?,updated_at=? WHERE code=?',(payload.product_id,utc(),code))
            if payload.job_id:
                job=c.execute('SELECT product_id FROM jobs WHERE id=?',(payload.job_id,)).fetchone()
                if not job:raise HTTPException(404,'Job not found')
                effective_pid=payload.product_id or case['product_id']
                if effective_pid and effective_pid!=job['product_id']:
                    raise HTTPException(409,'Job đang liên kết SKU khác. Cần chọn đúng Product Truth.')
                c.execute('UPDATE jobs SET case_code=? WHERE id=?',(code,payload.job_id))
        return {'ok':True,'case_code':code}

    @app.post('/api/dataset/cases/{code}/annotations')
    def add_annotation(code:str,payload:HumanAnnotation):
        if payload.label not in ('error','clean','uncertain'):raise HTTPException(400,'Nhãn phải là error/clean/uncertain')
        annotator=payload.annotator.strip()
        with db() as c:
            if not c.execute('SELECT 1 FROM dataset_cases WHERE code=?',(code,)).fetchone():raise HTTPException(404,'Case not found')
            c.execute('''INSERT INTO dataset_annotations VALUES(?,?,?,?,?,?,?,?)
              ON CONFLICT(code,annotator) DO UPDATE SET label=excluded.label,issue_type=excluded.issue_type,
              severity=excluded.severity,timestamp=excluded.timestamp,notes=excluded.notes,created_at=excluded.created_at''',
              (code,annotator,payload.label,payload.issue_type,payload.severity,payload.timestamp,payload.notes,utc()))
            items=[r['label'] for r in c.execute('SELECT label FROM dataset_annotations WHERE code=?',(code,))]
            consensus=independent_consensus([dict(r) for r in c.execute('SELECT annotator,label FROM dataset_annotations WHERE code=?',(code,))])
            c.execute('UPDATE dataset_cases SET verified_truth=?,verified_by=?,updated_at=? WHERE code=?',
                      (consensus,'independent_consensus' if consensus else None,utc(),code))
        return {'case_code':code,'annotators':len(items),'verified_truth':consensus,
                'note':'Hai người độc lập phải thống nhất nhãn; nếu bất đồng, chưa tính vào actual metrics.'}

    @app.get('/api/dataset/summary')
    def dataset_summary():
        with db() as c:
            counts={r['case_group']:r['n'] for r in c.execute('SELECT case_group,COUNT(*) n FROM dataset_cases GROUP BY case_group')}
            count=sum(counts.values())
            linked=c.execute('SELECT COUNT(DISTINCT case_code) n FROM jobs WHERE case_code IS NOT NULL').fetchone()['n']
            completed=c.execute("SELECT COUNT(DISTINCT case_code) n FROM jobs WHERE case_code IS NOT NULL AND status='completed'").fetchone()['n']
            verified=c.execute("SELECT COUNT(*) n FROM dataset_cases WHERE verified_truth IN ('clean','error')").fetchone()['n']
            missing_product=c.execute("SELECT COUNT(*) n FROM dataset_cases WHERE product_id IS NULL").fetchone()['n']
            simulation_rows=c.execute('SELECT COUNT(*) n FROM dataset_simulated').fetchone()['n']
            # Actual metrics are derived exclusively from completed jobs + independent human consensus.
            samples=[]
            cases=c.execute("SELECT code,verified_truth FROM dataset_cases WHERE verified_truth IN ('clean','error')").fetchall()
            for d in cases:
                j=c.execute('''SELECT * FROM jobs WHERE case_code=? AND status='completed' ORDER BY finished_at DESC LIMIT 1''',
                            (d['code'],)).fetchone()
                if not j:continue
                details=json.loads(j['details'] or '{}');cov=details.get('coverage',{})
                if not sufficient_coverage(cov):
                    continue
                pred=predicted_error([dict(r) for r in c.execute('SELECT code,severity FROM findings WHERE job_id=?',(j['id'],))])
                samples.append((d['verified_truth']=='error',pred))
            calculated=calculate_metrics(samples)
            return {'planned_cases':count,'target':80,'groups':counts,'product_links_missing':missing_product,
                'cases_with_job':linked,'cases_with_completed_job':completed,'human_consensus_verified':verified,
                'simulated_prediction_rows':simulation_rows,'actual':calculated,
                'note':'Actual chỉ tính video đã chạy thật + >=2 annotator thống nhất + OCR/ASR/VLM có coverage. Simulated của Sheet 5–6 KHÔNG tính.'}
