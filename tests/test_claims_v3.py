"""Context-aware claim matching: deterministic unit tests, no model downloads."""
import pytest
from verifai_core.claims import (
    CLAIM_RULE_VERSION, find_restricted_claims, normalize_claim_list,
    validate_reference_claims,
)

PHRASE = 'chữa khỏi hoàn toàn'

@pytest.mark.parametrize(('text','expected','reason'), [
    ('Sản phẩm giúp chữa khỏi hoàn toàn', 'asserted','literal_claim_present'),
    ('CHỮA KHỎI HOÀN TOÀN', 'asserted','literal_claim_present'),
    ('Sản phẩm không chữa khỏi hoàn toàn','negated','explicit_negation'),
    ('Sản phẩm chẳng chữa khỏi hoàn toàn','negated','explicit_negation'),
    ('Sản phẩm không có tác dụng chữa khỏi hoàn toàn','negated','explicit_negation'),
    ('Sản phẩm chưa có bằng chứng chữa khỏi hoàn toàn','negated','explicit_negation'),
    ('Không nên quảng cáo chữa khỏi hoàn toàn','negated','explicit_negation'),
    ('Không chỉ làm dịu mà còn chữa khỏi hoàn toàn','uncertain','complex_negation'),
    ('Có thể chữa khỏi hoàn toàn','uncertain','hypothetical_or_question'),
    ('Nghe nói sản phẩm chữa khỏi hoàn toàn','uncertain','hypothetical_or_question'),
    ('Bị cho là chữa khỏi hoàn toàn','uncertain','hypothetical_or_question'),
    ('Câu nói: “chữa khỏi hoàn toàn”','uncertain','quoted_phrase'),
    ('Một lời quảng cáo "chữa khỏi hoàn toàn"','uncertain','quoted_phrase'),
    ('Cảnh báo lời quảng cáo chữa khỏi hoàn toàn','uncertain','warning_or_denial_of_advertising'),
    ('Đừng tin chữa khỏi hoàn toàn','uncertain','warning_or_denial_of_advertising'),
])
def test_context_classification(text,expected,reason):
    m=find_restricted_claims(text,[PHRASE])
    assert len(m)==1
    assert (m[0].state,m[0].reason)==(expected,reason)
    assert text[m[0].start:m[0].end].lower() == PHRASE.lower()

@pytest.mark.parametrize('text',[
    'Video nói về đồ dùng cho bé',
    'không được quảng cáo kiểu chữa khỏi hoàn toàns',
    'chữa khỏi hoàn',
    'chữa khỏi hoàn toànn',
    'phục hồi hoàn toàn',
])
def test_does_not_match_unrelated_text(text):
    assert find_restricted_claims(text,[PHRASE])==[]

def test_clauses_reset_negation():
    mentions=find_restricted_claims(
        'Không chữa khỏi hoàn toàn, nhưng sản phẩm này chữa khỏi hoàn toàn.',
        [PHRASE])
    assert [m.state for m in mentions]==['negated','asserted']

def test_multiple_phrases_sorted_and_not_merged():
    phrases=['chứa cồn','chữa khỏi hoàn toàn']
    ms=find_restricted_claims('Không chứa cồn, nhưng chữa khỏi hoàn toàn',phrases)
    assert [(m.phrase,m.state) for m in ms] == [('chứa cồn','negated'),(PHRASE,'asserted')]

def test_claim_list_deduplicates_and_detects_collision():
    approved,restricted=validate_reference_claims(
        [' Dưỡng ẩm ', 'dưỡng   ẩm','dịu nhẹ'],
        ['CHỮA KHỎI HOÀN TOÀN', 'chữa khỏi hoàn toàn'])
    assert approved==['Dưỡng ẩm','dịu nhẹ']
    assert restricted==['CHỮA KHỎI HOÀN TOÀN']
    with pytest.raises(ValueError,match='vừa được phép'):
        validate_reference_claims(['Dưỡng ẩm'],['dưỡng  ẩm'])

@pytest.mark.parametrize('items', [[''],['  '],['x'*201],[7],['x'+str(i) for i in range(31)]])
def test_invalid_product_claims_are_rejected(items):
    with pytest.raises(ValueError):
        normalize_claim_list(items,'approved_claims')

def test_audit_schema_is_serializable():
    data=find_restricted_claims('Sản phẩm chữa khỏi hoàn toàn',[PHRASE])[0].to_dict()
    assert data['state']=='asserted' and data['phrase']==PHRASE
    assert CLAIM_RULE_VERSION.startswith('claim-v3')
