"""RULE02: infant nutrition products, feeding bottles and teats (Nghị định 100/2014/NĐ-CP, Điều 6).

Product Truth carries `category` and `target_age`. Findings are reviewer
candidates; the app never states that an advertisement is unlawful.
"""
from __future__ import annotations

from difflib import SequenceMatcher
import re
import unicodedata

INFANT_RULE_VERSION = 'infant-1.0'
CATEGORIES = ('general', 'infant_formula', 'complementary_food', 'feeding_bottle_teat')
CATEGORY_NAMES = {'general': 'Khác', 'infant_formula': 'Sữa/sản phẩm dinh dưỡng thay thế sữa mẹ',
                  'complementary_food': 'Thức ăn bổ sung cho trẻ nhỏ',
                  'feeding_bottle_teat': 'Bình bú, vú ngậm nhân tạo'}


def _fold(text: str, keep_spaces: bool = True) -> str:
    text = unicodedata.normalize('NFKD', str(text or '').replace('đ', 'd').replace('Đ', 'D'))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    return re.sub(r'\s+', ' ', text) if keep_spaces else re.sub(r'[^a-z0-9]', '', text)


def max_age_months(target_age: str) -> int | None:
    """'0-6 tháng' -> 6, '6-12 tháng' -> 12, '1-3 tuổi' -> 36, '' -> None."""
    s = _fold(target_age)
    m = re.search(r'(\d+)\s*(?:-|–|den|toi)\s*(\d+)\s*(thang|tuoi|month|year)', s)
    if m:
        value, unit = int(m.group(2)), m.group(3)
    else:
        m = re.search(r'(?:duoi|<)\s*(\d+)\s*(thang|tuoi|month|year)', s)
        if not m:
            return None
        value, unit = int(m.group(1)), m.group(2)
    return value * 12 if unit in ('tuoi', 'year') else value


def advertising_restriction(category: str, target_age: str) -> dict | None:
    """Reason the product falls in Điều 6 khoản 1, or None."""
    age = max_age_months(target_age)
    if category == 'feeding_bottle_teat':
        return {'reason': 'feeding_bottle_teat',
                'detail': 'Bình bú/vú ngậm nhân tạo thuộc diện cấm quảng cáo theo NĐ 100/2014 Điều 6 khoản 1.'}
    if category == 'infant_formula' and (age is None or age <= 24):
        return {'reason': 'infant_formula_under_24m' if age is not None else 'infant_formula_age_unknown',
                'detail': ('Sản phẩm thay thế sữa mẹ cho trẻ ' +
                           (f'đến {age} tháng tuổi' if age is not None else 'chưa rõ độ tuổi (khai báo trong Product Truth)') +
                           ' thuộc diện cấm quảng cáo cho trẻ dưới 24 tháng theo NĐ 100/2014 Điều 6 khoản 1.')}
    if category == 'complementary_food' and age is not None and age <= 6:
        return {'reason': 'complementary_food_under_6m',
                'detail': f'Thức ăn bổ sung cho trẻ đến {age} tháng thuộc diện cấm quảng cáo (dưới 6 tháng).'}
    return None


# Comparisons with breast milk or the mother's nipple, accent-free. OCR drops
# accented vowels ("Ging ht ti m" for "Giống hệt ti mẹ"), so long phrases are
# matched fuzzily; short ones only exactly ("Núm ti mềm" must not match).
_EXACT = ('nhusuame', 'nhutime', 'giongtime', 'chuansuame')
_FUZZY = ('thaythesuame', 'tothonsuame', 'ganvoisuame', 'tuongduongsuame', 'gionghetsuame',
          'gionghettime', 'thaythetime', 'giongnhusuame', 'giongsuame')
_NEGATION = ('khong', 'chua', 'khng')


def _negated(folded: str, start: int) -> bool:
    return any(n in folded[max(0, start - 8):start + 3] for n in _NEGATION)


def _best_window(folded: str, phrase: str) -> tuple[float, int]:
    best, where = 0.0, 0
    size = len(phrase)
    for length in range(max(4, size - 3), size + 2):
        for i in range(0, max(1, len(folded) - length + 1)):
            window = folded[i:i + length]
            matched = sum(b.size for b in SequenceMatcher(None, phrase, window).get_matching_blocks())
            score = matched / size
            if score > best:
                best, where = score, i
    return best, where


def breastmilk_comparison(text: str) -> str | None:
    folded = _fold(text, keep_spaces=False)
    if len(folded) < 6:
        return None
    for phrase in _EXACT + _FUZZY:
        at = folded.find(phrase)
        if at >= 0:
            return None if _negated(folded, at) else phrase
    for phrase in _FUZZY:
        score, at = _best_window(folded, phrase)
        if score >= (0.75 if len(phrase) >= 12 else 0.8) and folded[at:at + 1] == phrase[0]:
            return None if _negated(folded, at) else phrase
    return None


_AGE = re.compile(r'(\d+\s*(?:-|–|den|toi)\s*\d+\s*(?:thang|thng|tuoi|tui|th))|'
                  r'((?:tren|tu|duoi)\s*\d+\s*(?:thang|tuoi))|(\d+\s*(?:thang|tuoi)\s*tuoi)')


def has_age_information(texts) -> bool:
    return any(_AGE.search(_fold(t)) for t in texts if t)
