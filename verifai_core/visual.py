"""OpenCV temporal signals for conservative shot-aware VLM pair selection.

These features are NOT a deepfake/AI artifact detector. Motion, cuts, occlusion,
lighting and camera angle can change them substantially.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
import cv2
import numpy as np


@dataclass
class PairSignal:
    at: float
    at2: float
    frame: str
    frame2: str
    histogram_distance: float
    pixel_delta: float
    phash_distance: int
    orb_matches: int
    scene_cut: bool
    likely_same_shot: bool
    candidate: bool

    def to_dict(self):
        return asdict(self)


def _phash(gray: np.ndarray) -> np.ndarray:
    image = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(image)[:8, :8]
    median = float(np.median(dct[1:, :]))
    return (dct > median).reshape(-1)


def compare_frames(a: dict, b: dict) -> PairSignal:
    im1 = cv2.resize(a['image'], (256, 144), interpolation=cv2.INTER_AREA)
    im2 = cv2.resize(b['image'], (256, 144), interpolation=cv2.INTER_AREA)
    hsv1, hsv2 = cv2.cvtColor(im1, cv2.COLOR_BGR2HSV), cv2.cvtColor(im2, cv2.COLOR_BGR2HSV)
    h1 = cv2.calcHist([hsv1], [0, 1], None, [32, 16], [0, 180, 0, 256])
    h2 = cv2.calcHist([hsv2], [0, 1], None, [32, 16], [0, 180, 0, 256])
    cv2.normalize(h1, h1); cv2.normalize(h2, h2)
    hist = float(cv2.compareHist(h1, h2, cv2.HISTCMP_BHATTACHARYYA))
    delta = float(np.mean(cv2.absdiff(im1, im2))) / 255.0
    g1, g2 = cv2.cvtColor(im1, cv2.COLOR_BGR2GRAY), cv2.cvtColor(im2, cv2.COLOR_BGR2GRAY)
    phash = int(np.count_nonzero(_phash(g1) != _phash(g2)))
    orb = cv2.ORB_create(nfeatures=300)
    _, des1 = orb.detectAndCompute(g1, None)
    _, des2 = orb.detectAndCompute(g2, None)
    matches = 0
    if des1 is not None and des2 is not None:
        matches = sum(m.distance < 55 for m in cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True).match(des1, des2))
    scene_cut = hist > 0.55 and delta > 0.16 and matches < 10
    same_shot = not scene_cut and ((hist < 0.28 and delta < 0.38) or (hist < 0.48 and delta < 0.20) or (matches >= 22 and delta < 0.38))
    candidate = same_shot and (delta > 0.075 or phash >= 14)
    return PairSignal(round(a['at'], 2), round(b['at'], 2), a['frame'], b['frame'],
                      round(hist, 3), round(delta, 3), phash, matches,
                      scene_cut, same_shot, candidate)


def visual_pairs(frames: list[dict]) -> list[PairSignal]:
    return [compare_frames(a, b) for a, b in zip(frames, frames[1:])]


def evenly_spaced(items: list, limit: int) -> list:
    if limit <= 0 or not items:
        return []
    if len(items) <= limit:
        return list(items)
    if limit == 1:
        return [items[len(items) // 2]]
    indices = [round(i * (len(items) - 1) / (limit - 1)) for i in range(limit)]
    return [items[i] for i in dict.fromkeys(indices)]


def select_pairs(signals: list[PairSignal], limit: int) -> list[PairSignal]:
    # Prefer same-shot temporal changes, then other same-shot pairs for controls.
    candidates = [s for s in signals if s.likely_same_shot and s.candidate]
    stable = [s for s in signals if s.likely_same_shot and not s.candidate]
    selected = evenly_spaced(candidates, limit)
    if len(selected) < limit:
        selected += evenly_spaced(stable, limit - len(selected))
    return sorted(selected, key=lambda s: s.at)
