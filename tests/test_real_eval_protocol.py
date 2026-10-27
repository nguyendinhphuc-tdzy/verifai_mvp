import csv
import importlib.util
import json
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("real_eval", Path(__file__).resolve().parents[1] / "scripts" / "evaluate_real_jobs.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)

FIELDS = ["job_id", "source_group", "source_reference", "annotator_1", "label_1",
          "annotator_2", "label_2", "adjudication_status", "actual_error", "notes"]

def write_ground_truth(path, records):
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(records)

def base_row(job_id, actual):
    return dict(job_id=job_id, source_group="group-A", source_reference="https://example.org/reference",
                annotator_1="Alice", label_1=actual, annotator_2="Bob", label_2=actual,
                adjudication_status="verified", actual_error=actual, notes="")

def test_true_positive_and_false_negative(tmp_path):
    labels = tmp_path / "labels.csv"
    exports = tmp_path / "exports"
    exports.mkdir()
    write_ground_truth(labels, [base_row("job1", "error"), base_row("job2", "error")])
    (exports / "job1.json").write_text(json.dumps({
        "job_id": "job1", "details": {"coverage": {"ocr": "ok"}},
        "findings": [{"severity": "medium", "code": "PRICE-01"}]}))
    (exports / "job2.json").write_text(json.dumps({
        "job_id": "job2", "details": {"coverage": {"ocr": "ok"}}, "findings": []}))
    result = module.run(labels, exports)
    assert result["metrics"]["tp"] == 1
    assert result["metrics"]["fn"] == 1
    assert result["metrics"]["precision"] == 1.0
    assert result["metrics"]["recall"] == 0.5

def test_unverified_labels_and_missing_coverage_excluded(tmp_path):
    labels = tmp_path / "labels.csv"
    exports = tmp_path / "exports"
    exports.mkdir()
    a = base_row("a", "clean")
    a["label_2"] = "error"
    b = base_row("b", "clean")
    write_ground_truth(labels, [a, b])
    (exports / "b.json").write_text(json.dumps({
        "job_id": "b", "details": {"coverage": {"ocr": "disabled", "vlm": "error"}},
        "findings": []}))
    result = module.run(labels, exports)
    assert result["metrics"]["n"] == 0
    assert result["excluded"] == {"unverified_ground_truth": 1, "insufficient_model_coverage": 1}

def test_duplicate_jobs_in_ground_truth_rejected(tmp_path):
    labels = tmp_path / "labels.csv"
    exports = tmp_path / "exports"
    exports.mkdir()
    write_ground_truth(labels, [base_row("dup", "clean"), base_row("dup", "clean")])
    import pytest
    with pytest.raises(ValueError, match="Trùng job_id"):
        module.run(labels, exports)
