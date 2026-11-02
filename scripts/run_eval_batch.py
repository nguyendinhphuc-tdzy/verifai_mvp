"""Run real videos through the full VerifAI pipeline in an ISOLATED data dir.

Uses the real API in-process (real OCR/ASR, and Gemini only if VLM_ENABLED=1
with a key). The developer database is never touched: VERIFAI_DATA points to
--data-dir, seeded with Product Truth from deploy/seed.sql.

    python scripts/run_eval_batch.py --data-dir <tmp> --out report.json \
        --video "path/VID_LOI01.mp4=SKU001" --video "path/PUB002.mov=SKU008:public"

Each --video is PATH=SKU[:public]. ":public" uploads with rights
public_review_only and ai_generated=unknown; otherwise self_created / yes.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--video', action='append', required=True)
    parser.add_argument('--timeout', type=int, default=1800)
    args = parser.parse_args()
    os.environ['VERIFAI_DATA'] = str(Path(args.data_dir).resolve())
    os.environ.setdefault('VERIFAI_SEED_DB', str(ROOT / 'deploy' / 'seed.sql'))
    sys.path.insert(0, str(ROOT))
    from fastapi.testclient import TestClient
    import backend
    client = TestClient(backend.app)
    skus = {p['sku']: p['id'] for p in client.get('/api/products').json()}
    report = {'health': client.get('/api/health').json(), 'videos': []}
    for spec in args.video:
        path, _, target = spec.rpartition('=')
        sku, _, kind = target.partition(':')
        public = kind == 'public'
        started = time.monotonic()
        with open(path, 'rb') as stream:
            response = client.post('/api/jobs', data={
                'product_id': skus[sku], 'rights': 'public_review_only' if public else 'self_created',
                'ai_generated': 'unknown' if public else 'yes'},
                files={'file': (Path(path).name, stream, 'video/mp4')})
        response.raise_for_status()
        jid = response.json()['id']
        while True:
            job = client.get('/api/jobs/' + jid).json()
            if job['status'] in ('completed', 'failed') or time.monotonic() - started > args.timeout:
                break
            time.sleep(2)
        details = job.get('details') or {}
        row = {
            'video': Path(path).name, 'group': Path(path).parent.name, 'sku': sku, 'job_id': jid,
            'status': job['status'], 'decision': job.get('decision'),
            'recommendation_reason': (job.get('ai_recommendation') or {}).get('reason'),
            'label_suggestion': job.get('label_suggestion'),
            'findings': [{'code': f['code'], 'severity': f['severity'], 'source': f['source'],
                          'at': f['timestamp'], 'detail': f['detail'][:200]} for f in job.get('findings', [])],
            'coverage': details.get('coverage'), 'ai_label': details.get('ai_label'),
            'asr_audio_stream': ((details.get('perception_quality') or {}).get('asr') or {}).get('audio_stream'),
            'ocr_adaptive': ((details.get('perception_quality') or {}).get('ocr') or {}).get('adaptive'),
            'seconds': round(time.monotonic() - started, 1),
            'error': details.get('error'),
        }
        report['videos'].append(row)
        print(json.dumps({k: row[k] for k in ('video', 'status', 'decision', 'seconds')}
                         | {'codes': sorted({f['code'] + ':' + f['severity'] for f in row['findings']}),
                            'label': (row['label_suggestion'] or {}).get('label')},
                         ensure_ascii=False), flush=True)
        Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
