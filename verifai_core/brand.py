"""Conservative OCR-first brand consistency screening.

Only tests an explicit, unambiguous transposition of CamelCase brand words
(e.g. BabySkin -> SkinBaby), not arbitrary unknown text or fuzzy similarity.
A repeated candidate is for HUMAN REVIEW; no legal or SKU verdict is implied.
"""
from __future__ import annotations

import re
from typing import Any, Sequence

BRAND_RULE_VERSION = 'brand-consistency-v1'


def _brand_parts(brand: str) -> list[str]:
    """Split two-part/multi-part CamelCase or whitespace-separated brand names."""
    text = str(brand or '').strip()
    return re.findall(r'[A-Z]?[a-z]+|[A-Z]+(?![a-z])|\d+', text)


def _candidate_transposition(brand: str) -> str | None:
    parts = _brand_parts(brand)
    # A reversed single word, abbreviation or very short fragment is unsafe.
    if len(parts) != 2 or any(len(x) < 3 for x in parts):
        return None
    if parts[0].casefold() == parts[1].casefold():
        return None
    return parts[1] + parts[0]


def _field(e: Any, name: str, default=None):
    return e.get(name, default) if isinstance(e, dict) else getattr(e, name, default)


def detect_brand_inconsistencies(
    evidence: Sequence[Any], reference_brand: str, *, min_supporting_frames: int = 2
) -> list[dict]:
    """Return one candidate per transposed brand, linked to a canonical OCR item.

    Requiring 2 distinct source frames prevents a single spurious OCR reading
    from appearing as a brand inconsistency. Multiple readings from one frame
    do not count as independent frame support or independent model modalities.
    """
    candidate = _candidate_transposition(reference_brand)
    if not candidate:
        return []
    token = re.compile(r'(?<!\w)' + re.escape(candidate) + r'(?!\w)', re.I)
    strongest = None
    for index, e in enumerate(evidence):
        if _field(e, 'kind') != 'ocr':
            continue
        content = str(_field(e, 'content', ''))
        if not token.search(content):
            continue
        score = _field(e, 'score')
        if score is None or float(score) < 0.90:
            continue
        meta = _field(e, 'metadata', {}) or {}
        frames = {str(row['frame']) for row in meta.get('sources', [])
                  if isinstance(row, dict) and row.get('frame')}
        if not frames and _field(e, 'frame'):
            frames.add(str(_field(e, 'frame')))
        if len(frames) < min_supporting_frames:
            continue
        result = {
            'canonical_index': index,
            'reference_brand': reference_brand,
            'observed_brand': candidate,
            'supporting_frames': sorted(frames),
            'supporting_frame_count': len(frames),
            'rule_version': BRAND_RULE_VERSION,
        }
        if strongest is None or result['supporting_frame_count'] > strongest['supporting_frame_count']:
            strongest = result
    return [strongest] if strongest is not None else []
