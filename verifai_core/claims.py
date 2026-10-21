"""Conservative phrase-based claim verification over OCR/ASR text.

These are *candidate matches*, not semantic or legal conclusions. We avoid
auto-rejection when context is negated, quoted, hypothetical, or uncertain.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata

CLAIM_RULE_VERSION = 'claim-v3.0-alpha2'

# Clause-level scope deliberately favors "uncertain" over false certainty.
_BOUNDARY = re.compile(r'[,;.!?\n]|\b(?:nhưng|tuy nhiên|mặt khác|trái lại)\b', re.I)
_NEGATED = re.compile(
    r'\b(?:không|chẳng|chưa|không thể|không có tác dụng|không có khả năng|'
    r'không nên|đừng|chớ|không được|không giúp|chưa có bằng chứng)\b', re.I)
_HEDGED = re.compile(
    r'\b(?:có thể|được cho là|nghe nói|người ta nói|theo lời đồn|'
    r'quảng cáo rằng|tự nhận|nói rằng|liệu|có đúng|chưa rõ|'
    r'chưa được kiểm chứng|bị cho là)\b', re.I)
_WARNING = re.compile(r'\b(?:đừng tin|không tin|cảnh báo|cẩn thận|bác bỏ|sai sự thật)\b', re.I)
_QUOTE = {'"': '"', "'": "'", '“': '”', '‘': '’', '«': '»'}


@dataclass(frozen=True)
class ClaimMention:
    phrase: str
    observed: str
    state: str          # asserted | negated | uncertain
    reason: str
    start: int
    end: int

    def to_dict(self):
        return asdict(self)


def normalize_claim(text: str) -> str:
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', str(text or '')).casefold()).strip()


def normalize_claim_list(items: list[str], field: str, max_items: int = 30) -> list[str]:
    """Validate, trim, deduplicate and preserve entered wording."""
    if len(items) > max_items:
        raise ValueError(f'{field}: tối đa {max_items} cụm từ')
    seen, cleaned = set(), []
    for item in items:
        if not isinstance(item, str):
            raise ValueError(f'{field}: chỉ chấp nhận văn bản')
        phrase = unicodedata.normalize('NFKC', item).strip()
        phrase = re.sub(r'\s+', ' ', phrase)
        if not phrase or len(phrase) > 200:
            raise ValueError(f'{field}: mỗi cụm từ dài từ 1 đến 200 ký tự')
        key = normalize_claim(phrase)
        if key not in seen:
            cleaned.append(phrase)
            seen.add(key)
    return cleaned


def validate_reference_claims(approved: list[str], restricted: list[str]) -> tuple[list[str], list[str]]:
    a = normalize_claim_list(approved, 'approved_claims')
    r = normalize_claim_list(restricted, 'restricted_claims')
    collision = {normalize_claim(x) for x in a} & {normalize_claim(x) for x in r}
    if collision:
        raise ValueError('Một cụm từ không thể vừa được phép vừa bị hạn chế')
    return a, r


def find_restricted_claims(text: str, restricted: list[str]) -> list[ClaimMention]:
    """Exact boundary-aware matching with conservative local clause context."""
    s = unicodedata.normalize('NFKC', str(text or ''))[:1500]
    results = []
    for phrase in restricted:
        normalized = normalize_claim(phrase)
        if not normalized:
            continue
        tokens = [re.escape(part) for part in normalized.split()]
        pattern = re.compile(r'(?<!\w)' + r'\s+'.join(tokens) + r'(?!\w)', re.I)
        for match in pattern.finditer(s):
            before = s[:match.start()]
            after = s[match.end():]
            # Negators/hedges in earlier clauses do not govern this assertion.
            boundaries = list(_BOUNDARY.finditer(before))
            clause_start = boundaries[-1].end() if boundaries else max(0, match.start() - 100)
            prefix = s[clause_start:match.start()].strip()
            short_prefix = prefix[-75:]
            # A question can occur after the phrase in Vietnamese.
            question = bool(re.match(r'^\s*(?:không|chăng|sao|à|hay sao)\s*\?', after, re.I))
            question |= bool(re.search(r'\?[\s”"\']*$', after[:45]))
            quoted = (any(before.rstrip().endswith(q) and after.lstrip().startswith(end)
                          for q, end in _QUOTE.items())
                      or bool(re.search(r'\b(?:trích dẫn|dẫn lời|câu nói)\s*:?\s*$', short_prefix, re.I)))
            if quoted:
                state, reason = 'uncertain', 'quoted_phrase'
            elif _WARNING.search(short_prefix):
                state, reason = 'uncertain', 'warning_or_denial_of_advertising'
            elif re.search(r'\bkhông\s+chỉ\b', short_prefix, re.I):
                state, reason = 'uncertain', 'complex_negation'
            elif _NEGATED.search(short_prefix):
                state, reason = 'negated', 'explicit_negation'
            elif _HEDGED.search(short_prefix) or question:
                state, reason = 'uncertain', 'hypothetical_or_question'
            else:
                state, reason = 'asserted', 'literal_claim_present'
            results.append(ClaimMention(phrase, match.group(), state, reason,
                                        match.start(), match.end()))
    # Stable ordering for audit/evidence and overlapping phrases.
    return sorted(results, key=lambda m: (m.start, m.end, m.phrase.casefold()))
