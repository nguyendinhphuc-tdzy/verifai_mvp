"""Vietnamese price extraction/verification, v3-alpha.

Only recognizes price-like numbers in text. Distinguishes an observed price
from proof of a pricing violation: discounts and ambiguous contexts need review.
No LLM, model weights, or network dependencies.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import re
import unicodedata

PRICE_PARSER_VERSION = 'price-v3.0-alpha2'
MIN_VND = 1_000
MAX_VND = 100_000_000

# Grouped whole amounts and local decimal multipliers (e.g. 1,2 triệu).
_AMOUNT = r'(?:\d{1,3}(?:[., ]\d{3})+|\d+(?:[.,]\d+)?)'
# OCR frequently turns the đồng symbol into d, dd, or đd. These suffixes
# are accepted only for thousands-grouped numbers (e.g. 99.000dd),
# avoiding accidental interpretation of ungrouped product identifiers.
_UNIT = r'(?:triệu|trieu|nghìn|ngàn|nghin|ngan|đồng|dong|vnđ|vnd|tr|k|₫|đd|dd|đ|d)'
_TOKEN = re.compile(rf'(?<![\w])(?P<number>{_AMOUNT})\s*(?P<unit>{_UNIT})?(?![\w])', re.I | re.U)
_ORIGINAL = re.compile(r'\b(?:giá\s+(?:gốc|cũ|niêm\s*yết|trước(?:\s*đây)?|ban\s*đầu)|giá\s+thị\s+trường|trước\s+khi\s+giảm)\b', re.I)
_RANGE = re.compile(r'\b(?:giá\s+(?:từ|dao\s*động\s*từ)|chỉ\s+từ|từ|lên\s+đến|dưới|trên)\b', re.I)
_NON_PRICE_AMOUNT = re.compile(r'\b(?:giảm(?!\s*còn)|tiết\s*kiệm|voucher|mã\s+giảm|phí\s+(?:ship|vận\s*chuyển)|ship|hoàn\s+tiền|trị\s+giá|ưu\s+đãi\s+thêm)\b', re.I)
_PROMO = re.compile(r'\b(?:giá\s+(?:sale|khuyến\s*mãi|ưu\s*đãi)|giảm\s+còn|chỉ\s+còn|sale\s+còn|đang\s+sale|khuyến\s*mãi)\b', re.I)
_CURRENT = re.compile(r'\b(?:giá\s+(?:bán|hiện\s*tại|chỉ|là)|chốt\s+giá|bán\s+với\s+giá|giá|chỉ\s+có|chỉ)\b', re.I)
_OTHER_UNIT = re.compile(r'^(?:ml|l|kg|g|gram|cm|mm|m²|m2|gb|mb|fps|%|tuổi|tháng|phút|giây|cái|hộp|viên|gói|chiếc|pcs)\b', re.I)
_SOCIAL_UNIT = re.compile(r'^\s*(?:lượt\s+(?:xem|thích)|views?|followers?|người\s+(?:xem|theo\s*dõi)|likes?)\b', re.I)
_CONTEXT_PREFIX = re.compile(r'(?:giá|chỉ|sale|khuyến\s*mãi|giảm\s+còn|bán|đồng|vnd|₫|đ)\s*[:：]?\s*$', re.I)
_RELEVANT_SEPARATOR = re.compile(r'[;\n.!?。]')
_RANGE_JOIN = re.compile(r'^\s*(?:[-–—~]|đến|tới)\s*$', re.I)


@dataclass(frozen=True)
class PriceMention:
    amount_vnd: int
    raw: str
    role: str                # current | original | range | other | unknown
    context: str             # regular | promotion | reference | unspecified
    explicit_currency: bool
    start: int
    end: int

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PriceAssessment:
    status: str              # MATCH | MISMATCH | INSUFFICIENT_EVIDENCE
    reason: str
    reference_vnd: int | None
    mentions: tuple[PriceMention, ...]
    compared_vnd: int | None = None

    def to_dict(self) -> dict:
        return {**asdict(self), 'mentions': [m.to_dict() for m in self.mentions]}


def _amount_value(num: str, unit: str) -> int | None:
    lower = unit.lower()
    if lower in ('triệu', 'trieu', 'tr'):
        multiplier = 1_000_000
    elif lower in ('nghìn', 'ngàn', 'nghin', 'ngan', 'k'):
        multiplier = 1_000
    else:
        multiplier = 1
    # Decimal multiplier syntax: 1,2 triệu; 89.5k. Grouped integers: 1.200.000.
    try:
        if multiplier > 1:
            if re.fullmatch(r'\d{1,3}(?:[., ]\d{3})+', num):
                value = Decimal(re.sub(r'[., ]', '', num))
            else:
                value = Decimal(num.replace(',', '.'))
        else:
            if not re.fullmatch(r'(?:\d{1,3}(?:[., ]\d{3})+|\d+)', num):
                return None
            value = Decimal(re.sub(r'[., ]', '', num))
        result = value * multiplier
        if result != result.to_integral_value() or not MIN_VND <= result <= MAX_VND:
            return None
        return int(result)
    except InvalidOperation:
        return None


def _role(prefix: str) -> tuple[str, str]:
    # Only the *nearest* recognizable qualifier applies. This handles
    # 'giá gốc 149k, giảm còn 99k' without attaching the first role to 99k.
    matches = [(m.start(), 'original', 'reference') for m in _ORIGINAL.finditer(prefix)]
    matches += [(m.start(), 'current', 'promotion') for m in _PROMO.finditer(prefix)]
    matches += [(m.start(), 'current', 'regular') for m in _CURRENT.finditer(prefix)]
    matches += [(m.start(), 'range', 'unspecified') for m in _RANGE.finditer(prefix)]
    matches += [(m.start(), 'other', 'unspecified') for m in _NON_PRICE_AMOUNT.finditer(prefix)]
    if not matches:
        return 'unknown', 'unspecified'
    _, role, kind = max(matches, key=lambda item: (item[0], item[1] in ('range', 'other'), item[2] == 'reference', item[2] == 'promotion'))
    return role, kind


def extract_prices(text: str) -> list[PriceMention]:
    """Return bounded, position-aware price candidates (not violation claims)."""
    s = unicodedata.normalize('NFKC', str(text or ''))[:1500]
    found: list[PriceMention] = []
    previous_end = 0
    for match in _TOKEN.finditer(s):
        num = match.group('number')
        unit = (match.group('unit') or '').lower()
        before = s[:match.start()]
        after = s[match.end():]
        # Number fragments must not be embedded in dates, product codes or units.
        if (not unit and ((before.endswith(('/', ':')) and re.search(r'\d[/:-]$', before))
                          or re.match(r'^[/:-]\d', after))):
            continue
        if not unit:
            if _OTHER_UNIT.match(after.lstrip()):
                continue
            # No bare '2026', quantities, years or decimal amounts.
            if not _CONTEXT_PREFIX.search(before[-30:]):
                continue
            if num.isdigit() and 1900 <= int(num) <= 2100:
                continue
            if re.fullmatch(r'\d+(?:[.,]\d+)', num):
                continue
        elif unit in ('k', 'triệu', 'trieu', 'tr', 'nghìn', 'ngàn', 'nghin', 'ngan') and _SOCIAL_UNIT.match(after):
            continue
        # Restrict OCR-only unit variants to grouped VND amounts. Never
        # silently alter the original observed text or its character offsets.
        if unit in ('d', 'dd', 'đd') and not re.fullmatch(r'\d{1,3}(?:[., ]\d{3})+', num):
            continue
        amount = _amount_value(num, unit)
        if amount is None:
            continue
        # Don't let a qualifier from the previous sentence apply to this one.
        prefix = _RELEVANT_SEPARATOR.split(s[previous_end:match.start()])[-1][-45:]
        role, context = _role(prefix)
        # 'chỉ 99k' is a current selling-price claim. Naked '149k' remains
        # unknown; it can still be evaluated when it is the only price in text.
        found.append(PriceMention(amount, match.group().strip(), role, context,
                                  bool(unit), match.start(), match.end()))
        previous_end = match.end()
    return found


def assess_price(text: str, reference_vnd: int | None) -> PriceAssessment:
    """Conservative comparison against a single Product Truth reference price.

    A clear price mismatch is a *review candidate*, never proof of wrongdoing.
    A promotional price cannot be rejected against an ordinary single-price
    reference because an allowed sale may explain the difference.
    """
    mentions = tuple(extract_prices(text))
    if reference_vnd is None or reference_vnd <= 0:
        return PriceAssessment('INSUFFICIENT_EVIDENCE', 'missing_reference_price', reference_vnd, mentions)
    if not mentions:
        return PriceAssessment('INSUFFICIENT_EVIDENCE', 'no_price_detected', reference_vnd, mentions)
    old = [m for m in mentions if m.role == 'original']
    current = [m for m in mentions if m.role == 'current']
    if not current and not old and len(mentions) == 1 and mentions[0].role == 'unknown' and mentions[0].explicit_currency:
        current = [mentions[0]]
    if not current:
        return PriceAssessment('INSUFFICIENT_EVIDENCE', 'no_unambiguous_current_price', reference_vnd, mentions)
    distinct = {m.amount_vnd for m in current}
    if len(distinct) != 1:
        return PriceAssessment('INSUFFICIENT_EVIDENCE', 'multiple_current_prices', reference_vnd, mentions)
    value = next(iter(distinct))
    # A price range or multiple unlabelled values cannot be tied to one SKU.
    if len(mentions) > 1:
        for a, b in zip(mentions, mentions[1:]):
            gap = unicodedata.normalize('NFKC', str(text or ''))[a.end:b.start]
            if _RANGE_JOIN.fullmatch(gap):
                return PriceAssessment('INSUFFICIENT_EVIDENCE', 'price_range', reference_vnd, mentions)
        if any(m.role in ('unknown', 'other', 'range') for m in mentions):
            return PriceAssessment('INSUFFICIENT_EVIDENCE', 'unattributed_additional_price', reference_vnd, mentions)
    if value == reference_vnd:
        return PriceAssessment('MATCH', 'reference_price_matches', reference_vnd, mentions, value)
    if old or any(m.context == 'promotion' for m in current):
        return PriceAssessment('INSUFFICIENT_EVIDENCE', 'promotion_requires_policy', reference_vnd, mentions, value)
    return PriceAssessment('MISMATCH', 'observed_price_differs_from_reference', reference_vnd, mentions, value)
