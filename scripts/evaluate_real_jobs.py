"""Evaluate exported VerifAI evidence files against independently adjudicated labels.

Does not use simulated labels or inferred ground truth. Excludes uncertain cases.
Usage: python scripts/evaluate_real_jobs.py --ground-truth data/ground_truth_verified.csv --exports-dir exports --out reports/real_eval.json
"""
import argparse
import csv
import json
from pathlib import Path
from collections import Counter, defaultdict

YES = {"1", "true", "yes", "error", "có"}
NO = {"0", "false", "no", "clean", "không"}
EXCLUDED = {"COVERAGE", "EVIDENCE-LOW", "VIS-SCREEN", "VIS-06"}
LEVELS = {"high", "medium"}

def label(value):
    value = str(value or "").strip().casefold()
    if value in YES:
        return True
    if value in NO:
        return False
    return None

def run(ground_truth, exports_dir):
    rows = list(csv.DictReader(ground_truth.open(encoding="utf-8-sig", newline="")))
    truth = {}
    for row in rows:
        job_id = (row.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("Ground truth thiếu job_id")
        if job_id in truth:
            raise ValueError("Trùng job_id trong Ground Truth: " + job_id)
        a = label(row.get("actual_error"))
        reviewer1 = (row.get("annotator_1") or "").strip()
        reviewer2 = (row.get("annotator_2") or "").strip()
        l1 = label(row.get("label_1"))
        l2 = label(row.get("label_2"))
        reviewed = (row.get("adjudication_status") or "").casefold().strip() == "verified"
        valid = (a is not None and reviewed and reviewer1 and reviewer2
                 and reviewer1.casefold() != reviewer2.casefold()
                 and l1 is not None and l1 == l2 == a
                 and bool((row.get("source_reference") or "").strip())
                 and bool((row.get("source_group") or "").strip()))
        truth[job_id] = (a, valid, row)

    exported = {}
    for path in sorted(exports_dir.rglob("*.json")):
        try:
            item = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        job_id = str(item.get("job_id") or "").strip()
        if job_id:
            if job_id in exported:
                raise ValueError("Nhiều evidence export cho job_id: " + job_id)
            exported[job_id] = item

    counts = Counter()
    reasons = Counter()
    errors = []
    included = []
    by_source = defaultdict(Counter)
    by_vlm = defaultdict(Counter)
    by_model = defaultdict(Counter)
    for job_id, (actual, valid, gt) in truth.items():
        if not valid:
            reasons["unverified_ground_truth"] += 1
            continue
        item = exported.get(job_id)
        if item is None:
            reasons["missing_evidence_export"] += 1
            continue
        details = item.get("details") or {}
        coverage = details.get("coverage") or {}
        if not any(coverage.get(k) == "ok" for k in ("ocr", "asr")) and coverage.get("vlm") not in ("ok", "partial"):
            reasons["insufficient_model_coverage"] += 1
            continue
        # Evidence exports may contain findings at top-level or in details.
        findings = item.get("findings")
        if findings is None:
            findings = details.get("findings")
        if not isinstance(findings, list):
            reasons["missing_findings"] += 1
            continue
        positive = any(
            isinstance(f, dict)
            and str(f.get("severity", "")).lower() in LEVELS
            and str(f.get("code", "")).upper() not in EXCLUDED
            for f in findings
        )
        key = "tp" if actual and positive else "fn" if actual else "fp" if positive else "tn"
        counts[key] += 1
        source = gt.get("source_group") or "unknown"
        by_source[source][key] += 1
        vlm_bucket = str(coverage.get("vlm") or "unknown")
        by_vlm[vlm_bucket][key] += 1
        model = str((details.get("vlm") or {}).get("model") or "not_recorded")
        by_model[model][key] += 1
        included.append(job_id)
        if key in ("fp", "fn"):
            errors.append({"job_id": job_id, "type": key.upper(),
                           "source_group": source, "notes": gt.get("notes", "")})

    def metrics(c):
        tp, fp, fn, tn = (c[k] for k in ("tp", "fp", "fn", "tn"))
        p = tp / (tp + fp) if tp + fp else None
        r = tp / (tp + fn) if tp + fn else None
        f = 2 * p * r / (p + r) if p is not None and r is not None and (p + r) else None
        n = tp + fp + fn + tn
        accuracy = (tp + tn) / n if n else None
        return {"n": n, "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "accuracy": accuracy, "precision": p, "recall": r, "f1": f}

    return {"policy": "verified-ground-truth-v1", "metrics": metrics(counts),
            "by_source": {k: metrics(v) for k, v in sorted(by_source.items())},
            "by_vlm_coverage": {k: metrics(v) for k, v in sorted(by_vlm.items())},
            "by_model": {k: metrics(v) for k, v in sorted(by_model.items())},
            "excluded": dict(reasons), "error_cases": errors,
            "included_job_ids": included,
            "limitations": [
                "Flags are review candidates, not confirmed violations.",
                "Excluded jobs are NOT counted as true negatives.",
                "Repeated videos are not independent; report source-group breakdown.",
                "Overall candidate metrics include OCR/ASR-only runs; use by_vlm_coverage for VLM-specific claims.",
                "Small sample metrics must not be presented as production performance."
            ]}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--exports-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    report = run(args.ground_truth, args.exports_dir)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"metrics": report["metrics"], "excluded": report["excluded"]}, ensure_ascii=False))
    if not report["metrics"]["n"]:
        print("No verified evaluable cases yet; metrics remain null or unavailable.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
