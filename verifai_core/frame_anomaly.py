"""RULE07: deterministic frame anomalies (04/11/2026).

* Mirror (VIS-04): the reference brand or the AI disclosure becomes readable
  only after flipping the frame horizontally -> the video content is mirrored
  (VID_LOI30, VID_LOI32 from 6 s). A normal frame flipped yields gibberish.
* Pixelation (VIS-05): sharpness (Laplacian variance) of the picture area
  collapses below 10 % of the video's own early median, together with a
  regular block period >= 8 px in the column gradients, on >= 2 consecutive
  samples (VID_LOI35 from 5.0 s, VID_LOI37 from 6.0 s).

Validated on 84 videos (6 originals, 44 + 4 edited error clips, 30 public):
mirror flagged exactly LOI30/LOI32, pixelation exactly LOI35/LOI37.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from verifai_core.ai_label import find_ai_disclosure

FRAME_ANOMALY_VERSION = 'frame-anomaly-1.0'
PICTURE_FRACTION = 0.68      # skip the bottom info band (overlay stays sharp/unflipped)
SHARPNESS_RATIO = 0.10
MIN_BLOCK_PERIOD = 8
MIN_PERIOD_STRENGTH = 0.55
MIN_RUN = 2


def _fold(text: str) -> str:
    return ''.join(ch for ch in str(text).casefold() if ch.isalnum())


def _video_info(cap) -> tuple[float, int]:
    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    return (fps if fps > 0 else 25.0), count


def detect_mirror(path: Path | str, ocr: Callable, brand: str, samples: int = 10,
                  min_score: float = 0.85,
                  known_text_at: Callable[[float], list[str]] | None = None) -> dict:
    """OCR the horizontally flipped frame; hits = frames whose brand/AI label reads only when flipped.

    ``known_text_at(t)`` returns text the full-video OCR scan already read
    (score >= 0.85) on the original frame shown at ``t``. It replaces the
    second OCR of the original frame, and a sample whose original frame
    already shows both the brand and the AI label is skipped: neither can
    then read *only* when flipped, so it can never become a hit.
    """
    target = _fold(brand) if brand and len(_fold(brand)) >= 5 else ''
    cap = cv2.VideoCapture(str(path))
    hits = []
    skipped = 0
    try:
        fps, count = _video_info(cap)
        duration = count / fps if count else 0
        for k in range(samples if duration > 0 else 0):
            t = duration * (0.05 + 0.9 * k / max(1, samples - 1))
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, img = cap.read()
            if not ok or img is None:
                continue
            known = known_text_at(t) if known_text_at is not None else None
            if (known is not None and (not target or any(target in _fold(x) for x in known))
                    and find_ai_disclosure(known)):
                skipped += 1
                continue
            h, w = img.shape[:2]
            scale = 800 / max(h, w)
            flipped = cv2.flip(img, 1)
            if scale < 1:
                flipped = cv2.resize(flipped, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            results, status = ocr(flipped)
            if status != 'ok':
                continue
            texts = [text for text, score in results if score is None or score >= min_score]
            readable = [x for x in texts if target and target in _fold(x)]
            disclosure = find_ai_disclosure(texts)
            if not (readable or disclosure):
                continue
            # Only a mirror if the same text does NOT read on the original frame.
            if known is not None:
                plain_texts = known
            else:
                original = img if scale >= 1 else cv2.resize(img, (int(w * scale), int(h * scale)),
                                                             interpolation=cv2.INTER_AREA)
                plain, plain_status = ocr(original)
                plain_texts = [text for text, score in plain if score is None or score >= min_score] \
                    if plain_status == 'ok' else []
            if readable and any(target in _fold(x) for x in plain_texts):
                readable = []
            if disclosure and find_ai_disclosure(plain_texts):
                disclosure = None
            if readable or disclosure:
                hits.append({'at': round(t, 2), 'texts': (readable + ([disclosure] if disclosure else []))[:3]})
    finally:
        cap.release()
    return {'flagged': len(hits) >= MIN_RUN, 'hits': hits,
            'first_at': hits[0]['at'] if hits else None, 'brand_checked': bool(target),
            'reused_scan_text': known_text_at is not None, 'samples_skipped': skipped}


def _sharpness_and_period(img) -> tuple[float, int, float]:
    h, w = img.shape[:2]
    if w > 720:
        img = cv2.resize(img, (720, int(h * 720 / w)), interpolation=cv2.INTER_AREA)
        h, w = img.shape[:2]
    gray = cv2.cvtColor(img[: int(h * PICTURE_FRACTION)], cv2.COLOR_BGR2GRAY)
    sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    profile = np.abs(np.diff(gray.astype(np.float32), axis=1)).mean(axis=0)
    profile = profile - profile.mean()
    ac = np.correlate(profile, profile, 'full')[len(profile) - 1:]
    ac = ac / (ac[0] + 1e-9)
    lag = int(np.argmax(ac[6:40]) + 6) if len(ac) > 40 else 0
    return sharpness, lag, float(ac[lag]) if lag else 0.0


def detect_pixelation(path: Path | str, per_second: float = 2.0, max_samples: int = 240) -> dict:
    cap = cv2.VideoCapture(str(path))
    series = []
    try:
        fps, count = _video_info(cap)
        step = max(1, int(round(fps / per_second)))
        for index in range(0, count, step):
            if len(series) >= max_samples:
                break
            cap.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, img = cap.read()
            if not ok or img is None:
                break
            series.append((round(index / fps, 2),) + _sharpness_and_period(img))
    finally:
        cap.release()
    if len(series) < 4:
        return {'flagged': False, 'first_at': None, 'samples': len(series)}
    sharp = np.array([s[1] for s in series])
    reference = float(np.median(sharp[: max(3, len(sharp) * 2 // 5)]))
    run, best, first, start = 0, 0, None, None
    for t, value, lag, strength in series:
        bad = (reference > 0 and value / reference < SHARPNESS_RATIO
               and lag >= MIN_BLOCK_PERIOD and strength >= MIN_PERIOD_STRENGTH)
        if bad:
            run += 1
            start = t if run == 1 else start
            if run >= MIN_RUN and first is None:
                first = start
        else:
            run = 0
        best = max(best, run)
    return {'flagged': first is not None, 'first_at': first, 'longest_run': best,
            'reference_sharpness': round(reference, 1), 'samples': len(series)}
