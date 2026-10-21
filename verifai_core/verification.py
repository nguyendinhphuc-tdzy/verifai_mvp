"""Case-level evidence reconciliation for VerifAI v3 Sprint A3.

This is a deterministic reviewer aid, not legal compliance, an accuracy score,
or a replacement for individual findings. Repeated frames from one modality do
not constitute independent confirmation. VLM self-reported confidence is not
used as an authority signal.
"""
from __future__ import annotations

from collections import defaultdict
from copy import deepcopy
from typing import Any, Mapping, Sequence

VERIFICATION_VERSION = 'verification-v3.0-alpha3'


def _field(item: Any, name: str, default: Any = None) -> Any:
    return item.get(name, default) if isinstance(item, dict) else getattr(item, name, default)


def _source(item: Any) -> str:
    kind = str(_field(item, 'kind', ''))
    if kind in ('ocr', 'asr'):
        return kind
    if kind.startswith('vlm'):
        return 'vlm'
    if kind.startswith('visual'):
        return 'visual'
    return 'other'


def _as_dict(meta: Any) -> dict:
    return meta if isinstance(meta, dict) else {}


def _safe_time(item: Any) -> float:
    try:
        return max(0., float(_field(item, 'timestamp', 0) or 0))
    except (TypeError, ValueError):
        return 0.


def _observation(index: int, item: Any) -> dict:
    return {'index': index, 'modality': _source(item),
            'timestamp': _safe_time(item)}


def _summary(kind: str, status: str, reason: str, observations: list[dict],
             values: list[Any] | None = None, phrase: str | None = None) -> dict:
    indices = sorted({x['index'] for x in observations})
    modalities = sorted({x['modality'] for x in observations})
    return {'category': kind, 'status': status, 'reason': reason,
            'phrase': phrase, 'values': values or [],
            'modalities': modalities,
            'evidence_indices': indices,
            'evidence_ids': [],
            'timestamps': sorted({x['timestamp'] for x in observations}),
            'independent_modalities': len(modalities)}


def build_verification_report(evidence: Sequence[Any], findings: Sequence[Mapping[str, Any]],
                              coverage: Mapping[str, str], product_truth: Mapping[str, Any],
                              raw_map: Mapping[str, int] | None = None) -> dict:
    """Reconcile *observations*, not truths, in deterministic canonical order.

    The data comes from A1's ``metadata.price_v3`` and A2's
    ``metadata.claim_v3`` plus existing VLM/visual findings. A reviewer can
    inspect every statement through evidence_indices / evidence_ids.
    """
    raw_map = raw_map or {}
    price_observations: list[dict] = []
    claim_groups: dict[str, list[dict]] = defaultdict(list)
    observed_sources: set[str] = set()
    for i, ev in enumerate(evidence):
        source = _source(ev)
        observed_sources.add(source)
        meta = _as_dict(_field(ev, 'metadata', {}))
        pos = _observation(i, ev)
        price = _as_dict(meta.get('price_v3'))
        if price.get('mentions'):
            price_observations.append({**pos, 'status': price.get('status'),
                                       'amount': price.get('compared_vnd'),
                                       'reason': price.get('reason')})
        claims = _as_dict(meta.get('claim_v3'))
        for mention in claims.get('mentions', []):
            if not isinstance(mention, dict):
                continue
            phrase = str(mention.get('phrase', '')).strip()
            state = mention.get('state')
            if phrase and state in ('asserted', 'negated', 'uncertain'):
                claim_groups[phrase.casefold()].append({**pos, 'state': state,
                                                       'phrase': phrase})

    checks: list[dict] = []
    decisive = [v for v in price_observations
                if v['status'] in ('MATCH', 'MISMATCH')
                and isinstance(v['amount'], int)]
    values = sorted({v['amount'] for v in decisive})
    if len(values) > 1:
        checks.append(_summary('price', 'CONFLICT', 'multiple_observed_prices', decisive, values))
    elif len(values) == 1:
        mismatches = [v for v in decisive if v['status'] == 'MISMATCH']
        matches = [v for v in decisive if v['status'] == 'MATCH']
        group = mismatches or matches
        mods = {v['modality'] for v in group}
        status = 'CANDIDATE' if mismatches else 'CONSISTENT'
        reason = ('independent_sources_agree_on_price_candidate'
                  if mismatches and len(mods) >= 2 else
                  'single_source_price_candidate' if mismatches else
                  'reference_price_observed')
        checks.append(_summary('price', status, reason, group, values))
    elif price_observations:
        checks.append(_summary('price', 'INSUFFICIENT_EVIDENCE',
                               'price_mentions_without_comparable_current_price',
                               price_observations))
    if decisive:
        # A matching on-screen list price does not resolve a separate
        # promotional/ambiguous price elsewhere in the same video.
        unresolved = [v for v in price_observations if v not in decisive]
        if unresolved:
            checks.append(_summary('price', 'INSUFFICIENT_EVIDENCE',
                                   'additional_unresolved_price_mentions', unresolved))

    for key in sorted(claim_groups):
        group = claim_groups[key]
        states = {g['state'] for g in group}
        asserted = [g for g in group if g['state'] == 'asserted']
        if 'asserted' in states and 'negated' in states:
            status, reason, subset = 'CONFLICT', 'mixed_assertion_and_negation', group
        elif asserted:
            status = 'CANDIDATE'
            reason = ('independent_sources_repeat_restricted_claim'
                      if len({g['modality'] for g in asserted}) >= 2
                      else 'restricted_claim_asserted')
            subset = asserted
        else:
            status, reason, subset = 'INSUFFICIENT_EVIDENCE', 'non_asserted_claim_context', group
        checks.append(_summary('claim', status, reason, subset, phrase=group[0]['phrase']))

    # VLM findings are candidates even when multiple frames agree; not a
    # calibrated second vote for OCR/ASR claim or price verification.
    vlm_groups: dict[str, list[dict]] = defaultdict(list)
    visual_flags = []
    unresolved_findings = []
    coverage_codes = {'COVERAGE', 'EVIDENCE-LOW', 'VIS-06'}
    known = {'PRICE-01', 'CLAIM-01'} | coverage_codes
    for finding in findings:
        code = str(finding.get('code', ''))
        meta = _as_dict(finding.get('metadata'))
        index = meta.get('canonical_index')
        if index is None and finding.get('uid') is not None:
            index = raw_map.get(finding['uid'])
        observations = []
        if isinstance(index, int) and 0 <= index < len(evidence):
            observations.append(_observation(index, evidence[index]))
        if str(finding.get('source', '')) == 'vlm':
            vlm_groups[code].extend(observations)
            if not observations:
                vlm_groups[code]  # retain unlinked candidate
        elif code == 'VIS-SCREEN':
            visual_flags.extend(observations)
        elif code not in known and code != 'VIS-SCREEN':
            unresolved_findings.append(code)

    for code in sorted(vlm_groups):
        observations = vlm_groups[code]
        checks.append(_summary('visual', 'CANDIDATE', 'vlm_visual_hypothesis', observations,
                               phrase=code))
    if visual_flags:
        checks.append(_summary('visual', 'INSUFFICIENT_EVIDENCE',
                               'temporal_heuristic_only', visual_flags))
    if unresolved_findings:
        checks.append(_summary('other', 'CANDIDATE', 'other_findings_require_review', [],
                               values=sorted(set(unresolved_findings))))

    raw_coverage = {k: str(coverage.get(k, 'unknown')) for k in ('ocr', 'asr', 'vlm')}
    incomplete = sorted(k for k, state in raw_coverage.items() if state != 'ok')
    reference_status = str(product_truth.get('reference_status') or 'unverified')
    reference_reviewed = reference_status == 'reviewed'
    candidate = any(c['status'] in ('CANDIDATE', 'CONFLICT') for c in checks)
    # If a serious finding exists without a linked evidence record, never hide it.
    if not candidate:
        candidate = any(f.get('code') not in coverage_codes | {'VIS-SCREEN'}
                        for f in findings)
    low_evidence = any(f.get('code') in coverage_codes for f in findings)
    ambiguous = any(c['status'] == 'INSUFFICIENT_EVIDENCE' for c in checks)
    if candidate:
        status, reason = 'REVIEW_REQUIRED', 'candidate_or_conflict_requires_human_review'
    elif incomplete or not reference_reviewed or low_evidence or ambiguous:
        status, reason = 'INSUFFICIENT_EVIDENCE', 'missing_model_coverage_or_unreviewed_truth'
    else:
        status, reason = 'NO_ISSUES_OBSERVED', 'no_candidate_with_available_coverage'

    return {
        'version': VERIFICATION_VERSION,
        'status': status,
        'reason': reason,
        'requires_human_review': True,  # never auto-pass/reject in A3
        'is_final_decision': False,
        'coverage': raw_coverage,
        'incomplete_modules': incomplete,
        'reference_status': reference_status,
        'reference_revision': product_truth.get('revision'),
        'observed_modalities': sorted(observed_sources),
        'checks': checks,
        'candidate_count': sum(c['status'] == 'CANDIDATE' for c in checks),
        'conflict_count': sum(c['status'] == 'CONFLICT' for c in checks),
    }


def attach_evidence_ids(report: dict, inserted_ids: Sequence[int]) -> dict:
    """Link canonical indices to newly committed per-job SQLite evidence IDs."""
    linked = deepcopy(report)
    for check in linked.get('checks', []):
        check['evidence_ids'] = [inserted_ids[i] for i in check['evidence_indices']
                                 if isinstance(i, int) and 0 <= i < len(inserted_ids)]
    return linked
