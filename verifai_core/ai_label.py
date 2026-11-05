"""AI-content disclosure label check (dataset group "Thiếu nhãn AI").

When the uploader declares a video as AI-generated, the video must show a
disclosure such as "Nội dung được tạo bởi AI". The check searches every text
observation (full-coverage OCR, ASR, Gemini visible text). Vietnamese OCR often
drops diacritics and reads "AI" as "Al" (e.g. "Ni dung đưc to bi Al"), so
matching is done on accent-free, letters-only text with a fuzzy threshold.

An ABSENCE finding is only trustworthy when OCR covered the whole video; the
caller passes that fact and the finding is downgraded otherwise.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata
from typing import Iterable

AI_LABEL_RULE_VERSION = 'ai-label-1.0'
AI_GENERATED_VALUES = ('unknown', 'yes', 'no')

_PHRASES = (
    # Full disclosure phrases only: short ones like 'sanphamai' fuzzily matched
    # "SAN PHAM MiniFeed" (VID_LOI44 false 'found', 02/11/2026).
    'noidungduoctaoboiai', 'noidungtaoboiai', 'duoctaoboiai', 'taoboiai',
    'videotaoboiai', 'hinhanhtaoboiai',
    'aigenerated', 'generatedbyai', 'generatedwithai', 'madewithai', 'createdwithai',
    'aigeneratedcontent', 'createdbyai',
)


def _fold(text: str) -> str:
    text = unicodedata.normalize('NFKD', str(text).replace('đ', 'd').replace('Đ', 'D'))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = re.sub(r'[^a-z0-9]', '', text)
    # OCR commonly reads the capital I of "AI" as a lowercase l.
    return re.sub(r'al$', 'ai', text)


def _matches(folded: str) -> bool:
    if len(folded) < 4:
        return False
    for phrase in _PHRASES:
        if phrase in folded:
            return True
        if len(phrase) < 10:
            continue  # short phrases: exact containment only
        if len(folded) >= 8 and SequenceMatcher(None, folded, phrase).ratio() >= 0.80:
            return True
        # Phrase embedded in a longer OCR line: compare same-length windows.
        size = len(phrase)
        if len(folded) > size:
            for start in range(0, len(folded) - size + 1):
                if SequenceMatcher(None, folded[start:start + size], phrase).ratio() >= 0.85:
                    return True
    return False


def find_ai_disclosure(texts: Iterable[str]) -> str | None:
    """Return the first text that reads as an AI disclosure label, else None."""
    for text in texts:
        if text and _matches(_fold(text)):
            return str(text)
    return None
