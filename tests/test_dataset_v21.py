"""Offline regression coverage for workbook import and metric isolation (no real media)."""
from html import escape
from io import BytesIO
import zipfile

from fastapi.testclient import TestClient

from verifai_core.dataset import parse_official_workbook

SHEETS = [
 '1. Kich ban goc','2. Kich ban loi','3. Mo ta video cong khai',
 '4. Gan nhan video cong khai','5. So sanh video kiem soat',
 '6. So sanh video cong khai','7. Policy Rules','8. HD gán nhãn  '
]

def example_workbook() -> bytes:
    """Create minimal OOXML, exercising inlineStr parsing and case enumeration."""
    sheets={name:[] for name in SHEETS}
    for i in range(1,7):
        sheets[SHEETS[0]].append([f'VID_GOC{i:02}',f'SKU{i:03}',f'Sản phẩm {i}',
          'Brand',100000,'200ml','Description','Claim 1; Claim 2','Giả lập','Tester'])
    for i in range(1,45):
        sheets[SHEETS[1]].append([f'VID_LOI{i:02}',f'VID_GOC{(i-1)%6+1:02}','Sai giá',
          'Giá không khớp','100.000đ','99.000đ','0–5s','Cao','','Tester','Đã hoàn thành'])
    for i in range(1,31):
        code=f'PUB{i:03}'
        sheets[SHEETS[2]].append([code,'https://www.tiktok.com/a','TikTok',
          'https://example.org/product','Product','','Giá chưa xác minh','Claim',46306,'Tester'])
        sheets[SHEETS[3]].append([code,'Tester','Có' if i%2 else 'Không','Sai giá' if i%2 else ''])
    for i in range(1,45):
        code=f'VID_LOI{i:02}'
        sheets[SHEETS[4]].append([code,'Có','Sai giá','Có','Sai giá','TP','Tester'])
    for i in range(1,7):
        sheets[SHEETS[4]].append([f'VID_GOC{i:02}','Không','','Không','','TN','Tester'])
    for i in range(1,31):
        sheets[SHEETS[5]].append([f'PUB{i:03}','Không','','Có','Sai giá','FP','Tester'])
    for i in range(1,11):
        sheets[SHEETS[6]].append([f'RULE{i:02}','Rule','Policy','https://example.org',
               '','summary','alert','PRICE-01','Cao','Tester','Tham khảo','Chưa xác minh'])
    def colstr(n):
        name='';n+=1
        while n:
            n,r=divmod(n-1,26);name=chr(65+r)+name
        return name
    def xml_rows(rows):
        buf=['<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
          '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>']
        for y,row in enumerate(rows,1):
            buf.append(f'<row r="{y}">')
            for x,value in enumerate(row):
                ref=f'{colstr(x)}{y}'
                if isinstance(value,(int,float)):
                    buf.append(f'<c r="{ref}"><v>{value}</v></c>')
                else:
                    buf.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
            buf.append('</row>')
        buf.append('</sheetData></worksheet>');return ''.join(buf)
    b=BytesIO()
    with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('xl/workbook.xml','<?xml version="1.0" encoding="UTF-8"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+''.join(f'<sheet name="{escape(n,quote=True)}" sheetId="{i}" r:id="rId{i}"/>' for i,n in enumerate(SHEETS,1))+'</sheets></workbook>')
        z.writestr('xl/_rels/workbook.xml.rels','<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,9))+'</Relationships>')
        for i,name in enumerate(SHEETS,1):
            z.writestr(f'xl/worksheets/sheet{i}.xml',xml_rows(sheets[name]))
    return b.getvalue()


def test_workbook_parser_counts_and_origin():
    result=parse_official_workbook(example_workbook())
    assert result['counts']=={'original':6,'controlled_error':44,'public':30}
    assert len(result['simulated'])==80
    assert len(result['rules'])==10
    assert result['cases'][0]['price']==100000
    assert next(c for c in result['cases'] if c['code']=='PUB001')['price'] is None


def test_data_import_idempotent_truth_and_simulation_isolation(monkeypatch,tmp_path):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'db.sqlite3')
    backend.init()  # validates migration works on freshly isolated database
    client=TestClient(backend.app)
    payload=example_workbook()
    def upload():
        return client.post('/api/dataset/import',files={'file':('dataset.xlsx',BytesIO(payload),
          'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert upload().status_code==200
    assert upload().status_code==200
    cases=client.get('/api/dataset/cases').json()
    assert len(cases)==80
    assert len(client.get('/api/products').json())==6
    summ=client.get('/api/dataset/summary').json()
    assert summ['simulated_prediction_rows']==80
    assert summ['actual']['evaluated']==0
    assert summ['human_consensus_verified']==0
    # One imported manual reviewer from workbook does not qualify as consensus.
    assert next(c for c in cases if c['code']=='PUB001')['truth_origin']=='single_annotator'
    assert client.post('/api/dataset/cases/PUB001/annotations',json={'annotator':'A reviewer','label':'error'}).json()['verified_truth'] is None
    assert client.post('/api/dataset/cases/PUB001/annotations',json={'annotator':'B reviewer','label':'error'}).json()['verified_truth']=='error'
    s=client.get('/api/dataset/summary').json()
    assert s['human_consensus_verified']==1
    assert s['actual']['evaluated']==0  # still no actual job linked
    # Insert a synthetic *completed job record* to verify actual-only aggregation;
    # this is fixture plumbing, not evidence of performance on a video.
    prod=client.get('/api/products').json()[0]
    import json
    with backend.db() as con:
        con.execute("""INSERT INTO jobs (id,filename,stored_name,product_id,status,decision,
          created_at,details,case_code) VALUES (?,?,?,?,?,?,?,?,?)""",
          ('synthetic-test','fixture.mp4','fixture.mp4',prod['id'],'completed','Regenerate',
           '2026-01-01T00:00:00+00:00',json.dumps({'coverage':{'ocr':'ok'}}),'PUB001'))
        con.execute("INSERT INTO findings(job_id,code,severity,timestamp,detail) VALUES (?,?,?,?,?)",
          ('synthetic-test','PRICE-01','high',1.0,'test finding'))
    actual=client.get('/api/dataset/summary').json()['actual']
    assert actual['evaluated']==1 and actual['tp']==1 and actual['precision']==1
    # Contradictory independent reviewer invalidates consensus.
    conflict=client.post('/api/dataset/cases/PUB001/annotations',json={'annotator':'C reviewer','label':'clean'})
    assert conflict.status_code==200
    assert conflict.json()['verified_truth'] is None
    assert client.get('/api/dataset/summary').json()['actual']['evaluated']==0
    assert client.post('/api/dataset/import',files={'file':('invalid.csv',BytesIO(b'a,b'))}).status_code==400
