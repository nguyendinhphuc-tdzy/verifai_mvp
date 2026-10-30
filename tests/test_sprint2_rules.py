"""Candidate rule fixtures derived from controlled scenarios, not measured video accuracy."""
from verifai_core.sprint2_rules import (
    check_variant,check_unapproved_high_risk_claims,check_brand_typo
)

def test_variant_detects_wrong_volume_from_sprint2():
    errors=check_variant('Bình sữa MiniFeed 200ml','240ml')
    assert len(errors)==1
    assert errors[0].code=='VARIANT-01'
    assert errors[0].observed=='200ml'
    assert errors[0].expected=='240ml'
    assert check_variant('Bình sữa MiniFeed 240ml','240ml')==[]
    assert check_variant('Giá chỉ 99.000đ','240ml')==[]
    assert check_variant('350ml và 528ml','350ml')[0].reason=='conflicting_quantities_in_text'

def test_variant_understands_piece_count_and_size():
    assert check_variant('100 tờ','Gói 80 tờ')[0].code=='VARIANT-01'
    assert check_variant('Size L','Size M (6-11kg)')[0].reason=='size_mismatch'
    assert check_variant('6-11kg','Size M (6-11kg)')==[]  # no false size candidate

def test_unapproved_claim_examples_and_negations():
    assert check_unapproved_high_risk_claims(
        'Sản phẩm diệt khuẩn 99.9%', ['Dịu nhẹ cho da'], [])
    assert check_unapproved_high_risk_claims(
        'An toàn tuyệt đối cho bé', ['Không kích ứng'], [])
    assert not check_unapproved_high_risk_claims(
        'Sản phẩm không an toàn tuyệt đối', [], [])
    assert not check_unapproved_high_risk_claims(
        'Sản phẩm an toàn tuyệt đối', ['an toàn tuyệt đối'], [])
    assert not check_unapproved_high_risk_claims(
        'Sản phẩm an toàn tuyệt đối', [], ['an toàn tuyệt đối'])

def test_repeated_ocr_brand_typo_requires_distinct_frames():
    assert check_brand_typo('MinniFeed','MiniFeed',supporting_frames=2)
    assert check_brand_typo('BabySkni','BabySkin',supporting_frames=2)
    assert check_brand_typo('MinniFeed','MiniFeed',supporting_frames=1)==[]
    assert check_brand_typo('MiniFeed','MiniFeed',supporting_frames=2)==[]
    assert check_brand_typo('TotallyUnrelated','MiniFeed',supporting_frames=3)==[]
