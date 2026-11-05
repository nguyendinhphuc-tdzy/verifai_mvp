"""RULE01–RULE10 registry: explain each finding with a rule and its stated basis.

Source: the team's "Bộ rule 1-10" document (04/11/2026), with corrections from
docs/RULE01_10_AUDIT_2026.md and a quick check of secondary legal sources on
04/11/2026. These are NOT verified legal conclusions: every entry carries
`legal_review_required=True` and the app never states that a video violates
the law. `review_priority` (team policy) is separate from a finding's evidence
severity, which drives Pass / Needs Review / Regenerate.

Review this file every 2 sprints (laws and platform policies change).
"""
from __future__ import annotations

RULES_VERSION = 'rules-2026-11-04'

RULES: dict[str, dict] = {
    'RULE01': {
        'title': 'Claim ngoài danh sách được duyệt',
        'error_label': 'CLAIM_VIOLATION',
        'review_priority': 'Cao',
        'legal_basis': 'Luật Quảng cáo 16/2012/QH13, sửa đổi bởi Luật 75/2025/QH15 (hiệu lực 01/01/2026) – '
                       'Điều 8 khoản 9 (cấm quảng cáo sai/gây nhầm lẫn về chất lượng, công dụng...)',
    },
    'RULE02': {
        'title': 'Quảng cáo sản phẩm dinh dưỡng trẻ nhỏ, bình bú, vú ngậm',
        'error_label': 'CLAIM_VIOLATION',
        'review_priority': 'Rất cao',
        'legal_basis': 'Nghị định 100/2014/NĐ-CP – Điều 6 khoản 1 (cấm quảng cáo sữa thay thế sữa mẹ cho trẻ '
                       'dưới 24 tháng, thức ăn bổ sung cho trẻ dưới 6 tháng, bình bú và vú ngậm nhân tạo)',
        'legal_note': 'Một số nguồn báo chí nhắc thay đổi theo Nghị định 87/2026/NĐ-CP; chưa xác minh.',
    },
    'RULE03': {
        'title': 'Sai giá',
        'error_label': 'PRICE_MISMATCH',
        'review_priority': 'Cao',
        'legal_basis': 'Luật Bảo vệ quyền lợi người tiêu dùng 19/2023/QH15 – Điều 10 khoản 1 điểm a '
                       '(lừa dối/gây nhầm lẫn qua thông tin sai lệch về sản phẩm)',
        'legal_note': 'Tài liệu gốc dẫn thêm điểm e; điểm e nói về trách nhiệm khác, không dùng làm căn cứ.',
    },
    'RULE04': {
        'title': 'Sai tên/SKU/quy cách',
        'error_label': 'NAME_SKU_MISMATCH',
        'review_priority': 'Cao',
        'legal_basis': 'Luật Quảng cáo 16/2012/QH13, sửa đổi bởi Luật 75/2025/QH15 – Điều 8 khoản 9 '
                       '(nhãn hiệu, xuất xứ, chủng loại)',
    },
    'RULE05': {
        'title': 'Căn cứ xử phạt (chỉ chú giải, không tạo cảnh báo)',
        'error_label': 'CLAIM_VIOLATION (enforcement)',
        'review_priority': 'Rất cao',
        'legal_basis': 'Nghị định 87/2026/NĐ-CP (xử phạt VPHC văn hóa và quảng cáo, hiệu lực 15/05/2026)',
        'legal_note': 'Điều/khoản và mức phạt trong tài liệu gốc chưa khớp nguồn đã tra; app không hiển thị '
                      'mức phạt cho tới khi pháp chế xác nhận.',
    },
    'RULE06': {
        'title': 'Lỗi chữ/phụ đề hiển thị',
        'error_label': 'TEXT_RENDER_ERROR',
        'review_priority': 'Trung bình',
        'legal_basis': 'TikTok Advertising Policies – Misleading and False Content',
    },
    'RULE07': {
        'title': 'Hình ảnh sản phẩm không nhất quán',
        'error_label': 'VIS-01 (Product Visual Inconsistency)',
        'review_priority': 'Trung bình',
        'legal_basis': 'Luật Quảng cáo 16/2012/QH13, sửa đổi bởi Luật 75/2025/QH15 – Điều 19 khoản 1 '
                       '(nội dung quảng cáo phải trung thực, chính xác, rõ ràng)',
    },
    'RULE08': {
        'title': 'Thiếu nhãn nội dung do AI tạo',
        'error_label': 'AI_DISCLOSURE',
        'review_priority': 'Cao',
        'legal_basis': 'Luật Trí tuệ nhân tạo 134/2025/QH15 (hiệu lực 01/03/2026); Nghị định 142/2026/NĐ-CP – '
                       'Điều 18 (gắn nhãn rõ ràng, dễ nhận biết); tham khảo EU AI Act Điều 50',
        'legal_note': 'Điều 18 Nghị định 142/2026 mới đối chiếu qua nguồn thứ cấp.',
    },
    'RULE09': {
        'title': 'Nhãn AI theo quy định nền tảng',
        'error_label': 'AI_DISCLOSURE',
        'review_priority': 'Cao',
        'legal_basis': 'TikTok AI-Generated Content Labeling; Meta "AI info" label',
        'status': 'chưa triển khai',
    },
    'RULE10': {
        'title': 'Nguồn gốc nội dung C2PA',
        'error_label': 'PROVENANCE',
        'review_priority': 'Cao',
        'legal_basis': 'C2PA Technical Specification (Content Credentials)',
        'status': 'chưa triển khai',
    },
}

# Finding code (exact, then prefix) -> rule.
CODE_RULES: dict[str, str] = {
    'CLAIM-01': 'RULE01', 'CLAIM-02': 'RULE01', 'CLAIM-VLM': 'RULE01',
    'INFANT-01': 'RULE02', 'INFANT-02': 'RULE02', 'INFANT-03': 'RULE02',
    'PRICE-01': 'RULE03',
    'SKU-01': 'RULE04', 'TEXT-01': 'RULE04', 'VARIANT-01': 'RULE04',
    'TEXT-02': 'RULE06', 'TEXT-03': 'RULE06', 'VIS-03': 'RULE06',
    'VIS-01': 'RULE07', 'VIS-02': 'RULE07', 'VIS-04': 'RULE07', 'VIS-05': 'RULE07',
    'AI-LABEL-01': 'RULE08',
}


def rule_for(code: str) -> dict | None:
    rule_id = CODE_RULES.get(str(code or ''))
    if not rule_id:
        return None
    rule = RULES[rule_id]
    return {'rule_id': rule_id, 'title': rule['title'], 'error_label': rule['error_label'],
            'review_priority': rule['review_priority'], 'legal_basis': rule['legal_basis'],
            'legal_note': rule.get('legal_note', ''), 'legal_review_required': True,
            'rules_version': RULES_VERSION}
