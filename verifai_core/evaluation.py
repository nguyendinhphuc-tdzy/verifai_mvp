"""One shared Actual Evaluation policy for VerifAI's job-level and dataset APIs.

A prediction means an *evidence-backed candidate flag*, not a confirmed breach.
Never import simulated labels into a performance numerator or denominator.
"""
from __future__ import annotations
from collections.abc import Iterable, Mapping
from typing import Any

EXCLUDED_CODES = frozenset({'COVERAGE', 'EVIDENCE-LOW', 'VIS-SCREEN', 'VIS-06'})
POSITIVE_SEVERITIES = frozenset({'high', 'medium'})
EVAL_POLICY = 'candidate-v1-2026-10'


def predicted_error(findings: Iterable[Mapping[str, Any]]) -> bool:
    return any(str(f['severity']) in POSITIVE_SEVERITIES
               and str(f['code']) not in EXCLUDED_CODES for f in findings)


def sufficient_coverage(coverage: Mapping[str, Any]) -> bool:
    return (coverage.get('ocr') == 'ok' or coverage.get('asr') == 'ok'
            or coverage.get('vlm') in ('ok', 'partial'))


def independent_consensus(rows: Iterable[Mapping[str, Any]]) -> str | None:
    """Require >=2 distinct annotator names, no 'uncertain' or contradictory labels.

    Multiple rows by the same annotator must not masquerade as consensus.
    """
    labels: dict[str, str] = {}
    for item in rows:
        annotator = str(item['annotator']).strip().casefold()
        label = str(item['label']).strip().casefold()
        if not annotator or label not in ('clean', 'error'):
            return None
        if annotator in labels and labels[annotator] != label:
            return None
        labels[annotator] = label
    if len(labels) < 2 or len(set(labels.values())) != 1:
        return None
    return next(iter(labels.values()))


def calculate_metrics(samples: Iterable[tuple[bool, bool]]) -> dict[str, Any]:
    pairs = list(samples)
    tp = sum(actual and predicted for actual, predicted in pairs)
    fp = sum(not actual and predicted for actual, predicted in pairs)
    tn = sum(not actual and not predicted for actual, predicted in pairs)
    fn = sum(actual and not predicted for actual, predicted in pairs)
    return {
        'evaluated': len(pairs), 'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
        'precision': round(tp/(tp+fp), 3) if tp+fp else None,
        'recall': round(tp/(tp+fn), 3) if tp+fn else None,
        'f1': round(2*tp/(2*tp+fp+fn), 3) if (2*tp+fp+fn) else None,
        'prediction_policy': EVAL_POLICY,
    }
