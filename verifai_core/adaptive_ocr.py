"""Adaptive full-coverage OCR (Sprint 1, S1-2; approved by the PO 02/11/2026).

Every decoded frame is CHECKED, but OCR only runs where it can add information:

* Pass 0 - change check: each frame is compared with the last OCR'd frame on a
  small grayscale thumbnail, tile by tile, so a local change (e.g. a price)
  is not averaged away by a static background. Cheap; no OCR.
* Pass 1 - grid + change trigger: OCR at least every ``max_gap_seconds`` and
  when pass 0 sees a change (rate-limited by ``min_gap_seconds`` so constant
  camera motion cannot degrade into OCR on every frame).
* Pass 2 - boundary search: when two consecutive OCR results read different
  text, the frames in between are bisected to find where the text changed.
* Pass 3 - full-resolution re-read: the first time a new text state contains
  digits (prices, volumes) or low-confidence lines, the original-resolution
  frame is OCR'd again and the better reading is kept.

Frames that are not OCR'd INHERIT the reading of the OCR'd frame that covers
them; each event reports how many frames it covers and until when, so
``ocr_frames + inherited_frames == decoded_frames`` is auditable.

Known limitation: text visible for less than ``max_gap_seconds`` is found only
when pass 0 detects the visual change. A tiny overlay flashing for 1-2 frames
can still be missed. Use OCR_SCAN_MODE=all as the exhaustive reference.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Callable, Iterable, Iterator

import cv2
import numpy as np

ADAPTIVE_OCR_VERSION = 'adaptive-ocr-1.0'
_THUMB_WIDTH = 160
_GRID = 8
_FULLRES_SCORE_BELOW = 0.85

OCRFunction = Callable[[np.ndarray], 'tuple[list[tuple[str, float]], str]']


@dataclass(frozen=True)
class AdaptiveOCRConfig:
    max_gap_seconds: float = 0.5
    min_gap_seconds: float = 0.25
    change_threshold: float = 12.0
    fullres_recheck: bool = True
    # Text-state comparison ignores low-confidence lines and tiny fragments:
    # on moving/AI-generated footage they are per-frame OCR jitter, and
    # treating them as text changes triggers useless boundary searches.
    signature_min_score: float = 0.9
    signature_min_chars: int = 3

    def __post_init__(self):
        if not 0 < self.max_gap_seconds <= 10:
            raise ValueError('OCR_MAX_GAP_SECONDS phải trong khoảng (0, 10]')
        if not 0 <= self.min_gap_seconds <= self.max_gap_seconds:
            raise ValueError('OCR_MIN_GAP_SECONDS phải trong khoảng [0, OCR_MAX_GAP_SECONDS]')
        if not 0 < self.change_threshold <= 255:
            raise ValueError('OCR_CHANGE_THRESHOLD phải trong khoảng (0, 255]')


@dataclass
class OCREvent:
    """One OCR'd frame and the frames whose reading it stands for."""
    frame: dict
    results: list
    status: str
    reason: str               # first | grid | change | boundary | last
    inherited_frames: int = 0
    visible_until: float = 0.0
    fullres_used: bool = False


@dataclass
class AdaptiveStats:
    decoded_frames: int = 0
    ocr_frames: int = 0
    inherited_frames: int = 0
    by_reason: dict = field(default_factory=dict)
    boundary_searches: int = 0
    fullres_calls: int = 0
    fullres_improved: int = 0

    def snapshot(self, config: AdaptiveOCRConfig, fps: float) -> dict:
        return {
            'version': ADAPTIVE_OCR_VERSION,
            'decoded_frames': self.decoded_frames,
            'ocr_frames': self.ocr_frames,
            'inherited_frames': self.inherited_frames,
            'all_frames_accounted': self.ocr_frames + self.inherited_frames == self.decoded_frames,
            'ocr_ratio': round(self.ocr_frames / self.decoded_frames, 4) if self.decoded_frames else None,
            'by_reason': dict(self.by_reason),
            'boundary_searches': self.boundary_searches,
            'fullres_calls': self.fullres_calls,
            'fullres_improved': self.fullres_improved,
            'max_gap_seconds': config.max_gap_seconds,
            'min_gap_seconds': config.min_gap_seconds,
            'max_gap_frames': _frames(config.max_gap_seconds, fps),
            'change_threshold': config.change_threshold,
        }


def _frames(seconds: float, fps: float) -> int:
    return max(1, round(seconds * fps))


def thumbnail(image: np.ndarray) -> np.ndarray:
    gray = image if image.ndim == 2 else cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    target = (_THUMB_WIDTH, max(_GRID, round(height * _THUMB_WIDTH / max(1, width))))
    return cv2.resize(gray, target, interpolation=cv2.INTER_AREA).astype(np.int16)


def tile_change(a: np.ndarray, b: np.ndarray) -> float:
    """Largest per-tile mean absolute difference (0-255) between thumbnails."""
    if a.shape != b.shape:
        return 255.0
    diff = np.abs(a - b)
    h, w = diff.shape
    worst = 0.0
    for rows in np.array_split(np.arange(h), _GRID):
        for cols in np.array_split(np.arange(w), _GRID):
            if len(rows) and len(cols):
                worst = max(worst, float(diff[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1].mean()))
    return worst


def _norm(text: str) -> str:
    text = unicodedata.normalize('NFKC', str(text)).casefold()
    return re.sub(r'\s+', '', text)


def signature(results: list, status: str, min_score: float = 0.8,
              min_chars: int = 3) -> tuple[str, ...]:
    if status != 'ok':
        return ('<ocr-error>',)
    return tuple(sorted({_norm(t) for t, s in results
                         if (s is None or s >= min_score) and len(_norm(t)) >= min_chars}))


def same_text(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """Tolerate OCR jitter: every line must have a close match on the other side."""
    if a == b:
        return True
    if not a or not b:
        return False

    def close(s, t):
        # Numbers (prices, volumes) must match exactly: 149.000 vs 199.000 is
        # a different text state even though the strings are 91% similar.
        return (re.sub(r'\D', '', s) == re.sub(r'\D', '', t)
                and SequenceMatcher(None, s, t).ratio() >= 0.85)

    def covered(x, y):
        return all(any(close(s, t) for t in y) for s in x)
    return covered(a, b) and covered(b, a)


def _needs_fullres(results: list) -> bool:
    return any(any(ch.isdigit() for ch in str(t)) or (s is not None and s < _FULLRES_SCORE_BELOW)
               for t, s in results)


def _mean_score(results: list) -> float:
    scores = [float(s) for _, s in results if s is not None]
    return sum(scores) / len(scores) if scores else 0.0


class AdaptiveOCRScanner:
    def __init__(self, ocr: OCRFunction, fps: float, config: AdaptiveOCRConfig | None = None,
                 progress: Callable[[int, int], None] | None = None):
        if not fps or fps <= 0:
            raise ValueError('fps must be positive')
        self.ocr = ocr
        self.fps = float(fps)
        self.config = config or AdaptiveOCRConfig()
        self.progress = progress
        self.stats = AdaptiveStats()
        self._fullres_seen: list[tuple[str, ...]] = []

    def _signature(self, event: OCREvent) -> tuple[str, ...]:
        return signature(event.results, event.status,
                         self.config.signature_min_score, self.config.signature_min_chars)

    # -- OCR with pass 3 ---------------------------------------------------
    def _read(self, frame: dict, reason: str) -> OCREvent:
        results, status = self.ocr(frame['image'])
        self.stats.ocr_frames += 1
        self.stats.by_reason[reason] = self.stats.by_reason.get(reason, 0) + 1
        event = OCREvent(frame, list(results), status, reason, visible_until=frame['at'])
        full = frame.get('full')
        if (self.config.fullres_recheck and status == 'ok' and full is not None
                and _needs_fullres(results)):
            sig = self._signature(event)
            if not any(same_text(sig, seen) for seen in self._fullres_seen):
                self._fullres_seen.append(sig)
                self.stats.fullres_calls += 1
                full_results, full_status = self.ocr(full)
                if (full_status == 'ok' and full_results
                        and _mean_score(full_results) > _mean_score(results)):
                    event.results = list(full_results)
                    event.fullres_used = True
                    self.stats.fullres_improved += 1
        return event

    # -- pass 2 -----------------------------------------------------------
    def _resolve(self, left: OCREvent, between: list[dict], right: OCREvent) -> list[OCREvent]:
        """Assign `between` frames to OCR'd owners; return newly OCR'd events in order."""
        points = {0: left, len(between) + 1: right}
        sig = self._signature
        if between and not same_text(sig(left), sig(right)):
            self.stats.boundary_searches += 1
            lo, hi = 0, len(between) + 1
            while hi - lo > 1:
                mid = (lo + hi) // 2
                points[mid] = self._read(between[mid - 1], 'boundary')
                if same_text(sig(points[mid]), sig(points[lo])):
                    lo = mid
                else:
                    hi = mid
        frames = [left.frame, *between, right.frame]
        owners = sorted(points)
        for i, pos in enumerate(owners[:-1]):
            nxt = owners[i + 1]
            points[pos].inherited_frames += nxt - pos - 1
            points[pos].visible_until = frames[nxt - 1]['at']
        self.stats.inherited_frames += len(between) - (len(points) - 2)
        return [points[p] for p in owners[1:-1]]

    # -- driver -----------------------------------------------------------
    def scan(self, frames: Iterable[dict]) -> Iterator[OCREvent]:
        max_gap = _frames(self.config.max_gap_seconds, self.fps)
        min_gap = _frames(self.config.min_gap_seconds, self.fps) if self.config.min_gap_seconds else 1
        anchor: OCREvent | None = None
        anchor_thumb = None
        anchor_index = 0
        buffer: list[dict] = []
        pending_change = False
        for frame in frames:
            self.stats.decoded_frames += 1
            index = self.stats.decoded_frames - 1
            thumb = thumbnail(frame['image'])
            if anchor is None:
                anchor, anchor_thumb, anchor_index = self._read(frame, 'first'), thumb, index
                continue
            gap = index - anchor_index
            pending_change = pending_change or tile_change(thumb, anchor_thumb) >= self.config.change_threshold
            reason = ('grid' if gap >= max_gap else
                      'change' if pending_change and gap >= min_gap else None)
            if reason is None:
                # Keep only the downscaled image while waiting; full frames are large.
                buffer.append({k: v for k, v in frame.items() if k != 'full'})
            else:
                new = self._read(frame, reason)
                yield from self._resolve(anchor, buffer, new)
                yield anchor
                anchor, anchor_thumb, anchor_index = new, thumb, index
                buffer, pending_change = [], False
            if self.progress and self.stats.decoded_frames % 10 == 0:
                self.progress(self.stats.decoded_frames, self.stats.ocr_frames)
        if anchor is None:
            return
        if buffer:
            last = self._read(buffer.pop(), 'last')
            yield from self._resolve(anchor, buffer, last)
            yield anchor
            anchor = last
        yield anchor
        if self.progress:
            self.progress(self.stats.decoded_frames, self.stats.ocr_frames)
