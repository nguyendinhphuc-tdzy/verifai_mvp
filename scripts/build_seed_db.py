"""Build a product-only seed database for cloud demo hosting.

Cloud free tiers (e.g. Hugging Face Spaces) have no persistent disk, so the
app copies this seed into VERIFAI_DATA when no database exists. Only Product
Truth tables are kept; jobs, evidence, findings, labels, audits and dataset
rows are removed. The source database is opened read-only.

Writes deploy/seed.sql (text, so Hugging Face accepts it without LFS):

    python scripts/build_seed_db.py --out deploy/seed.sqlite3
    python scripts/build_seed_db.py --out deploy/seed.sqlite3 \
        --approve-test-reference "Bộ chuẩn kiểm thử đồ án, PO xác nhận 02/11/2026"
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

KEEP = {'products', 'product_truth_meta', 'product_truth_audits', 'product_import_profiles'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='data/verifai.sqlite3')
    parser.add_argument('--out', required=True)
    parser.add_argument('--approve-test-reference', default='',
                        help='mark every product test_reference_approved with this note')
    args = parser.parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    src = sqlite3.connect(f'file:{Path(args.source).resolve().as_posix()}?mode=ro', uri=True)
    dst = sqlite3.connect(out)
    src.backup(dst)
    src.close()
    tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        if table not in KEEP and table != 'sqlite_sequence':
            dst.execute(f'DELETE FROM "{table}"')
    now = datetime.now(timezone.utc).isoformat()
    # Every product needs a meta row (legacy products may lack one).
    for (pid,) in dst.execute('SELECT id FROM products').fetchall():
        dst.execute("""INSERT OR IGNORE INTO product_truth_meta(product_id,reference_url,reference_note,
                       reference_status,revision,updated_at) VALUES(?,?,?,?,?,?)""",
                    (pid, '', '', 'unverified', 1, now))
    if args.approve_test_reference:
        dst.execute("""UPDATE product_truth_meta SET reference_status='test_reference_approved',
                       reference_note=CASE WHEN reference_note='' THEN ? ELSE reference_note END,
                       updated_at=?""", (args.approve_test_reference[:800], now))
    # The seed may be published (public demo): drop personal names.
    dst.execute("UPDATE product_import_profiles SET owner=''")
    dst.commit()
    dst.execute('VACUUM')
    counts = {t: dst.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in sorted(KEEP)}
    statuses = dst.execute('SELECT reference_status,count(*) FROM product_truth_meta GROUP BY 1').fetchall()
    sql = out.with_suffix('.sql')
    sql.write_text('\n'.join(dst.iterdump()) + '\n', encoding='utf-8')
    dst.close()
    out.unlink()
    print({'out': str(sql), 'rows': counts, 'reference_status': dict(statuses)})


if __name__ == '__main__':
    main()
