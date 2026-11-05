"""Compare exhaustive (all) vs adaptive OCR on real videos with real PaddleOCR.

Local only: videos are read from disk and never uploaded. Per video it reports:
* time and OCR calls for each mode,
* recall of the texts found by the exhaustive reference, both for ALL strings
  and for STABLE strings (seen on >= --stable-frames frames). Single-frame
  readings on moving footage are mostly OCR jitter, so stable recall is the
  meaningful acceptance number; both are reported,
* on-screen duration of every stable text run (measured basis for
  OCR_MAX_GAP_SECONDS).

The exhaustive per-frame OCR is cached (--cache-dir). With --simulate, adaptive
mode replays OCR from that cache (no full-resolution re-read), so parameters
can be tuned in seconds; its time is then an ESTIMATE = calls x measured
seconds per exhaustive call.

    python scripts/compare_ocr_modes.py --video a.mp4 --cache-dir ocr_cache --output report.json
    python scripts/compare_ocr_modes.py --video a.mp4 --cache-dir ocr_cache --simulate --output sim.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from verifai_core.adaptive_ocr import (AdaptiveOCRConfig, AdaptiveOCRScanner,  # noqa: E402
                                       _norm, same_text)
from verifai_core.video_ocr import iter_all_video_frames  # noqa: E402

FLICKER_FRAMES = 2  # a reading may drop out for <=2 frames inside one run


def _texts(results, min_score, min_chars):
    return {_norm(t) for t, s in results
            if (s is None or s >= min_score) and len(_norm(t)) >= min_chars}


def _match(text, pool):
    return any(same_text((text,), (other,)) for other in pool)


def exhaustive(path, ocr, cache_dir):
    """Per-frame [(text, score)] for every decoded frame, cached by file hash."""
    digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()[:16]
    cache = Path(cache_dir) / f'{digest}.json' if cache_dir else None
    if cache and cache.is_file():
        data = json.loads(cache.read_text(encoding='utf-8'))
        return data['frames'], data['seconds']
    if ocr is None:
        raise SystemExit(f'No cache for {path}; run without --simulate first')
    frames, started = [], time.perf_counter()
    for frame in iter_all_video_frames(path):
        results, status = ocr.extract(frame['image'])
        frames.append([[t, s] for t, s in results] if status == 'ok' else [])
    seconds = time.perf_counter() - started
    if cache:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps({'video': str(path), 'seconds': seconds, 'frames': frames},
                                    ensure_ascii=False), encoding='utf-8')
    return frames, seconds


def text_runs(per_frame_texts, fps):
    distinct = []
    for texts in per_frame_texts:
        for text in texts:
            if not _match(text, distinct):
                distinct.append(text)
    runs = []
    for text in distinct:
        present = [any(same_text((text,), (t,)) for t in texts) for texts in per_frame_texts]
        start, gap, last = None, 0, 0
        for i, hit in enumerate(present + [False] * (FLICKER_FRAMES + 1)):
            if hit:
                start = i if start is None else start
                gap, last = 0, i
            elif start is not None:
                gap += 1
                if gap > FLICKER_FRAMES:
                    runs.append({'text': text, 'start_frame': start, 'end_frame': last,
                                 'frames_seen': sum(present[start:last + 1]),
                                 'seconds': round((last - start + 1) / fps, 3)})
                    start, gap = None, 0
    return distinct, runs


def run_adaptive(path, ocr_fn, fps, config):
    scanner = AdaptiveOCRScanner(ocr_fn, fps, config)
    started = time.perf_counter()
    found = []
    for event in scanner.scan(iter_all_video_frames(path, keep_full=config.fullres_recheck)):
        if event.status == 'ok':
            found.append(event.results)
    return found, time.perf_counter() - started, scanner.stats.snapshot(config, fps)


class CachedOCR:
    """Replays exhaustive results; frames are identified by their image object."""
    def __init__(self, frames):
        self.frames = frames
        self.index = {}

    def tag(self, iterator):
        for item in iterator:
            self.index[id(item['image'])] = item['source_frame_index']
            yield item

    def __call__(self, image):
        return [tuple(x) for x in self.frames[self.index[id(image)]]], 'ok'


def compare(path, ocr, args, config):
    import cv2
    cap = cv2.VideoCapture(str(path))
    fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
    cap.release()
    frames, all_seconds = exhaustive(path, ocr, args.cache_dir)
    per_frame = [_texts(r, args.min_score, args.min_chars) for r in frames]
    distinct, runs = text_runs(per_frame, fps)
    stable = [t for t in distinct
              if max((r['frames_seen'] for r in runs if r['text'] == t), default=0) >= args.stable_frames]
    if args.simulate:
        cached = CachedOCR(frames)
        sim_config = AdaptiveOCRConfig(**{**config.__dict__, 'fullres_recheck': False})
        scanner = AdaptiveOCRScanner(cached, fps, sim_config)
        found_results = [e.results for e in scanner.scan(cached.tag(iter_all_video_frames(path)))
                         if e.status == 'ok']
        stats = scanner.stats.snapshot(sim_config, fps)
        per_call = all_seconds / max(1, len(frames))
        adaptive_seconds = stats['ocr_frames'] * per_call
        timing = 'estimated_from_exhaustive_seconds_per_call'
    else:
        from verifai_core.perception import OCRService  # noqa: F401
        found_results, adaptive_seconds, stats = run_adaptive(path, ocr.extract, fps, config)
        timing = 'measured'
    found = set().union(*(_texts(r, args.min_score, args.min_chars) for r in found_results)) \
        if found_results else set()
    missed = [t for t in distinct if not _match(t, found)]
    missed_stable = [t for t in stable if not _match(t, found)]
    stable_runs = sorted(r['seconds'] for r in runs if r['text'] in stable)
    calls = stats['ocr_frames'] + stats['fullres_calls']
    return {
        'video': Path(path).name, 'fps': round(fps, 3), 'frames': len(frames),
        'all': {'seconds': round(all_seconds, 1), 'ocr_calls': len(frames),
                'distinct_texts': len(distinct), 'stable_texts': len(stable)},
        'adaptive': {'seconds': round(adaptive_seconds, 1), 'timing': timing,
                     'ocr_calls': calls, 'stats': stats},
        'call_reduction': round(len(frames) / calls, 2) if calls else None,
        'speedup': round(all_seconds / adaptive_seconds, 2) if adaptive_seconds else None,
        'recall_all_texts': round(1 - len(missed) / len(distinct), 4) if distinct else None,
        'recall_stable_texts': round(1 - len(missed_stable) / len(stable), 4) if stable else None,
        'missed_stable': [{'text': t, 'runs': [r for r in runs if r['text'] == t]} for t in missed_stable],
        'missed_single_or_flicker': len(missed) - len(missed_stable),
        'stable_run_seconds': {
            'count': len(stable_runs),
            'min': stable_runs[0] if stable_runs else None,
            'p10': stable_runs[len(stable_runs) // 10] if stable_runs else None,
            'median': statistics.median(stable_runs) if stable_runs else None,
            'under_0_5s': sum(d < 0.5 for d in stable_runs),
            'under_1s': sum(d < 1.0 for d in stable_runs),
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', action='append', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--cache-dir', default='')
    parser.add_argument('--simulate', action='store_true')
    parser.add_argument('--max-gap-seconds', type=float, default=0.5)
    parser.add_argument('--min-gap-seconds', type=float, default=0.25)
    parser.add_argument('--change-threshold', type=float, default=12.0)
    parser.add_argument('--signature-min-score', type=float, default=0.9)
    parser.add_argument('--min-score', type=float, default=0.8, help='text counted for recall')
    parser.add_argument('--min-chars', type=int, default=3)
    parser.add_argument('--stable-frames', type=int, default=3)
    args = parser.parse_args()
    config = AdaptiveOCRConfig(max_gap_seconds=args.max_gap_seconds,
                               min_gap_seconds=args.min_gap_seconds,
                               change_threshold=args.change_threshold,
                               signature_min_score=args.signature_min_score,
                               signature_min_chars=args.min_chars)
    ocr, load = None, None
    needs_ocr = not args.simulate or any(
        not (Path(args.cache_dir or '.') / f'{hashlib.sha256(Path(v).read_bytes()).hexdigest()[:16]}.json').is_file()
        for v in args.video)
    if needs_ocr:
        import numpy as np
        from verifai_core.perception import OCRService
        ocr, started = OCRService(), time.perf_counter()
        ocr.extract(np.full((64, 64, 3), 255, dtype=np.uint8))  # load models outside timings
        load = round(time.perf_counter() - started, 1)
    report = {'config': vars(args), 'model_load_seconds': load, 'videos': []}
    for video in args.video:
        result = compare(video, ocr, args, config)
        report['videos'].append(result)
        print(json.dumps({k: result[k] for k in ('video', 'frames', 'call_reduction', 'speedup',
                                                  'recall_all_texts', 'recall_stable_texts',
                                                  'stable_run_seconds')}, ensure_ascii=True), flush=True)
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    total_all = sum(v['all']['seconds'] for v in report['videos'])
    total_adaptive = sum(v['adaptive']['seconds'] for v in report['videos'])
    report['summary'] = {'videos': len(report['videos']),
                         'all_seconds': round(total_all, 1), 'adaptive_seconds': round(total_adaptive, 1),
                         'speedup': round(total_all / total_adaptive, 2) if total_adaptive else None,
                         'missed_stable_total': sum(len(v['missed_stable']) for v in report['videos'])}
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report['summary']), flush=True)


if __name__ == '__main__':
    main()
