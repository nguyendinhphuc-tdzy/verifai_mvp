"""Conservative deterministic candidate rules distilled from Sprint-2 Sheet 2.

Dataset scenarios describe intended manipulations; they are NOT model predictions
and do not fine-tune Gemini. Flags require text evidence and human review.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal
from difflib import SequenceMatcher
import re
import unicodedata

from verifai_core.claims import find_restricted_claims, normalize_claim

RULE_VERSION='sprint2-text-v1'

# These are the seven extra/unsupported exemplar statements in
# VID_LOI16..22, generalized to recognizable short phrases.
HIGH_RISK_CLAIMS=(
    'tăng chiều cao vượt trội',
    'diệt khuẩn 99.9%',
    'hết mẩn đỏ chỉ sau',
    'an toàn tuyệt đối',
    'giống hệt ti mẹ',
    'thấm hút gấp đôi',
    'thông minh vượt trội',
)

_SPEC=re.compile(
    r'(?<!\w)(?P<amount>\d+(?:[.,]\d+)?)\s*(?P<unit>ml|kg|g|tờ|to|viên|vien|pcs)\b',
    re.I | re.U,
)
_SIZE=re.compile(r'\bsize\s*(?P<size>xs|s|m|l|xl|xxl)\b',re.I)


@dataclass(frozen=True)
class RuleCandidate:
    code:str
    observed:str
    expected:str
    reason:str


def _canonical(text: str) -> str:
    return unicodedata.normalize('NFKC',str(text or '')).casefold()


def _specs(text: str) -> set[tuple[str, str]]:
    result = set()
    normalized = _canonical(text)[:1500]
    for match in _SPEC.finditer(normalized):
        # Ranges like "6-11kg" are not a single 11kg package weight.
        before = normalized[max(0, match.start()-12):match.start()]
        if re.search(r'\d\s*[-–—]\s*$', before):
            continue
        value = format(Decimal(match.group('amount').replace(',', '.')).normalize(), 'f')
        unit = match.group('unit').lower()
        if unit == 'to':
            unit = 'tờ'
        elif unit == 'vien':
            unit = 'viên'
        result.add((value, unit))
    return result


def check_variant(text: str, reference: str) -> list[RuleCandidate]:
    """Candidate only when explicitly comparable packaging units differ."""
    observed = _specs(text)
    truth = _specs(reference)
    by_unit = {}
    for amount, unit in observed:
        by_unit.setdefault(unit, set()).add(amount)
    expected_by_unit = {}
    for amount, unit in truth:
        expected_by_unit.setdefault(unit, set()).add(amount)
    found = []
    for unit, amounts in sorted(by_unit.items()):
        if len(amounts) > 1:
            found.append(RuleCandidate(
                'VARIANT-01', ', '.join(x+unit for x in sorted(amounts)), '',
                'conflicting_quantities_in_text'))
            continue
        expected = expected_by_unit.get(unit)
        if expected is None or len(expected) != 1:
            continue
        actual = next(iter(amounts))
        if actual not in expected:
            found.append(RuleCandidate(
                'VARIANT-01', actual+unit, next(iter(expected))+unit,
                'observed_variant_differs_from_reference'))
    size_truth = _SIZE.search(_canonical(reference))
    size_video = _SIZE.search(_canonical(text))
    if size_truth and size_video and size_truth.group('size') != size_video.group('size'):
        found.append(RuleCandidate(
            'VARIANT-01', 'Size ' + size_video.group('size').upper(),
            'Size ' + size_truth.group('size').upper(), 'size_mismatch'))
    return found


def check_unapproved_high_risk_claims(text: str, approved: list[str],
                                       restricted: list[str]) -> list[RuleCandidate]:
    """Curated review patterns only, not a general claim semantic checker."""
    allowed = [normalize_claim(v) for v in approved]
    blocked = [normalize_claim(v) for v in restricted]
    results = []
    for match in find_restricted_claims(text, list(HIGH_RISK_CLAIMS)):
        if match.state != 'asserted':
            continue
        needle = normalize_claim(match.phrase)
        if any(needle in a for a in allowed) or any(needle in b for b in blocked):
            continue
        results.append(RuleCandidate(
            'CLAIM-02', match.observed, '; '.join(approved),
            'high_risk_phrase_not_in_approved_claims'))
    return results


# Typos are scenario-based prototypes, not a dictionary of all brand mistakes.
KNOWN_BRAND_TYPOS = {'minnifeed': 'minifeed', 'babyskni': 'babyskin'}


def check_brand_typo(text: str, brand: str, supporting_frames: int = 0) -> list[RuleCandidate]:
    if supporting_frames < 2 or not brand or len(brand) < 5:
        return []
    truth = _canonical(brand)
    tokens = set(re.findall(r'\b[a-zA-Z][a-zA-Z]{3,}\b', text or ''))
    matches = []
    for token in tokens:
        candidate = token.casefold()
        if candidate == truth:
            continue
        # OCR on moving packaging crops words ('NutriGro', 'iniFeed') and
        # misreads the final glyph ('NutriGrov'); neither is a printed typo.
        if candidate in truth or (len(candidate) == len(truth) and candidate[:-1] == truth[:-1]):
            continue
        exact = KNOWN_BRAND_TYPOS.get(candidate) == truth
        near = (abs(len(candidate) - len(truth)) <= 1 and
                SequenceMatcher(None, candidate, truth).ratio() >= 0.83)
        if exact or near:
            matches.append(RuleCandidate(
                'TEXT-01', token, brand, 'ocr_brand_typo_repeated_in_frames'))
    return matches


# --- Lossy-OCR tolerant checks (02/11/2026) ---------------------------------
# PaddleOCR's Vietnamese (latin) recognizer often drops diacritic letters, e.g.
# "Tăng chiu cao vưt tri" for "Tăng chiều cao vượt trội", so exact matching misses
# claims that are plainly visible. These checks compare accent-free letters.

def fold(text: str) -> str:
    text = unicodedata.normalize('NFKD', str(text or '').replace('đ', 'd').replace('Đ', 'D'))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r'[^a-z0-9%]', '', text)


def _fuzzy_contains(haystack: str, needle: str, threshold: float) -> bool:
    if not needle or not haystack:
        return False
    if needle in haystack:
        return True
    size = len(needle)
    if len(haystack) <= size:
        return SequenceMatcher(None, haystack, needle).ratio() >= threshold
    return any(SequenceMatcher(None, haystack[i:i + size], needle).ratio() >= threshold
               for i in range(0, len(haystack) - size + 1))


_NEGATION_FOLDED = ('khong', 'chua', 'khongphai')
# Absolute/superlative advertising wording that needs an approved-claim basis.
SUPERLATIVE_MARKERS = ('vuottroi', 'tuyetdoi', 'hoantoan', 'chisau', 'gapdoi', 'so1',
                       'tot nhat', 'totnhat', 'duynhat', '100%', '999%', 'ngaylap tuc',
                       'ngaylaptuc', 'cam ket', 'camket', 'than ky', 'thanky')


def check_unapproved_claims_fuzzy(text: str, approved: list[str],
                                  restricted: list[str]) -> list[RuleCandidate]:
    """CLAIM-02 candidates robust to diacritic loss.

    * curated high-risk phrases (Sprint-2 scenarios) matched fuzzily, reason
      'high_risk_phrase_fuzzy';
    * any line with superlative/absolute wording that is not an approved claim,
      reason 'superlative_not_in_approved_claims' (weaker, generic).
    """
    folded = fold(text)
    if len(folded) < 8 or any(folded.startswith(n) for n in _NEGATION_FOLDED):
        return []
    approved_f = [fold(a) for a in approved if fold(a)]
    restricted_f = [fold(r) for r in restricted if fold(r)]
    if any(_fuzzy_contains(folded, a, 0.85) or _fuzzy_contains(a, folded, 0.85) for a in approved_f):
        return []
    for phrase in HIGH_RISK_CLAIMS:
        needle = fold(phrase)
        if any(needle in r for r in restricted_f):
            continue  # restricted claims are reported by CLAIM-01
        if _fuzzy_contains(folded, needle, 0.80):
            return [RuleCandidate('CLAIM-02', text, '; '.join(approved), 'high_risk_phrase_fuzzy')]
    markers = [m.replace(' ', '') for m in SUPERLATIVE_MARKERS]
    hits = [folded.find(m) for m in markers if m in folded]
    # A negation before the wording ("không chữa khỏi hoàn toàn") is a denial.
    negated = hits and any(n in folded[:min(hits)] for n in _NEGATION_FOLDED)
    if hits and not negated:
        return [RuleCandidate('CLAIM-02', text, '; '.join(approved),
                              'superlative_not_in_approved_claims')]
    return []


def check_brand_substitution(text: str, brand: str, supporting_frames: int = 0) -> list[RuleCandidate]:
    """SKU-01 candidate: a different brand name sharing the reference's stem.

    'SoftCare' vs reference 'SoftDry' (same 4+ letter prefix, different name).
    Crops of the true brand ('ftDry', 'NutriGro') and near-typos (TEXT-01) are
    excluded. Requires the reading on >= 2 frames.
    """
    if supporting_frames < 2 or not brand:
        return []
    results = []
    for word in re.findall(r'[A-Za-z]{5,}', brand):
        truth = word.casefold()
        for token in set(re.findall(r'\b[A-Za-z]{5,}\b', text or '')):
            cand = token.casefold()
            if cand == truth or cand in truth or truth in cand:
                continue
            if SequenceMatcher(None, cand, truth).ratio() >= 0.83:
                continue  # typo-level difference, handled by TEXT-01
            shared_prefix = len(_common_prefix(cand, truth))
            rest_cand, rest_truth = cand[shared_prefix:], truth[shared_prefix:]
            # 'BabyGer' vs 'BabyGentle': the differing part starts like the true
            # one, so it is a truncated/misread reading, not another brand.
            if len(rest_cand) < 3 or (rest_truth and rest_cand[0] == rest_truth[0]):
                continue
            if shared_prefix >= 4 and not token.islower() and not token.isupper():
                results.append(RuleCandidate('SKU-01', token, word, 'brand_name_substituted'))
    return results


def _common_prefix(a: str, b: str) -> str:
    out = []
    for x, y in zip(a, b):
        if x != y:
            break
        out.append(x)
    return ''.join(out)
