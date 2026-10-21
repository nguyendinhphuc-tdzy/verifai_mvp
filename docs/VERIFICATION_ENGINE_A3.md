# Sprint A3 — Evidence Verification Engine (v3-alpha3)

## Intent and boundaries

A3 adds a **deterministic, inspectable, case-level report** on top of A1 Price Parser and A2 Product Truth/Claim Verification. It operates on existing normalized evidence and findings produced by the real pipeline. It does **not** certify a video, detect generated footage conclusively, override the reviewer, or replace source-specific findings.

The verification report is a *snapshot of analysis-time data*. Older completed jobs do not automatically gain an A3 report.

## Status contract

| Status | Meaning | Human handling |
|---|---|---|
| `REVIEW_REQUIRED` | At least one candidate or conflicting observation warrants a review | Inspect linked evidence before making a decision |
| `INSUFFICIENT_EVIDENCE` | Missing OCR/ASR/VLM coverage, unreviewed Product Truth, ambiguous price/claim context or low-quality evidence, without stronger candidate | Recheck video manually; optionally improve references/models and re-analyze |
| `NO_ISSUES_OBSERVED` | No issue candidate in the **available, successful** OCR/ASR/VLM checks using a manually reviewed reference | **Not** an approval, safety guarantee or evidence of complete detection |

Every status includes `requires_human_review=true`, `is_final_decision=false`. Neither A3 nor a VLM report sets a final `Pass` or `Regenerate`.

**Interpretation:** The labels are reviewer guidance, not probabilistic confidence or model accuracy. Two agreeing modalities are two observations, *not proof* the detected fact is true.

## Reconciliation rules

1. **Price:** Read `evidence.metadata.price_v3` and group **comparable** current-price observations. A1 `MATCH` and `MISMATCH` observations with different amounts create `CONFLICT: multiple_observed_prices`. Identical mismatches across OCR and ASR become a `CANDIDATE` with two observed modalities. Repeated OCR frames alone remain one modality.
2. **Claim:** Read `evidence.metadata.claim_v3.mentions` and group by exact case-insensitive claim phrase. Asserted + negated contexts create `CONFLICT: mixed_assertion_and_negation`. Repeated asserted phrases make a `CANDIDATE`; negated/uncertain-only contexts remain `INSUFFICIENT_EVIDENCE`. This is *not* natural-language entailment or semantic equivalence.
3. **Visual:** Existing VLM issue findings remain `CANDIDATE` linked to VLM evidence. OpenCV temporal `VIS-SCREEN` alone is insufficient visual proof; it never becomes independent VLM confirmation.
4. **Coverage/reference:** Missing `ocr/asr/vlm=ok`, Product Truth not marked `reviewed`, an `EVIDENCE-LOW/COVERAGE/VIS-06` finding or ambiguous sub-check prevents a no-issues conclusion unless a stronger review candidate already exists.
5. **Unknown future findings:** Keep unexpected codes as review candidates rather than silently discarding them.

Multiple values or opposite claim contexts from different times may reflect price changes, promotions or quoting, **not actual contradictory product truth**. The engine says there are **different observations**, not who is correct.

## Storage and API

- `GET /api/jobs/{job_id}`: new `details.verification` report with version, status, check list, conflict/candidate counts, completeness, Product Truth revision, and canonical evidence links.
- `GET /api/jobs/{job_id}/verification`: read-only A3 report. Returns `409` while unfinished; `404` for an older job without verification, rather than inventing a result.
- `GET /api/jobs/{job_id}/evidence/export`: retains schema `verifai-evidence-2.0`, including the new `details.verification`; old export consumers continue to see existing properties.
- Reports are computed once during analysis, **after** A1/A2 rules and normalized evidence, and use the actual SQLite evidence IDs returned during insertion. Every `check.evidence_ids` points to persisted canonical evidence.
- `analysis_completed` audit adds `verification_status` and conflict count.
- No database migration, no additional AI dependencies, and no change to approved human review endpoints.

Example report:

```json
{
  "version": "verification-v3.0-alpha3",
  "status": "REVIEW_REQUIRED",
  "requires_human_review": true,
  "is_final_decision": false,
  "candidate_count": 0,
  "conflict_count": 1,
  "checks": [
    {
      "category": "price",
      "status": "CONFLICT",
      "reason": "multiple_observed_prices",
      "values": [99000, 149000],
      "modalities": ["asr", "ocr"],
      "evidence_indices": [0, 3],
      "evidence_ids": [41, 44],
      "timestamps": [0.0, 2.0],
      "independent_modalities": 2,
      "phrase": null
    }
  ]
}
```

## Review workflow and test contract

In Review Queue, the summary above findings shows the case-level result and a count of candidate/conflict categories. Expand **Giải thích kết quả kiểm tra** to see the reasoning and jump directly to evidence. All source findings and manual Confirm/Reject actions remain.

```powershell
cd C:\Users\PC\Documents\verifai_mvp
git fetch origin
git switch feature/a3-evidence-verification-engine
git pull
python -m pytest -q tests/test_verification_a3.py tests/test_verification_api_a3.py
python -m pytest -q
```

The engine's 18 deterministic unit cases have been run locally and pass. API integration tests are included but **the complete A2+A3 Windows regression must be run on the user's Windows environment**. Test one real product/video with matching price, one with conflicting price in OCR vs ASR, one negated claim, and one VLM-related frame candidate.

## Honest limitations

- String/rule-based price and claim understanding is only as good as the OCR/ASR input. Voice/text transcription can be noisy.
- Conflict detection is global to one video. Two different prices at different timestamps can be legitimate promotions or different products. A3 **does not** perform SKU tracking or infer that either value is illegal.
- Independent modalities mean source labels differ, not that their real-world errors are independent. Confidence is uncalibrated, so A3 does not compute a confidence percentage.
- Product Truth `reviewed` is operator self-attested, not a verified trusted external feed.
- The list of `checks` is an explainable summary of A1/A2/VLM findings, not a semantic compliance or legal judgment.
- A3 report is generated at analysis time and does not change when the reviewer confirms/rejects findings. `review_decision` remains separate.
- Re-analyze overwrites the job's previous evidence/findings/report and clears prior reviewer decisions; **export the old evidence first** if you need it for comparison or audit.
