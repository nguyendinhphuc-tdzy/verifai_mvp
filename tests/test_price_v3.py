"""Price Parser v3 alpha: Vietnamese formatting, context and conservative evidence."""
import pytest
from verifai_core.price import PRICE_PARSER_VERSION, extract_prices, assess_price


@pytest.mark.parametrize(('phrase','amount'), [
    ('Giá 149.000đ', 149000),
    ('99.000dd', 99000),
    ('99.000đd', 99000),
    ('99.000d', 99000),
    ('45.000d', 45000),
    ('89.000d', 89000),
    ('149,000 ₫', 149000),
    ('149000 vnd', 149000),
    ('149 000 đồng', 149000),
    ('149k', 149000),
    ('89,5k', 89500),
    ('1,2 triệu', 1200000),
    ('1.25tr', 1250000),
    ('1.200.000đ', 1200000),
    ('1,200,000VND', 1200000),
    ('Giá bán: 149000', 149000),
    ('giá gốc 299 nghìn', 299000),
    ('giá 99 ngàn', 99000),
    ('1,5 triệu đồng', 1500000),
])
def test_price_formats(phrase, amount):
    assert [m.amount_vnd for m in extract_prices(phrase)] == [amount]


@pytest.mark.parametrize('text', [
    'Sản xuất năm 2026',
    'Bé được 30 tháng tuổi',
    'Dung tích 250ml',
    'Chứa 200g',
    'Combo 3 sản phẩm',
    '100k lượt xem',
    'Có 1.5 triệu người theo dõi',
    'Ngày 21/10/2026',
    'SKU B123456',
    'Mã sản phẩm 149000',
    'Giá 2026',
    'Năm 2026 giá sẽ thay đổi',
    '12/10/2026',
    '149.5 không phải số tiền',
    'SKU A149000d',
    'Mã lô 123456d',
    '99.000ddSKU',
])
def test_non_prices_not_extracted(text):
    assert extract_prices(text) == [], text


def test_promotion_and_original_roles():
    mentions = extract_prices('Giá sale 99k, giá gốc 149k')
    assert [(m.amount_vnd,m.role,m.context) for m in mentions] == [
        (99000,'current','promotion'),(149000,'original','reference')]
    mentions = extract_prices('giá gốc 149k giảm còn 99k')
    assert [(m.amount_vnd,m.role) for m in mentions] == [(149000,'original'),(99000,'current')]


@pytest.mark.parametrize(('text','reference','expected_status','expected_reason'), [
    ('Giá bán 99k',149000,'MISMATCH','observed_price_differs_from_reference'),
    ('99.000đ',149000,'MISMATCH','observed_price_differs_from_reference'),
    ('99.000dd',149000,'MISMATCH','observed_price_differs_from_reference'),
    ('99.000đd',149000,'MISMATCH','observed_price_differs_from_reference'),
    ('45.000d',45000,'MATCH','reference_price_matches'),
    ('Giá khuyến mãi 99.000dd',149000,'INSUFFICIENT_EVIDENCE','promotion_requires_policy'),
    ('Giá bán 149k',149000,'MATCH','reference_price_matches'),
    ('149.000đ',149000,'MATCH','reference_price_matches'),
    ('Giá gốc 149k, giá sale 99k',149000,'INSUFFICIENT_EVIDENCE','promotion_requires_policy'),
    ('Giá sale 99k',149000,'INSUFFICIENT_EVIDENCE','promotion_requires_policy'),
    ('Giá gốc 149k',149000,'INSUFFICIENT_EVIDENCE','no_unambiguous_current_price'),
    ('99k đến 149k',149000,'INSUFFICIENT_EVIDENCE','no_unambiguous_current_price'),
    ('Giá 99k-149k',149000,'INSUFFICIENT_EVIDENCE','price_range'),
    ('Giá 99k, giá 149k',149000,'INSUFFICIENT_EVIDENCE','multiple_current_prices'),
    ('99k, 149k',149000,'INSUFFICIENT_EVIDENCE','no_unambiguous_current_price'),
    ('Năm 2026',149000,'INSUFFICIENT_EVIDENCE','no_price_detected'),
    ('Giá 99k',None,'INSUFFICIENT_EVIDENCE','missing_reference_price'),
    ('99k',149000,'MISMATCH','observed_price_differs_from_reference'),
    ('Giá 149k, sản phẩm khác 79k',149000,'INSUFFICIENT_EVIDENCE','unattributed_additional_price'),
    ('Giá từ 99k',149000,'INSUFFICIENT_EVIDENCE','no_unambiguous_current_price'),
    ('Giảm 20k',149000,'INSUFFICIENT_EVIDENCE','no_unambiguous_current_price'),
    ('Voucher 20k',149000,'INSUFFICIENT_EVIDENCE','no_unambiguous_current_price'),
    ('Phí ship 30k',149000,'INSUFFICIENT_EVIDENCE','no_unambiguous_current_price'),
    ('Tiết kiệm 50k',149000,'INSUFFICIENT_EVIDENCE','no_unambiguous_current_price'),
    ('Giá bán 149k giảm 20k',149000,'INSUFFICIENT_EVIDENCE','unattributed_additional_price'),
    ('Giá trước 149k, chỉ còn 99k',149000,'INSUFFICIENT_EVIDENCE','promotion_requires_policy'),
])
def test_verification_statuses(text, reference, expected_status, expected_reason):
    out = assess_price(text,reference)
    assert (out.status,out.reason) == (expected_status,expected_reason), out


def test_metadata_and_positions():
    s='🎈 Giá bán 149.000đ nhé!'
    a=assess_price(s,99000)
    assert a.status=='MISMATCH'
    assert a.compared_vnd==149000
    m=a.mentions[0]
    assert s[m.start:m.end] == m.raw
    assert a.to_dict()['mentions'][0]['role']=='current'
    assert PRICE_PARSER_VERSION.startswith('price-v3')


def test_strange_input_safe():
    assert len(extract_prices('1234567890123456789đ')) == 0
    assert extract_prices('') == []
    assert assess_price('...',100000).status == 'INSUFFICIENT_EVIDENCE'
    assert extract_prices('giá 0000000000000000000000000000đ') == []
