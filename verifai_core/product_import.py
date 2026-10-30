"""Import only the six ORIGINAL product reference rows from Sprint-2 Excel.

No controlled errors, simulated predictions, public videos or ground truth are
imported by this endpoint. An existing SKU is never overwritten implicitly.
"""
from __future__ import annotations
import hashlib
import json
import re
import uuid

from fastapi import File, HTTPException, UploadFile

from verifai_core.claims import validate_reference_claims
from verifai_core.dataset import _as_text, _int_price, _rows_named, _sheet_rows, _val, MAX_XLSX_BYTES


def parse_original_products(content: bytes) -> list[dict]:
    sheets = _sheet_rows(content)
    rows = _rows_named(sheets, '1. Kich ban goc')
    products = []
    seen_codes = set()
    seen_skus = set()
    for row in rows:
        code = _as_text(_val(row, 0)).upper()
        if not re.fullmatch(r'VID_GOC\d{2}', code):
            continue
        sku = _as_text(_val(row, 1)).upper()
        name, brand = _as_text(_val(row, 2)), _as_text(_val(row, 3))
        price = _int_price(_val(row, 4))
        variant = _as_text(_val(row, 5))
        scene = _as_text(_val(row, 6))
        claims_text = _as_text(_val(row, 7))
        origin, owner, notes = (_as_text(_val(row, i)) for i in (8, 9, 10))
        if (not re.fullmatch(r'SKU[A-Z0-9_-]{1,76}', sku)
                or not name or not brand or price is None or price <= 0
                or not variant or not scene or len(name) > 180 or len(brand) > 100
                or len(variant) > 150 or len(scene) > 1500 or len(origin) > 200
                or len(owner) > 100 or len(notes) > 1000):
            raise ValueError(f'{code}: thiếu hoặc sai SKU, tên, brand, giá, biến thể hay mô tả video gốc')
        if code in seen_codes or sku.casefold() in seen_skus:
            raise ValueError(f'{code}: mã video hoặc SKU bị trùng')
        seen_codes.add(code)
        seen_skus.add(sku.casefold())
        approved, _ = validate_reference_claims(
            [x.strip() for x in claims_text.split(';') if x.strip()], [])
        products.append({
            'video_code':code, 'sku':sku, 'name':name, 'brand':brand,
            'price':price, 'variant':variant,
            'expected_video_description':scene, 'approved_claims':approved,
            'source_class':origin or 'unspecified', 'owner':owner, 'notes':notes,
        })
    if len(products) != 6 or seen_codes != {f'VID_GOC{i:02d}' for i in range(1,7)}:
        raise ValueError('MVP chỉ nhận đúng 6 sản phẩm gốc VID_GOC01–VID_GOC06 trong Sheet 1')
    return sorted(products, key=lambda p: p['video_code'])


def ensure_product_import_schema(db):
    with db() as c:
        c.execute('''CREATE TABLE IF NOT EXISTS product_import_profiles(
            product_id TEXT PRIMARY KEY,
            video_code TEXT NOT NULL,
            variant TEXT NOT NULL,
            expected_video_description TEXT NOT NULL,
            source_class TEXT NOT NULL,
            owner TEXT NOT NULL,
            notes TEXT NOT NULL,
            import_sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL,
            created_by_import INTEGER NOT NULL DEFAULT 0)''')


def install_product_import_routes(app, db, utc):
    ensure_product_import_schema(db)

    @app.post('/api/products/import')
    async def product_import(file: UploadFile = File(...)):
        if not (file.filename or '').lower().endswith('.xlsx'):
            raise HTTPException(400, 'Chỉ nhận file XLSX chứa Sheet 1 (6 video sản phẩm gốc)')
        data = await file.read(MAX_XLSX_BYTES + 1)
        if len(data) > MAX_XLSX_BYTES:
            raise HTTPException(413, 'Workbook vượt 8 MB')
        try:
            items = parse_original_products(data)
        except (ValueError, TypeError, OverflowError) as e:
            raise HTTPException(400, str(e)) from e
        stamp = utc()
        digest = hashlib.sha256(data).hexdigest()
        created = existing_count = 0
        conflicts = []
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            for p in items:
                row = c.execute('SELECT * FROM products WHERE sku=? COLLATE NOCASE',
                                (p['sku'],)).fetchone()
                if row is None:
                    product_id = uuid.uuid4().hex[:12]
                    c.execute('INSERT INTO products VALUES(?,?,?,?,?,?,?,?)',
                              (product_id,p['sku'],p['name'],p['brand'],p['price'],
                               json.dumps(p['approved_claims'],ensure_ascii=False),'[]',stamp))
                    source_note = 'Bảng tham chiếu nhập từ XLSX (nguồn: ' + p['source_class'] + ')'
                    c.execute('''INSERT INTO product_truth_meta(
                        product_id,reference_url,reference_note,reference_status,revision,updated_at
                        ) VALUES(?,?,?,?,?,?)''',
                        (product_id,'',source_note[:800],'unverified',1,stamp))
                    c.execute('''INSERT INTO product_truth_audits(
                        product_id,event,revision,snapshot,created_at
                        ) VALUES(?,?,?,?,?)''',
                        (product_id,'imported',1,json.dumps(p,ensure_ascii=False),stamp))
                    created += 1
                else:
                    product_id = row['id']
                    existing_count += 1
                    current_claims = json.loads(row['claims'] or '[]')
                    if (row['name'] != p['name'] or row['brand'] != p['brand']
                            or row['price'] != p['price']
                            or current_claims != p['approved_claims']):
                        conflicts.append(p['sku'])
                previous = c.execute(
                    'SELECT created_by_import FROM product_import_profiles WHERE product_id=?',
                    (product_id,)).fetchone()
                owned = int(previous['created_by_import']) if previous else int(row is None)
                c.execute('''INSERT INTO product_import_profiles(
                    product_id,video_code,variant,expected_video_description,
                    source_class,owner,notes,import_sha256,imported_at,created_by_import
                    ) VALUES(?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(product_id) DO UPDATE SET
                      video_code=excluded.video_code,variant=excluded.variant,
                      expected_video_description=excluded.expected_video_description,
                      source_class=excluded.source_class,owner=excluded.owner,
                      notes=excluded.notes,import_sha256=excluded.import_sha256,
                      imported_at=excluded.imported_at''',
                    (product_id,p['video_code'],p['variant'],
                     p['expected_video_description'],p['source_class'],p['owner'],
                     p['notes'],digest,stamp,owned))
        return {
            'ok':True, 'sheet':'1. Kich ban goc', 'products_read':len(items),
            'products_created':created, 'matched_existing':existing_count,
            'core_conflicts_not_overwritten':conflicts,
            'warnings':['Thông tin nguồn Giả lập không phải Product Truth đã xác minh',
                        'Không nhập Sheet 2–9, kịch bản lỗi, prediction mô phỏng hay nhãn kiểm định'],
        }
