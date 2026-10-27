"""Export *completed* local VerifAI jobs into a reproducible evaluation bundle.

This tool never invents Ground Truth. It creates a BLANK labeling worksheet
alongside evidence and a machine-readable manifest. Do not commit exports:
they may contain private media metadata, claim text and reference URLs.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

LABEL_COLUMNS = (
    "job_id", "source_group", "source_reference", "annotator_1",
    "label_1", "annotator_2", "label_2", "adjudication_status",
    "actual_error", "notes",
)
MANIFEST_COLUMNS = (
    "job_id", "filename", "sku", "status", "source_group",
    "model", "ocr_coverage", "asr_coverage", "vlm_coverage",
    "vlm_calls_succeeded", "finding_count", "evidence_sha256",
)


def _local_url(url: str) -> str:
    url = url.rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "http" or parts.hostname not in ("127.0.0.1", "localhost"):
        raise ValueError("Only local HTTP localhost/127.0.0.1 API is supported")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError("Invalid base URL")
    return url


def _get_json(base_url: str, endpoint: str, timeout: int = 30):
    with urlopen(base_url + endpoint, timeout=timeout) as response:
        result = json.load(response)
    return result


def _atomic_json(path: Path, payload: dict) -> str:
    encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, delete=False) as f:
        f.write(encoded)
        temp = Path(f.name)
    os.replace(temp, path)
    return hashlib.sha256(encoded).hexdigest()


def _write_csv(path: Path, fields, rows) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def export(base_url: str, out_dir: Path, *, job_ids=None, overwrite=False, get_json=_get_json):
    base_url = _local_url(base_url)
    jobs = get_json(base_url, "/api/jobs")
    if not isinstance(jobs, list):
        raise ValueError("Unexpected /api/jobs response")
    requested = set(job_ids or ())
    if requested:
        missing = requested - {str(row.get("id", "")) for row in jobs}
        if missing:
            raise ValueError("Unknown job IDs: " + ", ".join(sorted(missing)))
    completed = [j for j in jobs if j.get("status") == "completed"
                 and (not requested or str(j["id"]) in requested)]
    completed.sort(key=lambda x: str(x["id"]))
    exports_dir = out_dir / "exports"
    exports_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    drafts = []
    filenames = Counter(j.get("filename", "") for j in completed)
    for job in completed:
        job_id = str(job["id"])
        # Treat identifiers as opaque IDs, never trusted filesystem paths.
        if not (3 <= len(job_id) <= 80 and all(c.isascii() and (c.isalnum() or c in "-_") for c in job_id)):
            raise ValueError("Unsafe job id in API response")
        path = exports_dir / f"verifai-evidence-{job_id}.json"
        if path.exists() and not overwrite:
            payload = json.loads(path.read_text(encoding="utf-8-sig"))
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        else:
            payload = get_json(base_url, f"/api/jobs/{job_id}/evidence/export")
            if payload.get("job_id") != job_id or not isinstance(payload.get("findings"), list):
                raise ValueError("Invalid evidence payload for job " + job_id)
            digest = _atomic_json(path, payload)
        if payload.get("job_id") != job_id:
            raise ValueError("Evidence job ID mismatch for " + job_id)
        details = payload.get("details") or {}
        coverage = details.get("coverage") or {}
        vlm = details.get("vlm") or {}
        model = vlm.get("model") or ""
        manifest.append({
            "job_id": job_id, "filename": job.get("filename", ""),
            "sku": job.get("sku", ""), "status": job.get("status", ""),
            "source_group": "", "model": model,
            "ocr_coverage": coverage.get("ocr", ""),
            "asr_coverage": coverage.get("asr", ""),
            "vlm_coverage": coverage.get("vlm", ""),
            "vlm_calls_succeeded": vlm.get("calls_succeeded", 0),
            "finding_count": len(payload.get("findings", [])),
            "evidence_sha256": digest,
        })
        drafts.append({k: job_id if k == "job_id" else "" for k in LABEL_COLUMNS})
    _write_csv(out_dir / "manifest.csv", MANIFEST_COLUMNS, manifest)
    # Never overwrite human labels; create an onboarding draft only.
    labeling_path = out_dir / "ground_truth_TO_LABEL.csv"
    if not labeling_path.exists():
        _write_csv(labeling_path, LABEL_COLUMNS, drafts)
    result = {
        "exported_jobs": len(manifest),
        "unique_source_filenames": len(filenames),
        "repeated_filename_groups": {k: v for k, v in filenames.items() if v > 1},
        "manifest": str(out_dir / "manifest.csv"),
        "labeling_draft": str(labeling_path),
        "warning": "Ground Truth has NOT been verified. Same filename may be repeated submissions.",
    }
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8001")
    p.add_argument("--out-dir", type=Path, default=Path("evaluation_bundle"))
    p.add_argument("--job-ids", nargs="*", default=[])
    p.add_argument("--overwrite", action="store_true",
                   help="Explicitly replace old evidence exports with the latest job snapshot")
    a = p.parse_args()
    result = export(a.base_url, a.out_dir, job_ids=a.job_ids, overwrite=a.overwrite)
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
