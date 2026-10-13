# SPDX-License-Identifier: GPL-3.0-or-later
"""Audit downloaded C evidence using the existing, unchanged acceptance rules."""
import json
from pathlib import Path
from evidence import LIMIT, read_json, assess, catalog, artifact_errors


def verify_saved(root: Path, original: Path) -> dict:
    """Verify downloaded artifact bytes against this run; never grant admission."""
    for name in ("context.json", "raws.jsonl", "assessment.json", "inputs.json"):
        saved, produced = root / name, original / name
        if (saved.is_symlink() or not saved.is_file() or not produced.is_file()
                or saved.stat().st_size > LIMIT or produced.stat().st_size > LIMIT
                or saved.read_bytes() != produced.read_bytes()):
            raise ValueError("saved-run-file-mismatch:" + name)
    expected = read_json(original / "context.json")
    rows = read_json(root / "raws.jsonl", lines=True)
    report = assess(expected, rows, root)
    required = {name for name, spec in catalog()["cases"].items() if spec["scope"] == "vm"}
    failures = [row for row in report["cases"]
        if row["case"] in required and row["status"] != "CONSISTENT"]
    if report["errors"] or failures or artifact_errors(root, rows):
        raise ValueError("saved-evidence-invalid:" + json.dumps({
            "errors": report["errors"], "vm": failures}, sort_keys=True))
    if report != read_json(root / "assessment.json"):
        raise ValueError("saved-assessment-mismatch")
    return {"gate": "C_SAVED_EVIDENCE_ONLY", "status": "PASS",
        "vmCases": len(required), "referencedFiles": len({
            item["path"] for row in rows for item in row["artifacts"]}),
        "missingAcceptance": [row["case"] for row in report["cases"]
            if row["status"] != "CONSISTENT"],
        "admission": "NOT_PERFORMED", "upstreamAgreement": "NOT_INFERRED"}


