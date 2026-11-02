"""Evaluate the whole VerifAI video dataset and export one session_summary sheet.

Packages the procedure used for the 80-video run on 02/11/2026:

* discovers self-created videos (folders GỐC / LỖI/<category>) and public videos,
  one entry per video code (``VID_LOI22 (1).mp4`` and ``VID_LOI22.mp4`` are the
  same code; duplicates are rejected);
* links each video to a Product Truth SKU (``scripts/dataset_sku_map.json``;
  unlisted self-created videos use SKU rotation and are marked *assumed*;
  unlisted public videos use a NOREF product without Product Truth);
* runs the real pipeline (adaptive OCR, ASR, Gemini, rules, recommendation,
  label suggestion) in N parallel shards, each with its own data directory,
  self-created videos first, public videos short-first;
* RESUMES: completed jobs are skipped, except jobs whose Gemini step failed
  transiently (coverage.vlm == 'error'), which are re-run;
* exports one row per video (latest completed job wins), ordered GOC, LOI, PUB,
  with the 21 session_summary columns plus evaluation columns. Videos without
  a finished job are listed as "chưa chạy" / "chưa chạy xong".

Everything runs on this machine's CPU; the developer database is never used.

    python scripts/evaluate_dataset.py run --self-dir "<VIDEO TỰ TẠO>" \
        --public-dir "<VIDEO CÔNG KHAI>" --work-dir eval_runs/full --sheet results.csv
    python scripts/evaluate_dataset.py export --work-dir eval_runs/full --sheet results.csv
    python scripts/evaluate_dataset.py run ... --only VID_LOI11 --only VID_LOI44 --force
"""
from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.mkv', '.webm'}
CODE_RE = re.compile(r'(VID_(?:GOC|LOI)\d+|PUB\d+)', re.I)
GROUP_NAMES = {'original': 'Video gốc', 'controlled_error': 'Video lỗi', 'public': 'Video công khai'}
SKU_SOURCE_NAMES = {'mapped': 'Theo bảng SKU', 'assumed_rotation': 'Suy đoán (xoay vòng SKU)',
                    'no_product_truth': 'Chưa có Product Truth'}
LABEL_NAMES = {'clean': 'Không lỗi', 'error': 'Có lỗi', 'uncertain': 'Chưa chắc chắn'}
EXTRA_COLUMNS = ('dataset_group', 'error_category', 'sku_source', 'ai_label_suggestion',
                 'ai_error_types', 'finding_details', 'ocr_frames_read', 'decoded_frames',
                 'asr_audio_stream', 'ai_label_check', 'elapsed_seconds')


# -- manifest -----------------------------------------------------------------
def video_code(name: str) -> str | None:
    match = CODE_RE.search(Path(name).stem)
    return match.group(1).upper() if match else None


def order_key(code: str) -> tuple[int, int]:
    kind = 0 if 'GOC' in code else 1 if 'LOI' in code else 2
    return kind, int(re.search(r'(\d+)$', code).group(1))


def _duration(path: Path) -> float:
    try:
        import cv2
        cap = cv2.VideoCapture(str(path))
        seconds = cap.get(cv2.CAP_PROP_FRAME_COUNT) / max(cap.get(cv2.CAP_PROP_FPS) or 0, 1)
        cap.release()
        return round(float(seconds), 1)
    except Exception:
        return 0.0


def build_manifest(self_dir: Path | None, public_dir: Path | None, sku_map: dict,
                   duration=_duration) -> list[dict]:
    files = []
    for base, public in ((self_dir, False), (public_dir, True)):
        if base:
            files += [(p, public) for p in sorted(Path(base).rglob('*'))
                      if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS]
    items, seen = [], {}
    for path, public in files:
        code = video_code(path.name)
        if not code:
            continue
        if code in seen:
            raise SystemExit(f'Trùng mã video {code}: {seen[code]} và {path}')
        seen[code] = path
        group = 'public' if public else 'original' if 'GOC' in code else 'controlled_error'
        if code in sku_map:
            sku, source = sku_map[code], 'mapped'
        elif group == 'public':
            sku, source = 'NOREF', 'no_product_truth'
        else:
            sku, source = f'SKU00{(order_key(code)[1] - 1) % 6 + 1}', 'assumed_rotation'
        items.append({'code': code, 'path': str(path), 'group': group,
                      'category': path.parent.name if group == 'controlled_error' else '',
                      'sku': sku, 'sku_source': source, 'duration': duration(path)})
    return sorted(items, key=lambda i: order_key(i['code']))


def run_priority(item: dict) -> tuple:
    group = {'original': 0, 'controlled_error': 1, 'public': 2}[item['group']]
    return (group, item['duration'] if group == 2 else order_key(item['code'])[1])


# -- resume ---------------------------------------------------------------------
def shard_dirs(work_dir: Path) -> list[Path]:
    return sorted(p for p in work_dir.glob('shard*') if (p / 'verifai.sqlite3').is_file())


def finished_codes(work_dir: Path) -> set[str]:
    """Codes with a completed job whose Gemini step did not fail transiently."""
    done = set()
    for shard in shard_dirs(work_dir):
        conn = sqlite3.connect(f'file:{(shard / "verifai.sqlite3").as_posix()}?mode=ro', uri=True)
        try:
            for name, details in conn.execute("SELECT filename, details FROM jobs WHERE status='completed'"):
                if json.loads(details or '{}').get('coverage', {}).get('vlm') == 'error':
                    continue
                code = video_code(name)
                if code:
                    done.add(code)
        finally:
            conn.close()
    return done


def next_shard_index(work_dir: Path) -> int:
    used = [int(m.group(1)) for p in work_dir.glob('shard*')
            if (m := re.fullmatch(r'shard(\d+)', p.name))]
    return max(used, default=-1) + 1


def run(args) -> None:
    work = Path(args.work_dir).resolve()
    work.mkdir(parents=True, exist_ok=True)
    sku_map = {k: v for k, v in json.loads(Path(args.sku_map).read_text(encoding='utf-8')).items()
               if not k.startswith('_')}
    manifest = build_manifest(Path(args.self_dir) if args.self_dir else None,
                              Path(args.public_dir) if args.public_dir else None, sku_map)
    (work / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding='utf-8')
    wanted = {c.upper() for c in args.only} if args.only else None
    done = set() if args.force else finished_codes(work)
    todo = sorted((i for i in manifest if i['code'] not in done
                   and (wanted is None or i['code'] in wanted)), key=run_priority)
    print(f'{len(manifest)} video, đã xong {len(done & {i["code"] for i in manifest})}, cần chạy {len(todo)}',
          flush=True)
    first = next_shard_index(work)
    procs = []
    for k in range(max(1, min(args.shards, len(todo)))):
        shard = todo[k::args.shards]
        if not shard:
            continue
        name = f'shard{first + k}'
        cmd = [sys.executable, str(ROOT / 'scripts' / 'run_eval_batch.py'), '--data-dir', str(work / name),
               '--out', str(work / f'{name}.json'), '--timeout', str(args.timeout)]
        for item in shard:
            cmd += ['--video', f"{item['path']}={item['sku']}" + (':public' if item['group'] == 'public' else '')]
        env = {**os.environ, 'OMP_NUM_THREADS': str(args.threads), 'PYTHONIOENCODING': 'utf-8'}
        log = open(work / f'{name}.log', 'w', encoding='utf-8')
        procs.append(subprocess.Popen(cmd, cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT))
        print(f'{name}: {len(shard)} video', flush=True)
    codes = [p.wait() for p in procs]
    print('exit codes:', codes, flush=True)
    export(args)


# -- export ---------------------------------------------------------------------
def choose_latest(rows: dict, code: str, row: dict) -> None:
    """Keep one row per video: completed beats unfinished, then newest wins."""
    previous = rows.get(code)
    if previous is None or (row['status'] == 'completed', row['created_at']) >= \
            (previous['status'] == 'completed', previous['created_at']):
        rows[code] = row


def _job_row(job: dict, meta: dict) -> dict:
    details = job.get('details') or {}
    verification = details.get('verification') or {}
    coverage = details.get('coverage') or {}
    ai = job.get('ai_recommendation') or {}
    findings = job.get('findings') or []
    suggestion = job.get('label_suggestion') or {}
    quality = details.get('perception_quality') or {}
    adaptive = (quality.get('ocr') or {}).get('adaptive') or {}
    product = job.get('product') or {}
    vlm = details.get('vlm') or {}
    return {
        'job_id': job['id'], 'filename': job['filename'], 'sku': product.get('sku', ''),
        'product_name': product.get('name', ''), 'status': job['status'],
        'created_at': job['created_at'], 'finished_at': job.get('finished_at') or '',
        'ai_decision': ai.get('decision', ''), 'ai_reason': ai.get('reason', ''),
        'verification_status': verification.get('status', ''),
        'verification_reason': verification.get('reason', ''),
        'reviewer_decision': job.get('review_decision') or '', 'reviewer': job.get('reviewer') or '',
        'review_note': job.get('review_note') or '',
        'ocr_coverage': (verification.get('coverage') or coverage).get('ocr', ''),
        'asr_coverage': coverage.get('asr', ''), 'vlm_coverage': coverage.get('vlm', ''),
        'vlm_model': vlm.get('model', ''), 'finding_count': len(findings),
        'finding_codes': '; '.join(str(f.get('code', '')) for f in findings),
        'analysis_error': details.get('error', '') or '; '.join(vlm.get('errors') or []),
        'dataset_group': GROUP_NAMES.get(meta.get('group'), ''),
        'error_category': meta.get('category', ''),
        'sku_source': SKU_SOURCE_NAMES.get(meta.get('sku_source'), ''),
        'ai_label_suggestion': LABEL_NAMES.get(suggestion.get('label'), ''),
        'ai_error_types': '; '.join(suggestion.get('error_types') or []),
        'finding_details': ' | '.join(f"{f['code']}({f['severity']}) {str(f['detail'])[:120]}"
                                     for f in findings if f['code'] != 'VIS-SCREEN')[:1500],
        'ocr_frames_read': adaptive.get('ocr_frames', ''), 'decoded_frames': adaptive.get('decoded_frames', ''),
        'asr_audio_stream': {True: 'Có', False: 'Không có âm thanh'}.get((quality.get('asr') or {}).get('audio_stream'), ''),
        'ai_label_check': (details.get('ai_label') or {}).get('status', ''),
        'elapsed_seconds': details.get('elapsed_seconds', ''),
    }


def placeholder_row(meta: dict, status: str) -> dict:
    return {'filename': Path(meta['path']).name, 'sku': meta['sku'], 'status': status,
            'dataset_group': GROUP_NAMES[meta['group']], 'error_category': meta.get('category', ''),
            'sku_source': SKU_SOURCE_NAMES[meta['sku_source']]}


def export(args) -> dict:
    work = Path(args.work_dir).resolve()
    manifest = {m['code']: m for m in json.loads((work / 'manifest.json').read_text(encoding='utf-8'))}
    os.environ['VERIFAI_SKIP_DOTENV'] = '1'
    sys.path.insert(0, str(ROOT))
    import backend
    from verifai_core.session_export import SUMMARY_COLUMNS
    rows: dict[str, dict] = {}
    for shard in shard_dirs(work):
        backend.DB = shard / 'verifai.sqlite3'
        with backend.db() as conn:
            ids = [r['id'] for r in conn.execute('SELECT id FROM jobs ORDER BY created_at')]
        for jid in ids:
            job = backend.get_job(jid)
            code = video_code(job['filename'])
            if code in manifest:
                choose_latest(rows, code, _job_row(job, manifest[code]))
    for code, row in list(rows.items()):
        if row['status'] != 'completed':
            rows[code] = placeholder_row(manifest[code], 'chưa chạy xong (dừng giữa chừng)')
    for code in set(manifest) - set(rows):
        rows[code] = placeholder_row(manifest[code], 'chưa chạy')
    sheet = Path(args.sheet)
    sheet.parent.mkdir(parents=True, exist_ok=True)
    with sheet.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(SUMMARY_COLUMNS) + list(EXTRA_COLUMNS))
        writer.writeheader()
        for code in sorted(rows, key=order_key):
            writer.writerow(rows[code])
    completed = sum(r['status'] == 'completed' for r in rows.values())
    summary = {'videos': len(rows), 'completed': completed, 'sheet': str(sheet)}
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('run', 'export'):
        p = sub.add_parser(name)
        p.add_argument('--work-dir', required=True, help='shard data directories and manifest')
        p.add_argument('--sheet', required=True, help='output CSV (UTF-8 with BOM, opens in Excel)')
        if name == 'run':
            p.add_argument('--self-dir', help='folder "VIDEO TỰ TẠO" (GỐC, LỖI/<category>)')
            p.add_argument('--public-dir', help='folder "VIDEO CÔNG KHAI"')
            p.add_argument('--sku-map', default=str(ROOT / 'scripts' / 'dataset_sku_map.json'))
            p.add_argument('--shards', type=int, default=3)
            p.add_argument('--threads', type=int, default=4, help='OMP threads per shard')
            p.add_argument('--timeout', type=int, default=3600, help='seconds to wait per video')
            p.add_argument('--only', action='append', help='run only these video codes')
            p.add_argument('--force', action='store_true', help='re-run even if already completed')
    args = parser.parse_args(argv)
    if args.command == 'run':
        if not (args.self_dir or args.public_dir):
            parser.error('cần --self-dir và/hoặc --public-dir')
        run(args)
    else:
        export(args)


if __name__ == '__main__':
    main()
