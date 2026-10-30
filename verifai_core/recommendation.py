"""Conservative three-way AI review suggestion, never a final human decision.

Pass means "no issues observed *within analyzed coverage*" on a reviewed
reference. It does NOT certify regulatory compliance or video authenticity.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

DECISIONS = ('Pass', 'Needs Review', 'Regenerate')
COVERAGE_MODULES = ('ocr', 'asr', 'vlm')


def recommend_ai(
    verification: Mapping[str, Any] | None,
    findings: Sequence[Mapping[str, Any]] = (),
) -> dict[str, Any]:
    """Deterministic AI recommendation from stored verification and findings.

    A severe/high-priority deterministic finding recommends Regenerate only
    when evidence-linked; VLM-only hypotheses can never force Regenerate.
    """
    report = verification if isinstance(verification, Mapping) else {}
    coverage = report.get('coverage') or {}
    status = str(report.get('status') or '')
    high = [
        f for f in findings
        if f.get('severity') == 'high'
        and f.get('source') not in ('vlm', 'visual_heuristic')
        and (f.get('evidence_id') is not None or f.get('evidence_refs'))
        and f.get('flag_review') != 'rejected'
    ]
    if high and report.get('reference_status') == 'reviewed' and all(
            coverage.get(m) == 'ok' for m in COVERAGE_MODULES):
        return {
            'decision': 'Regenerate',
            'reason': 'evidence_linked_high_severity_findings',
            'explanation': (
                'Có cảnh báo mức cao có liên kết bằng chứng, cần reviewer xem lại '
                'trước khi yêu cầu sửa hoặc tạo lại video.'
            ),
            'is_final_decision': False,
        }
    if not report:
        return {
            'decision': 'Needs Review',
            'reason': 'verification_not_available',
            'explanation': 'Chưa có báo cáo kiểm chứng; cần phân tích hoặc kiểm tra thủ công.',
            'is_final_decision': False,
        }
    if status in ('REVIEW_REQUIRED',):
        return {
            'decision': 'Needs Review',
            'reason': 'finding_or_conflict_requires_review',
            'explanation': 'Có ứng viên lỗi hoặc tín hiệu xung đột cần người duyệt xác minh.',
            'is_final_decision': False,
        }
    if report.get('reference_status') != 'reviewed':
        return {
            'decision': 'Needs Review',
            'reason': 'product_truth_unverified',
            'explanation': (
                'Chưa phát hiện lỗi rõ ràng, nhưng Product Truth chưa được xem xét nguồn. '
                'Cần xác nhận tham chiếu rồi phân tích lại để cân nhắc Pass.'
            ),
            'is_final_decision': False,
        }
    incomplete = [m for m in COVERAGE_MODULES if coverage.get(m) != 'ok']
    if incomplete:
        return {
            'decision': 'Needs Review',
            'reason': 'incomplete_ai_coverage',
            'explanation': 'Nguồn kiểm tra chưa đầy đủ: ' + ', '.join(incomplete) + '.',
            'is_final_decision': False,
        }
    if status == 'NO_ISSUES_OBSERVED' and not findings:
        return {
            'decision': 'Pass',
            'reason': 'no_issues_in_checked_scope',
            'explanation': (
                'Chưa phát hiện ứng viên lỗi trong phạm vi các module đã chạy '
                'với Product Truth đã được xem xét nguồn. Chỉ là đề xuất AI; '
                'reviewer vẫn phải xem video và ra quyết định cuối.'
            ),
            'is_final_decision': False,
        }
    return {
        'decision': 'Needs Review',
        'reason': 'insufficient_evidence_or_unresolved_findings',
        'explanation': 'Chưa đủ cơ sở để đề xuất Pass; cần người duyệt kiểm tra.',
        'is_final_decision': False,
    }
