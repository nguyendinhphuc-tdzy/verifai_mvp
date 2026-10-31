"""Stream EVERY decodable frame for OCR, without storing a video in RAM.

The sampled thumbnail timeline for UI/visual comparison is separate. Full
OCR mode performs one OCR call for every decoded frame, without a 4/12/60
frame budget. It may be extremely slow on CPU; callers must report coverage.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterator

import cv2


def iter_all_video_frames(path: Path | str, long_edge: int = 800) -> Iterator[dict]:
    """Yield one resized BGR frame per decoded video frame, in source order.

    JPEG is *not* saved here; the caller saves evidence-bearing frames only.
    Video decoding errors stop iteration and are reflected by attempted versus
    expected frames in the job's perception_quality metadata.
    """
    cap = cv2.VideoCapture(str(path))
    try:
        if not cap.isOpened():
            raise RuntimeError('Không thể mở video để quét OCR toàn bộ frame')
        fps = float(cap.get(cv2.CAP_PROP_FPS) or 0)
        if not 0 < fps < 240:
            raise RuntimeError('FPS video không hợp lệ cho OCR toàn bộ frame')
        idx = 0
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            height, width = frame.shape[:2]
            factor = min(1.0, long_edge / max(height, width))
            if factor < 1.0:
                frame = cv2.resize(
                    frame,
                    (max(1, round(width * factor)), max(1, round(height * factor))),
                    interpolation=cv2.INTER_AREA,
                )
            yield {
                'image': frame,
                'at': round(idx / fps, 3),
                'frame': f'ocr-{idx:08d}.jpg',
                'source_frame_index': idx,
            }
            idx += 1
    finally:
        cap.release()
