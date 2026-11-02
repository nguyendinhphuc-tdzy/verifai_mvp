"""Claim/brand rules on real lossy PaddleOCR readings (VID_LOI16, VID_LOI09)."""
import pytest

from verifai_core.sprint2_rules import check_brand_substitution, check_unapproved_claims_fuzzy

APPROVED = ['Bổ sung DHA', 'Hỗ trợ tiêu hóa']


@pytest.mark.parametrize('text', ['Tăng chiu cao vưt tri chí sau 1 tháng s dng',
                                  'Täng chiéu cao vưt tri chi sau 1 tháng s dng',
                                  'Diệt khuẩn 99.9%', 'An toàn tuyt đi cho bé'])
def test_high_risk_claims_survive_diacritic_loss(text):
    found = check_unapproved_claims_fuzzy(text, APPROVED, [])
    assert [c.reason for c in found] == ['high_risk_phrase_fuzzy']


@pytest.mark.parametrize('text', ['B sung DHA', 'H tr tiêu hóa', 'Hp 900g, 0-6 tháng',
                                  'Ni dung đưc to bi Al', 'Không gây kích ng', 'Milk Powder',
                                  'Sản phẩm không chữa khỏi hoàn toàn'])
def test_approved_ordinary_and_negated_text_is_not_a_claim(text):
    assert check_unapproved_claims_fuzzy(text, APPROVED, []) == []


def test_generic_superlative_is_a_weaker_candidate():
    assert [c.reason for c in check_unapproved_claims_fuzzy('Cam kết hiệu quả 100%', [], [])] == \
        ['superlative_not_in_approved_claims']


def test_brand_substitution_but_not_crops_or_typos():
    assert [c.observed for c in check_brand_substitution('SoftCare', 'SoftDry', 2)] == ['SoftCare']
    for text in ('ftDry', 'SoftDry', 'NutriGro', 'Softory', 'SN PHM'):
        assert check_brand_substitution(text, 'SoftDry', 2) == []
    assert check_brand_substitution('NutriGrov', 'NutriGrow', 2) == []  # typo -> TEXT-01
    assert check_brand_substitution('SoftCare', 'SoftDry', 1) == []     # one frame is not enough


def test_real_ocr_noise_from_original_videos_is_not_flagged():
    """Readings from clean VID_GOC01/02/04 on 02/11/2026 (moving packaging)."""
    from verifai_core.sprint2_rules import check_brand_typo
    assert check_brand_substitution('BabyGer', 'BabyGentle', 2) == []
    for token in ('NutriGro', 'NutriGrov', 'NutriGroy'):
        assert check_brand_typo(token, 'NutriGrow', 2) == []
    assert check_brand_typo('iniFeed', 'MiniFeed', 2) == []
    # Printed typos and other brands are still caught.
    assert [c.observed for c in check_brand_typo('MinniFeed', 'MiniFeed', 2)] == ['MinniFeed']
    assert [c.observed for c in check_brand_substitution('NutriMax', 'NutriGrow', 2)] == ['NutriMax']


def test_number_one_claim_needs_a_standalone_phrase():
    assert check_unapproved_claims_fuzzy('so 16m g0i to', [], []) == []  # OCR noise, VID_LOI31
    assert [c.reason for c in check_unapproved_claims_fuzzy('Thương hiệu số 1 Việt Nam', [], [])] == \
        ['superlative_not_in_approved_claims']


def test_sheet_count_unit_survives_ocr_dropping_the_vowel():
    """VID_LOI11: 'Gói 100 t' (OCR 0.97) on a pack whose reference is 'Gói 80 tờ'."""
    from verifai_core.sprint2_rules import check_variant
    for text in ('Gói 100 t', 'Gói 100 tà', 'Gói 100 tò'):
        assert [(c.observed, c.expected) for c in check_variant(text, 'Gói 80 tờ')] == [('100tờ', '80tờ')]
    assert check_variant('Gói 80 t', 'Gói 80 tờ') == []


def test_ai_disclosure_not_matched_by_product_heading():
    """VID_LOI44: Gemini text 'SAN PHAM MiniFeed ...' is not an AI disclosure."""
    from verifai_core.ai_label import find_ai_disclosure
    assert find_ai_disclosure(['Visible text on screen: SAN PHAM MiniFeed Binh sua 240ml']) is None
    assert find_ai_disclosure(['SẢN PHẨM']) is None
