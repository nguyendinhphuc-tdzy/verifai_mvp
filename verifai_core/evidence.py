"""Canonical evidence normalization. Never merge different modalities or assertions."""
from __future__ import annotations
from dataclasses import dataclass, field
import hashlib
import json
import re
import unicodedata
from typing import Any


def clean_text(text: Any) -> str:
    text = unicodedata.normalize('NFKC', str(text or ''))
    text = ''.join(ch if ch.isprintable() else ' ' for ch in text)
    return re.sub(r'\s+', ' ', text).strip()[:1500]


def comparison_key(text: str) -> str:
    return clean_text(text).casefold()


@dataclass
class RawEvidence:
    uid: str
    kind: str
    at: float
    text: str
    score: float | None = None
    frame: str | None = None
    frame2: str | None = None
    source_model: str = 'unknown'
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class Evidence:
    kind: str
    timestamp: float
    end_timestamp: float
    content: str
    score: float | None
    frame: str | None
    frame2: str | None
    source_model: str
    fingerprint: str
    metadata: dict[str, Any]

    def to_db(self) -> tuple:
        return (self.kind, self.timestamp, self.end_timestamp, self.content,
                self.score, self.frame, self.frame2, self.source_model,
                self.fingerprint, json.dumps(self.metadata, ensure_ascii=False))


def normalize_evidence(raw: list[RawEvidence], window_seconds: float = 2.3) -> tuple[list[Evidence], dict[str, int]]:
    """Merge adjacent repeated OCR/ASR observations, retaining every source in metadata.

    Deliberately do NOT deduplicate VLM issues or cross-modal evidence: two different
    sources are independent claims, not interchangeable confirmations.
    Returns canonical evidence and raw-UID-to-canonical-index mapping.
    """
    normalized: list[Evidence] = []
    raw_to_canonical: dict[str, int] = {}
    for item in sorted(raw, key=lambda r: (r.at, r.uid)):
        content = clean_text(item.text)
        if not content:
            continue
        at = max(0.0, round(float(item.at), 2))
        key = comparison_key(content)
        group_idx = None
        if item.kind in ('ocr', 'asr'):
            for idx in range(len(normalized) - 1, -1, -1):
                previous = normalized[idx]
                if at - previous.end_timestamp > window_seconds:
                    break
                if (previous.kind == item.kind and previous.source_model == item.source_model
                        and comparison_key(previous.content) == key
                        and 0 <= at - previous.end_timestamp <= window_seconds):
                    group_idx = idx
                    break
        provenance = {'uid': item.uid, 'at': at, 'frame': item.frame,
                      'frame2': item.frame2, 'score': item.score,
                      'source_model': item.source_model}
        if group_idx is not None:
            existing = normalized[group_idx]
            existing.end_timestamp = max(existing.end_timestamp, at)
            if item.score is not None:
                existing.score = max(existing.score or 0.0, float(item.score))
            existing.metadata['sources'].append(provenance)
            if item.frame and item.frame not in existing.metadata['frames']:
                existing.metadata['frames'].append(item.frame)
            if item.frame2 and item.frame2 not in existing.metadata['frames']:
                existing.metadata['frames'].append(item.frame2)
            existing.frame2 = item.frame2 or item.frame or existing.frame2
            raw_to_canonical[item.uid] = group_idx
        else:
            fingerprint = hashlib.sha256(f'{item.kind}|{item.source_model}|{at}|{key}'.encode()).hexdigest()[:20]
            metadata = {**item.metadata, 'sources': [provenance],
                        'frames': [f for f in (item.frame, item.frame2) if f],
                        'normalization_version': 'evidence-2.0'}
            normalized.append(Evidence(item.kind, at, at, content, item.score,
                                       item.frame, item.frame2, item.source_model,
                                       fingerprint, metadata))
            raw_to_canonical[item.uid] = len(normalized) - 1
    return normalized, raw_to_canonical
