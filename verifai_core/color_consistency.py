"""Gemini multi-frame colour-consistency check (04/11/2026).

Native whole-video Gemini analysis missed objects that change colour mid-video
(VID_LOI31: lotion turns blue from 6 s; VID_LOI34: can turns pink). Sending a
few evenly spaced still frames in ONE call and asking explicitly about the
colour of the same object caught both, with 0 false positives on 6 original
and 6 public videos (experiment 04/11/2026, 23 videos).

Results are reviewer candidates only (VIS-02, medium): a Gemini-only finding
never forces Regenerate.
"""
from __future__ import annotations

import json
from pathlib import Path

import cv2

COLOR_CHECK_VERSION = 'color-consistency-1.0'
MIN_CONFIDENCE = 0.70

PROMPT = """Các ảnh là {n} khung hình theo thứ tự thời gian của CÙNG MỘT video quảng cáo
(thời điểm: {times} giây). Kiểm tra TÍNH NHẤT QUÁN MÀU SẮC của CÙNG MỘT vật thể giữa các khung:
bao bì/thân sản phẩm, và chất bên trong hoặc chất được lấy ra (sữa, kem, dung dịch...).
Báo lỗi khi cùng một vật thể đổi màu rõ ràng, hoặc chất có màu bất thường so với chính nó ở khung khác.
KHÔNG báo: thay đổi ánh sáng/bóng/độ phơi sáng, góc quay, cận cảnh, chuyển sang vật thể hoặc sản phẩm KHÁC,
cảnh mới có bối cảnh khác. Nếu không chắc là cùng một vật thể, không báo.
Trả JSON: {{"objects": [{{"object": str, "colors_by_frame": [str]}}],
"inconsistencies": [{{"object": str, "from_frame": int, "to_frame": int, "from_color": str,
"to_color": str, "visible_basis": str, "confidence": number}}]}}"""


def sample_frames(path: Path | str, n: int = 5, long_edge: int = 640) -> tuple[list[bytes], list[float]]:
    """n JPEG frames spread over 8 %..94 % of the video (avoids black first/last frames)."""
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 0
        count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
        duration = count / fps if fps > 0 else 0
        images, times = [], []
        if duration <= 0:
            return images, times
        for k in range(n):
            t = duration * (0.08 + 0.86 * k / max(1, n - 1))
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000)
            ok, img = cap.read()
            if not ok or img is None:
                continue
            h, w = img.shape[:2]
            scale = long_edge / max(h, w)
            if scale < 1:
                img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
            images.append(cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 88])[1].tobytes())
            times.append(round(t, 2))
        return images, times
    finally:
        cap.release()


def parse_inconsistencies(raw: str, times: list[float]) -> list[dict]:
    data = json.loads(raw)
    items = data.get('inconsistencies') if isinstance(data, dict) else None
    found = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        try:
            confidence = min(1.0, max(0.0, float(item.get('confidence') or 0)))
        except (TypeError, ValueError):
            continue
        basis = str(item.get('visible_basis') or '').strip()
        if confidence < MIN_CONFIDENCE or not str(item.get('to_color') or '').strip():
            continue
        try:
            to_frame = int(item.get('to_frame'))
        except (TypeError, ValueError):
            to_frame = len(times)
        # Model frames may be 0- or 1-based; clamp into range.
        index = min(max(to_frame - 1 if to_frame >= 1 else to_frame, 0), len(times) - 1) if times else 0
        found.append({'object': str(item.get('object') or '')[:120],
                      'from_color': str(item.get('from_color') or '')[:60],
                      'to_color': str(item.get('to_color') or '')[:60],
                      'visible_basis': basis[:400], 'confidence': round(confidence, 2),
                      'timestamp': times[index] if times else 0.0})
    return found


def check_color_consistency(client, model: str, path: Path | str, n: int = 5) -> dict:
    """Returns {'status', 'times', 'issues'}; raises on API errors (caller records them)."""
    from google.genai import types
    images, times = sample_frames(path, n)
    if len(images) < 2:
        return {'status': 'skipped_too_few_frames', 'times': times, 'issues': []}
    parts = [types.Part.from_bytes(data=b, mime_type='image/jpeg') for b in images]
    response = client.models.generate_content(
        model=model, contents=parts + [PROMPT.format(n=len(images), times=times)],
        config=types.GenerateContentConfig(response_mime_type='application/json',
                                           thinking_config=types.ThinkingConfig(thinking_level='low')))
    issues = parse_inconsistencies(response.text or '{}', times)
    return {'status': 'ok', 'times': times, 'issues': issues}
