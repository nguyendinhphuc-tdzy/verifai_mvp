"""Read-only, evidence-first export of all stored VerifAI analysis sessions.

This package does not export raw videos or JPEG frame bytes. It carries
reviewer decisions, AI recommendations, OCR/ASR/VLM evidence, findings,
verification and audits, including failed/queued/unreviewed sessions.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from io import BytesIO, StringIO
import json
import re
from typing import Any
import zipfile

from fastapi import HTTPException, Request
from fastapi.responses import Response

MAX_ZIP_BYTES = 120 * 1024 * 1024
SUMMARY_COLUMNS = (
    'job_id', 'filename', 'sku', 'product_name', 'status',
    'created_at', 'finished_at', 'ai_decision', 'ai_reason',
    'verification_status', 'verification_reason', 'reviewer_decision',
    'reviewer', 'review_note', 'ocr_coverage', 'asr_coverage',
    'vlm_coverage', 'vlm_model', 'finding_count', 'finding_codes',
    'analysis_error',
)
FINDING_COLUMNS = (
    'job_id', 'filename', 'code', 'severity', 'timestamp',
    'detail', 'source', 'confidence_uncalibrated',
    'linked_evidence_id', 'flag_review', 'reviewer_decision',
    'review_note', 'rule_id', 'review_priority', 'legal_basis',
)


def _csv_bytes(columns, rows: list[dict[str, Any]]) -> bytes:
    buffer = StringIO(newline='')
    writer = csv.DictWriter(buffer, fieldnames=columns, extrasaction='ignore')
    writer.writeheader()
    for row in rows:
        # Escape spreadsheet formulas in user-supplied video names/OCR/AI text.
        safe = {}
        for name in columns:
            value = row.get(name, '')
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            if isinstance(value, str) and (
                value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r', '\n'))
                or value.startswith(('\t', '\r', '\n'))
            ):
                value = "'" + value
            safe[name] = value
        writer.writerow(safe)
    return ('\ufeff' + buffer.getvalue()).encode('utf-8')


def build_all_sessions_zip(db, get_job, utc):
    """Bounded in-memory archive, no changes to database records."""
    with db() as conn:
        ids = [r['id'] for r in conn.execute('SELECT id FROM jobs ORDER BY created_at,id')]
    summary, issues = [], []
    stream = BytesIO()
    budget = 0
    with zipfile.ZipFile(stream, mode='w', compression=zipfile.ZIP_DEFLATED,
                         compresslevel=6, allowZip64=True) as archive:
        for num, jid in enumerate(ids, start=1):
            try:
                job = get_job(jid)
            except HTTPException as e:
                if e.status_code == 404:
                    raise HTTPException(409, 'Danh sách phiên đã thay đổi khi export. Hãy thử lại.') from e
                raise
            details = job.get('details') or {}
            verification = details.get('verification') or {}
            coverage = verification.get('coverage') or details.get('coverage') or {}
            vlm = details.get('vlm') or {}
            product = job.get('product') or {}
            ai = job.get('ai_recommendation') or details.get('ai_recommendation') or {}
            findings = job.get('findings') or []
            summary.append({
                'job_id':jid, 'filename':job.get('filename',''),
                'sku':product.get('sku',''), 'product_name':product.get('name',''),
                'status':job.get('status',''),
                'created_at':job.get('created_at',''), 'finished_at':job.get('finished_at',''),
                'ai_decision':ai.get('decision',''), 'ai_reason':ai.get('reason',''),
                'verification_status':verification.get('status',''),
                'verification_reason':verification.get('reason',''),
                'reviewer_decision':job.get('review_decision',''),
                'reviewer':job.get('reviewer',''), 'review_note':job.get('review_note',''),
                'ocr_coverage':coverage.get('ocr',''), 'asr_coverage':coverage.get('asr',''),
                'vlm_coverage':coverage.get('vlm',''), 'vlm_model':vlm.get('model',''),
                'finding_count':len(findings),
                'finding_codes':'; '.join(str(f.get('code','')) for f in findings),
                'analysis_error':details.get('error',''),
            })
            for finding in findings:
                issues.append({
                    'job_id':jid, 'filename':job.get('filename',''),
                    'code':finding.get('code',''), 'severity':finding.get('severity',''),
                    'timestamp':finding.get('timestamp',''),
                    'detail':finding.get('detail',''), 'source':finding.get('source',''),
                    'confidence_uncalibrated':finding.get('confidence',''),
                    'linked_evidence_id':finding.get('evidence_id',''),
                    'flag_review':finding.get('flag_review',''),
                    'reviewer_decision':job.get('review_decision',''),
                    'review_note':job.get('review_note',''),
                    'rule_id':(finding.get('rule') or {}).get('rule_id',''),
                    'review_priority':(finding.get('rule') or {}).get('review_priority',''),
                    'legal_basis':(finding.get('rule') or {}).get('legal_basis',''),
                })
            # Names are generated from a number and a sanitized identifier,
            # never from uploaded filenames or other user-supplied paths.
            safe_id = re.sub(r'[^a-zA-Z0-9_-]', '_', str(jid))[:60]
            body = json.dumps(job, ensure_ascii=False, indent=2, default=str).encode('utf-8')
            budget += len(body)
            if budget > MAX_ZIP_BYTES:
                raise HTTPException(413, 'Dữ liệu export vượt 120 MB. Hãy giảm số phiên trước khi export.')
            archive.writestr(f'sessions/{num:05d}-{safe_id}.json', body)
        files = [
            ('session_summary.csv', _csv_bytes(SUMMARY_COLUMNS, summary)),
            ('ai_findings.csv', _csv_bytes(FINDING_COLUMNS, issues)),
            ('README.txt', (
                'VerifAI - export of all stored sessions\n'
                'Timestamp (UTC): ' + utc() + '\n'
                'session_summary.csv: one row per job, including failures and unreviewed videos.\n'
                'ai_findings.csv: every candidate error/rule finding and reviewer status.\n'
                'sessions/*.json: all stored OCR/ASR/VLM evidence, verification, '
                'Product Truth snapshot, AI suggestion, reviewer decision, '
                'labels and audits.\n'
                'Uploaded videos and JPEG frame bytes are NOT included.\n'
                'A review suggestion is not a regulatory compliance certificate.\n'
                'Keep this archive private; it may contain confidential content.\n'
            ).encode('utf-8')),
        ]
        for path, body in files:
            budget += len(body)
            if budget > MAX_ZIP_BYTES:
                raise HTTPException(413, 'Dữ liệu export vượt 120 MB.')
            archive.writestr(path, body)
    if stream.tell() > MAX_ZIP_BYTES:
        raise HTTPException(413, 'File ZIP export vượt 120 MB.')
    return stream.getvalue()


def install_export_routes(app, db, get_job, utc):
    @app.get('/api/sessions/export')
    def export_all_sessions(request: Request):
        # Global local-only middleware already rejects non-loopback hosts.
        payload = build_all_sessions_zip(db, get_job, utc)
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        return Response(payload, media_type='application/zip', headers={
            'Content-Disposition': f'attachment; filename="verifai-all-sessions-{stamp}.zip"',
            'Cache-Control': 'no-store',
            'X-Content-Type-Options': 'nosniff',
        })
