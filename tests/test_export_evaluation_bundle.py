"""Offline contract tests: no live server and no fabricated review labels."""
import csv
import json
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "export_evaluation_bundle.py"
spec = importlib.util.spec_from_file_location("eval_bundle_export", SCRIPT)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def _fake_get(base, route):
    assert base == "http://127.0.0.1:8001"
    if route == "/api/jobs":
        return [
            {"id": "job001", "status": "completed", "filename": "VID_LOI12.mp4", "sku": "SKU006"},
            {"id": "job002", "status": "completed", "filename": "VID_LOI12.mp4", "sku": "SKU006"},
            {"id": "queued01", "status": "queued", "filename": "other.mp4", "sku": "SKU001"},
        ]
    if route.startswith("/api/jobs/") and route.endswith("/evidence/export"):
        job_id = route.split("/")[3]
        return {
            "job_id": job_id, "schema_version": "verifai-evidence-2.0",
            "details": {"coverage": {"ocr": "ok", "asr": "ok", "vlm": "error"},
                        "vlm": {"model": "gemini-3.5-flash-lite", "calls_succeeded": 0}},
            "findings": [{"code": "SKU-01", "severity": "medium"}],
            "evidence": [],
        }
    raise ValueError("Unexpected route " + route)


def test_export_completed_and_blank_labels(tmp_path):
    output = module.export("http://127.0.0.1:8001", tmp_path, get_json=_fake_get)
    assert output["exported_jobs"] == 2
    assert output["repeated_filename_groups"] == {"VID_LOI12.mp4": 2}
    with (tmp_path / "manifest.csv").open(encoding="utf-8-sig", newline="") as f:
        manifest = list(csv.DictReader(f))
    assert len(manifest) == 2
    assert all(r["model"] == "gemini-3.5-flash-lite" for r in manifest)
    assert all(len(r["evidence_sha256"]) == 64 for r in manifest)
    with (tmp_path / "ground_truth_TO_LABEL.csv").open(encoding="utf-8-sig", newline="") as f:
        draft = list(csv.DictReader(f))
    assert len(draft) == 2
    assert all(not r["actual_error"] and not r["adjudication_status"] for r in draft)
    assert not (tmp_path / "exports" / "verifai-evidence-queued01.json").exists()


def test_export_does_not_overwrite_existing_human_labels(tmp_path):
    module.export("http://127.0.0.1:8001", tmp_path, get_json=_fake_get)
    labels = tmp_path / "ground_truth_TO_LABEL.csv"
    labels.write_text("REVIEWER ENTERED RESULTS", encoding="utf-8")
    module.export("http://127.0.0.1:8001", tmp_path, get_json=_fake_get)
    assert labels.read_text(encoding="utf-8") == "REVIEWER ENTERED RESULTS"


def test_export_refuses_external_hosts(tmp_path):
    with pytest.raises(ValueError, match="Only local HTTP"):
        module.export("https://example.com", tmp_path, get_json=_fake_get)


def test_export_selected_missing_ids_rejected(tmp_path):
    with pytest.raises(ValueError, match="Unknown job IDs"):
        module.export("http://127.0.0.1:8001", tmp_path,
                      job_ids=["unknown"], get_json=_fake_get)
