"""CPU-light video frame selection and truthful per-frame OCR coverage.

Sampling selects hypotheses, not proof of OCR recall. It never runs inference,
downloads weights or fabricates extracted text.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import cv2
import numpy as np


SAMPLING_VERSION = 'media-sampling-b1.0'


def video_stride(fps: float, duration: float, max_frames: int = 60) -> int:
    """Target ~1 frame/sec for short clips, <=max_frames across long clips.

    The caller still caps the decoded frames because codecs/metadata vary.
    """
    if not math.isfinite(fps) or fps <= 0:
        raise ValueError('fps must be positive and finite')
    if max_frames <= 0:
        raise ValueError('max_frames must be positive')
    safe_duration = duration if math.isfinite(duration) and duration > 0 else 0
    spacing = max(1.0, safe_duration / max_frames)
    return max(1, round(fps * spacing))


def _spread_indices(n: int, count: int) -> list[int]:
    if n <= 0 or count <= 0:
        return []
    if count >= n:
        return list(range(n))
    if count == 1:
        return [n // 2]
    return list(dict.fromkeys(round(i * (n - 1) / (count - 1)) for i in range(count)))


def select_ocr_frames(frames: list[dict], limit: int, mode: str = 'hybrid') -> list[dict]:
    """Keep uniform temporal anchors and some visibly changed frames.

    Novelty is a thumbnail pixel-difference heuristic, not text detection.
    Every returned frame is one of the existing decoded frames, in time order.
    """
    if mode not in ('hybrid', 'uniform'):
        raise ValueError('OCR_SAMPLING_MODE must be hybrid or uniform')
    n = len(frames)
    if n == 0 or limit <= 0:
        return []
    limit = min(n, limit)
    if mode == 'uniform' or n <= limit or limit <= 2:
        return [frames[i] for i in _spread_indices(n, limit)]

    # Reserve more than half the budget for broad temporal coverage.
    anchor_count = max(2, (limit + 1) // 2)
    chosen = set(_spread_indices(n, anchor_count))
    thumbnails = []
    for frame in frames:
        img = frame['image']
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if img.ndim == 3 else img
        thumbnails.append(cv2.resize(gray, (48, 27), interpolation=cv2.INTER_AREA))
    novelty = []
    for i in range(1, n):
        delta = float(np.mean(cv2.absdiff(thumbnails[i], thumbnails[i-1]))) / 255.0
        if delta >= .045:
            novelty.append((delta, float(frames[i].get('blur', 0)), i))
    for _, _, i in sorted(novelty, key=lambda p: (-p[0], -p[1], p[2])):
        if len(chosen) >= limit:
            break
        chosen.add(i)
    # Fill any remaining positions with evenly distributed (not random) frames.
    if len(chosen) < limit:
        for i in _spread_indices(n, limit):
            chosen.add(i)
            if len(chosen) >= limit:
                break
    if len(chosen) < limit:
        for i in range(n):
            chosen.add(i)
            if len(chosen) >= limit:
                break
    return [frames[i] for i in sorted(chosen)]


@dataclass
class OCRCoverage:
    attempted_frames: int = 0
    successful_frames: int = 0
    empty_frames: int = 0
    text_lines: int = 0
    _failures: list[str] = field(default_factory=list)

    def observe(self, status: str, text_lines: int) -> None:
        self.attempted_frames += 1
        if status == 'ok':
            self.successful_frames += 1
            self.text_lines += max(0, int(text_lines))
            if text_lines <= 0:
                self.empty_frames += 1
        else:
            self._failures.append(str(status or 'error: unknown')[:180])

    def snapshot(self) -> dict:
        failures = len(self._failures)
        if self.attempted_frames == 0:
            status = 'skipped'
        elif self.successful_frames == self.attempted_frames:
            status = 'ok'
        elif self.successful_frames:
            status = 'partial'
        elif all(message == 'not_installed' for message in self._failures):
            status = 'not_installed'
        else:
            status = 'error'
        return {
            'status': status,
            'attempted_frames': self.attempted_frames,
            'successful_frames': self.successful_frames,
            'failed_frames': failures,
            'empty_frames': self.empty_frames,
            'text_lines': self.text_lines,
            'errors': list(dict.fromkeys(self._failures))[:5],
            'text_observed': self.text_lines > 0,
        }
