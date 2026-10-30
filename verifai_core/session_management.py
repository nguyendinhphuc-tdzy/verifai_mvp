"""Local-only session export/reset endpoints for reviewer data.

Exports AI findings, canonical evidence, coverage, product snapshots, human
reviews, annotations and audit history. Raw video/frames are not exported.
Destructive operations require typed confirmation and refuse running jobs.
"""
from __future__ import annotations

import csv
import io
import ipaddress
import json
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel

MAX_ZIP_BYTES = 120 * 1024 * 1024
RESET_PHRASE = 'XOA TAT CA PHIEN'
STORED_VIDEO = re.compile(r'^[0-9a-f]{12}\.(?:mp4|mov|mkv|webm)$')
JOB_ID = re.compile(r'^[0-9a-f]{12}$')


class ResetSessionsIn(BaseModel):
    confirmation: str


def require_local(request: Request) -> None:
    """No network-wide export/deletion when app is accidentally exposed."""
    peer = request.client.host if request.client else ''
    hostname = request.url.hostname or ''
    try:
        peer_ok = ipaddress.ip_address(peer).is_loopback
        host_ok = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        peer_ok = peer == 'localhost'
        host_ok = hostname == 'localhost'
    # Starlette TestClient's built-in in-process scope (no network socket).
    if peer == 'testclient' and hostname == 'testserver':
        peer_ok = host_ok = True
    if not (peer_ok and host_ok):
        raise HTTPException(403, 'Session management is only available on localhost')
    origin = request.headers.get('origin')
    if origin:
        value = urlsplit(origin)
        if value.scheme not in ('http', 'https') or value.hostname != hostname or value.port != request.url.port:
            raise HTTPException(403, 'Cross-origin session management is forbidden')


def _csv_bytes(headers, rows) -> bytes:
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, fieldnames=headers, extrasaction='ignore')
    writer.writeheader()
    writer.writerows(rows)
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def _safe_json(text, default):
    try:
        return json.loads(text or '')
    except (TypeError, ValueError):
        return default


def build_session_archive(db, utc, get_job) -> bytes:
    with db() as c:
        ids = [r['id'] for r in c.execute('SELECT id FROM jobs ORDER BY created_at,id')]
    summary = []
    findings = []
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for job_id in ids:
            # Include failed and unreviewed jobs too, never just completed ones.
            try:
                job = get_job(job_id)
            except HTTPException as e:
                if e.status_code == 404:
                    raise HTTPException(409, 'Sessions changed during export; please retry') from e
                raise
            safe_name = re.sub(r'[^A-Za-z0-9_-]', '_', job_id)[:80]
            details = job.get('details') or {}
            coverage = details.get('coverage') or {}
            vlm = details.get('vlm') or {}
            verification = details.get('verification') or {}
            product = job.get('product') or {}
            flags = job.get('findings') or []
            summary.append({
                'job_id': job_id, 'filename': job.get('filename', ''),
                'sku': product.get('sku', ''), 'product_name': product.get('name', ''),
                'status': job.get('status', ''), 'created_at': job.get('created_at', ''),
                'finished_at': job.get('finished_at', ''),
                'ai_decision': job.get('decision', ''),
                'verification_status': verification.get('status', ''),
                'verification_reason': verification.get('reason', ''),
                'reviewer_decision': job.get('review_decision', ''),
                'reviewer': job.get('reviewer', ''),
                'review_note': job.get('review_note', ''),
                'ocr_coverage': coverage.get('ocr', ''),
                'asr_coverage': coverage.get('asr', ''),
                'vlm_coverage': coverage.get('vlm', ''),
                'vlm_model': vlm.get('model', ''),
                'vlm_calls_succeeded': vlm.get('calls_succeeded', 0),
                'finding_count': len(flags),
                'finding_codes': '; '.join(str(f.get('code', '')) for f in flags),
                'analysis_error': details.get('error', ''),
            })
            for item in flags:
                findings.append({
                    'job_id': job_id, 'filename': job.get('filename', ''),
                    'code': item.get('code', ''), 'severity': item.get('severity', ''),
                    'timestamp': item.get('timestamp', ''),
                    'detail': item.get('detail', ''), 'source': item.get('source', ''),
                    'confidence_uncalibrated': item.get('confidence', ''),
                    'linked_evidence_id': item.get('evidence_id', ''),
                    'flag_review': item.get('flag_review', ''),
                    'reviewer_decision': job.get('review_decision', ''),
                    'review_note': job.get('review_note', ''),
                })
            # Full data: AI observations and verification, evidence, findings,
            # human annotations, audits, review and Product Truth at analysis time.
            archive.writestr(f'sessions/{len(summary):05d}-{safe_name}.json',
                             json.dumps(job, ensure_ascii=False, indent=2, default=str))
            if memory.tell() > MAX_ZIP_BYTES:
                raise HTTPException(413, 'Export exceeds 120 MB; archive jobs separately')
        summary_columns = [
            'job_id','filename','sku','product_name','status','created_at',
            'finished_at','ai_decision','verification_status','verification_reason',
            'reviewer_decision','reviewer','review_note','ocr_coverage','asr_coverage',
            'vlm_coverage','vlm_model','vlm_calls_succeeded','finding_count',
            'finding_codes','analysis_error',
        ]
        finding_columns = [
            'job_id','filename','code','severity','timestamp','detail','source',
            'confidence_uncalibrated','linked_evidence_id','flag_review',
            'reviewer_decision','review_note',
        ]
        archive.writestr('session_summary.csv', _csv_bytes(summary_columns, summary))
        archive.writestr('ai_findings.csv', _csv_bytes(finding_columns, findings))
        archive.writestr('README.txt', (
            'VerifAI full session export. Generated: ' + utc() + '\n'
            + 'session_summary.csv: AI decision, coverage, model, reviewer decision and notes.\n'
            + 'ai_findings.csv: every AI/rule finding, source, timestamp, confidence and flag review.\n'
            + 'sessions/*.json: full job details, verification, canonical evidence, human labels and audits.\n'
            + 'Raw uploaded video and frame image bytes are NOT included.\n'
            + 'This archive contains potentially sensitive review data. Keep it private.\n'
            + 'AI flags are hypotheses for human review, not verified violations.\n'
        ))
    if memory.tell() > MAX_ZIP_BYTES:
        raise HTTPException(413, 'Export exceeds 120 MB; archive jobs separately')
    return memory.getvalue()


def reset_sessions(db, upload: Path, frames: Path) -> dict:
    """Delete job rows under SQLite write lock, then remove only their media."""
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        active = c.execute(
            "SELECT COUNT(*) AS n FROM jobs WHERE status IN ('queued','processing')"
        ).fetchone()['n']
        if active:
            raise HTTPException(409, f'Có {active} phiên đang xử lý. Hãy chờ hoàn tất trước khi xóa.')
        jobs = [dict(r) for r in c.execute('SELECT id,stored_name FROM jobs')]
        for table in ('findings', 'evidence', 'labels', 'audits', 'jobs'):
            c.execute(f'DELETE FROM {table}')
        # Product Truth, cases, source labels, and imported Excel are retained.
    removed_videos = removed_frame_dirs = 0
    cleanup_errors = []
    upload_root = upload.resolve()
    frames_root = frames.resolve()
    for job in jobs:
        stored = str(job.get('stored_name') or '')
        job_id = str(job['id'])
        if STORED_VIDEO.fullmatch(stored) and stored.startswith(job_id + '.'):
            path = upload / stored
            try:
                if not path.is_symlink() and path.resolve().parent == upload_root and path.is_file():
                    path.unlink()
                    removed_videos += 1
            except OSError as e:
                cleanup_errors.append(f'video {job_id}: {type(e).__name__}')
        if JOB_ID.fullmatch(job_id):
            path = frames / job_id
            try:
                if path.is_symlink():
                    cleanup_errors.append(f'frames {job_id}: symlink skipped')
                elif path.resolve().parent == frames_root and path.is_dir():
                    shutil.rmtree(path)
                    removed_frame_dirs += 1
            except OSError as e:
                cleanup_errors.append(f'frames {job_id}: {type(e).__name__}')
    return {
        'ok': True, 'deleted_sessions': len(jobs),
        'removed_uploaded_videos': removed_videos,
        'removed_frame_directories': removed_frame_dirs,
        'cleanup_errors': cleanup_errors,
        'preserved': ['products', 'product_truth_history', 'dataset_cases',
                      'dataset_annotations', 'dataset_imports'],
        'note': 'Session records removed; unmatched or unsafe files remain untouched.',
    }


def install_session_routes(app, db, utc, upload_path, frame_path, get_job):
    @app.get('/api/sessions/export')
    def export_sessions(request: Request):
        require_local(request)
        data = build_session_archive(db, utc, get_job)
        today = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
        return Response(data, media_type='application/zip', headers={
            'Content-Disposition': f'attachment; filename="verifai-all-sessions-{today}.zip"',
            'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
        })

    @app.post('/api/sessions/reset')
    def delete_all_sessions(request: Request, payload: ResetSessionsIn):
        require_local(request)
        if payload.confirmation != RESET_PHRASE:
            raise HTTPException(400, 'Confirmation phrase does not match')
        return reset_sessions(db, upload_path(), frame_path())
