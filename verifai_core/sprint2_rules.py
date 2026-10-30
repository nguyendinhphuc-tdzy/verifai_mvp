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


def _specs(text: str) -> set[tuple[str,str]]:
    result=set()
    for m in _SPEC.finditer(_canonical(text)[:1500]):
        value=format(Decimal(m.group('amount').replace(',', '.')).normalize(), 'f')
        unit=m.group('unit').lower()
        if unit=='to':unit='tờ'
        if unit=='vien':unit='viên'
        result.add((value,unit))
    return result


def check_variant(text: str, reference: str) -> list[RuleCandidate]:
    """Compare explicit matching units; refuse unsupported/incomparable units.

    Price numbers and birth-age ranges are not variants. Self-contradictory
    quantities of the same unit are review candidates, not proven SKU errors.
    """
    observed=_specs(text)
    truth=_specs(reference)
    by_unit={}
    for amount,unit in observed:
        by_unit.setdefault(unit,set()).add(amount)
    expected_by_unit={}
    for amount,unit in truth:
        expected_by_unit.setdefault(unit,set()).add(amount)
    found=[]
    for unit,amounts in sorted(by_unit.items()):
        if len(amounts)>1:
            found.append(RuleCandidate('VARIANT-01',
              ', '.join(x+unit for x in sorted(amounts)), '', 'conflicting_quantities_in_text'))
            continue
        expected=expected_by_unit.get(unit)
        if expected is None or len(expected)!=1:
            continue
        actual=next(iter(amounts))
        if actual not in expected:
            found.append(RuleCandidate('VARIANT-01',actual+unit,
                 next(iter(expected))+unit,'observed_variant_differs_from_reference'))
    size_truth=_SIZE.search(_canonical(reference))
    size_video=_SIZE.search(_canonical(text))
    if size_truth and size_video and size_truth.group('size')!=size_video.group('size'):
        found.append(RuleCandidate('VARIANT-01','Size '+size_video.group('size').upper(),
                                  'Size '+size_truth.group('size').upper(),'size_mismatch'))
    return found


def check_unapproved_high_risk_claims(text:str, approved:list[str],
                                       restricted:list[str]) -> list[RuleCandidate]:
    """Only curated high-risk forms, not all arbitrary claims absent from Approved."""
    allowed=[normalize_claim(v) for v in approved]
    blocked=[normalize_claim(v) for v in restricted]
    results=[]
    # Respect negation, questions and quotations from the existing claim engine.
    for match in find_restricted_claims(text, list(HIGH_RISK_CLAIMS)):
        if match.state!='asserted':
            continue
        needle=normalize_claim(match.phrase)
        if any(needle in a for a in allowed) or any(needle in b for b in blocked):
            continue  # existing CLAIM-01 handles known restricted phrases
        results.append(RuleCandidate('CLAIM-02',match.observed,'; '.join(approved),
                                     'high_risk_phrase_not_in_approved_claims'))
    return results


# Typo prototypes from VID_LOI23..29, never treated as universal dictionary.
# Require independent OCR frame support to reduce hallucinated spelling errors.
KNOWN_BRAND_TYPOS={'minnifeed':'minifeed','babyskni':'babyskin'}


def check_brand_typo(text:str, brand:str, supporting_frames:int=0) -> list[RuleCandidate]:
    if supporting_frames<2 or not brand or len(brand)<5:
        return []
    truth=_canonical(brand)
    tokens=set(re.findall(r'\b[a-zA-Z][a-zA-Z]{3,}\b',text or ''))
    matches=[]
    for token in tokens:
        t=token.casefold()
        if t==truth:
            continue
        exact=KNOWN_BRAND_TYPOS.get(t)==truth
        near=(abs(len(t)-len(truth))<=1
              and SequenceMatcher(None,t,truth).ratio()>=0.83)
        if exact or near:
            matches.append(RuleCandidate('TEXT-01',token,brand,
                                         'ocr_brand_typo_repeated_in_frames'))
    return matches
