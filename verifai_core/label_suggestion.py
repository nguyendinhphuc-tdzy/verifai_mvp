"""AI-suggested evaluation label (PO decision 02/11/2026: AI suggests first,
the session reviewer accepts or overrides).

The suggestion is derived only from the stored AI recommendation and findings;
it is never stored as a label by itself. Because the reviewer sees the
suggestion, reviewer labels are NOT independent of the AI: metrics computed from
them measure reviewer agreement, and are reported as such.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

LABEL_SUGGESTION_VERSION = 'label-suggestion-1.0'
NON_CONTENT_CODES = frozenset({'COVERAGE', 'EVIDENCE-LOW', 'VIS-SCREEN', 'VIS-06'})

ERROR_TYPES = {
    'PRICE': 'Sai giá',
    'SKU': 'Sai tên brand / thông tin sản phẩm',
    'TEXT': 'Sai tên brand / thông tin sản phẩm',
    'VARIANT': 'Sai tên brand / thông tin sản phẩm',
    'CLAIM': 'Claim ngoài danh sách được duyệt',
    'VIS-01': 'Không nhất quán hình ảnh',
    'VIS-02': 'Không nhất quán hình ảnh',
    'VIS-03': 'Lỗi hiển thị',
    'AI-LABEL': 'Thiếu nhãn AI',
}


def error_type(code: str) -> str:
    code = str(code or '')
    if code in ERROR_TYPES:
        return ERROR_TYPES[code]
    for prefix, name in ERROR_TYPES.items():
        if code.startswith(prefix):
            return name
    return 'Khác'


def suggest_label(recommendation: Mapping[str, Any] | None,
                  findings: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any] | None:
    if not recommendation:
        return None
    decision = recommendation.get('decision')
    content = [f for f in findings
               if f.get('code') not in NON_CONTENT_CODES
               and f.get('severity') in ('high', 'medium')
               and f.get('flag_review') != 'rejected']
    types = sorted({error_type(f.get('code')) for f in content})
    codes = sorted({str(f.get('code')) for f in content})
    if decision == 'Regenerate':
        label, strength = 'error', 'strong'
        reason = 'AI đề xuất Regenerate: có lỗi mức cao, liên kết bằng chứng OCR/ASR.'
    elif decision == 'Pass':
        label, strength = 'clean', 'strong'
        reason = 'AI đề xuất Pass: không thấy ứng viên lỗi trong phạm vi đã quét.'
    elif content:
        label, strength = 'error', 'weak'
        reason = 'Có ứng viên lỗi nhưng chưa đủ mạnh để đề xuất Regenerate; reviewer cần xác minh.'
    else:
        label, strength = 'uncertain', 'weak'
        reason = 'Không có ứng viên lỗi nhưng độ phủ hoặc Product Truth chưa đủ để đề xuất Pass.'
    return {'version': LABEL_SUGGESTION_VERSION, 'label': label, 'strength': strength,
            'error_types': types, 'codes': codes, 'reason': reason,
            'decision': decision, 'is_ground_truth': False}
