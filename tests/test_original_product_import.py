"""Offline regression coverage: only Sheet 1 becomes Product Truth."""
from io import BytesIO
import zipfile
import re

from fastapi.testclient import TestClient

import importlib.util
from pathlib import Path

_fixture_path = Path(__file__).resolve().parent / 'test_dataset_v21.py'
_spec = importlib.util.spec_from_file_location('test_dataset_v21_fixture', _fixture_path)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)
example_workbook = _module.example_workbook
from verifai_core.product_import import parse_original_products

def only_original_sheet(workbook: bytes) -> bytes:
    source = BytesIO(workbook)
    target = BytesIO()
    with zipfile.ZipFile(source) as inp, zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as out:
        for name in ['xl/workbook.xml','xl/_rels/workbook.xml.rels',
                     'xl/worksheets/sheet1.xml']:
            text=inp.read(name)
            if name=='xl/workbook.xml':
                x=text.decode()
                x=re.sub(r'<sheets>.*?</sheets>',
                    '<sheets><sheet name="1. Kich ban goc" sheetId="1" r:id="rId1"/></sheets>',x)
                text=x.encode()
            if name.endswith('.rels'):
                text=(
                    '<?xml version="1.0" encoding="UTF-8"?>'
                    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
                    '</Relationships>').encode()
            out.writestr(name,text)
    return target.getvalue()

def test_parser_accepts_original_only_and_ignores_error_sheets():
    original=parse_original_products(only_original_sheet(example_workbook()))
    full=parse_original_products(example_workbook())
    assert original==full
    assert len(original)==6
    assert original[0]['sku']=='SKU001'
    assert original[0]['variant']=='200ml'
    assert original[0]['expected_video_description']
    assert len(original[0]['approved_claims'])==2
    assert not any('VID_LOI' in p['video_code'] for p in original)

def test_product_import_keeps_ground_truth_unverified_and_preserves_existing(monkeypatch,tmp_path):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'only_six.sqlite3')
    backend.init()
    client=TestClient(backend.app)
    workbook=only_original_sheet(example_workbook())
    def upload(body=workbook):
        return client.post('/api/products/import',files={'file':('only_six.xlsx',
                            BytesIO(body),
                            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    r=upload()
    assert r.status_code==200, r.text
    assert r.json()['products_read']==6
    assert r.json()['products_created']==6
    assert r.json()['matched_existing']==0
    products=client.get('/api/products').json()
    assert len(products)==6
    sku001=next(p for p in products if p['sku']=='SKU001')
    assert sku001['variant']=='200ml'
    assert sku001['video_code']=='VID_GOC01'
    assert sku001['reference_status']=='unverified'
    assert sku001['source_class']=='Giả lập'
    assert len(client.get('/api/dataset/cases').json())==0
    assert client.get('/api/dataset/summary').json()['simulated_prediction_rows']==0
    r2=upload()
    assert r2.status_code==200
    assert r2.json()['products_created']==0
    assert r2.json()['matched_existing']==6
    assert len(client.get('/api/products').json())==6
    assert client.post('/api/products/import',files={'file':('invalid.csv',
        BytesIO(b'bad'),'text/csv')}).status_code==400

def test_existing_reviewed_product_is_not_overwritten(monkeypatch,tmp_path):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'existing.sqlite3')
    backend.init()
    client=TestClient(backend.app)
    created=client.post('/api/products',json={
      'sku':'SKU001','name':'Validated name','brand':'ValidatedBrand',
      'price':999999,'claims':[],'banned':[],
      'reference_status':'reviewed','reference_note':'Manual source verified'
    })
    assert created.status_code==200
    r=client.post('/api/products/import',files={'file':('original.xlsx',
        BytesIO(only_original_sheet(example_workbook())),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')})
    assert r.status_code==200, r.text
    assert r.json()['products_created']==5
    assert r.json()['core_conflicts_not_overwritten']==['SKU001']
    p=client.get('/api/products/'+created.json()['id']).json()
    assert p['name']=='Validated name'
    assert p['price']==999999
    assert p['reference_status']=='reviewed'
    assert p['variant']=='200ml'


def test_clear_only_import_owned_unreviewed_products(monkeypatch,tmp_path):
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'reset-import.sqlite3')
    backend.init()
    client=TestClient(backend.app)
    assert client.post('/api/products/import',files={'file':('original.xlsx',
        BytesIO(only_original_sheet(example_workbook())),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}).status_code==200
    assert len(client.get('/api/products').json())==6
    assert client.post('/api/products/import/reset',json={
        'confirmation':'incorrect'}).status_code==400
    result=client.post('/api/products/import/reset',json={'confirmation':'XOA EXCEL'})
    assert result.status_code==200,result.text
    assert result.json()['removed_imported_products']==6
    assert client.get('/api/products').json()==[]

def test_clear_excel_refuses_when_video_jobs_reference_product(monkeypatch,tmp_path):
    import json
    import backend
    monkeypatch.setattr(backend,'DB',tmp_path/'import-linked.sqlite3')
    backend.init()
    client=TestClient(backend.app)
    assert client.post('/api/products/import',files={'file':('original.xlsx',
        BytesIO(only_original_sheet(example_workbook())),
        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')}).status_code==200
    pid=client.get('/api/products').json()[0]['id']
    with backend.db() as c:
        c.execute('''INSERT INTO jobs(id,filename,stored_name,product_id,status,
                     created_at,details) VALUES(?,?,?,?,?,?,?)''',(
                 'fixture-job','video.mp4','fixture-job.mp4',pid,'completed',
                 '2026-10-30T00:00:00Z',json.dumps({})))
    result=client.post('/api/products/import/reset',json={
        'confirmation':'XOA EXCEL'})
    assert result.status_code==409
    assert len(client.get('/api/products').json())==6


def test_compiler_uses_scenarios_not_fabricated_video_metrics():
    from pathlib import Path
    import importlib.util
    p=Path(__file__).resolve().parents[1] / 'scripts' / 'build_sprint2_examples.py'
    spec=importlib.util.spec_from_file_location('scenario_compile',p)
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    training=module.compile_examples(example_workbook())
    assert len(training['examples'])==44
    assert training['trained_model_weights'] is False
    assert sum(training['counts'].values())==44
    assert training['examples'][0]['label_status']=='scenario_only_unadjudicated'
    assert training['examples'][0]['source_group']=='VID_GOC01'
