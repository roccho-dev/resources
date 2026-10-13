# SPDX-License-Identifier: GPL-3.0-or-later
"""Audit downloaded C evidence using the existing, unchanged acceptance rules."""
import json
import re
from pathlib import Path
from evidence import LIMIT, read_json, assess, catalog, artifact_errors, digest


def verify_context(root: Path, pins: dict) -> dict:
    """Recompute the saved VM identity. Identity is not supplier agreement."""
    context = read_json(root / "context.json")
    observed = read_json(root / "inputs.json")
    environment = read_json(root / "environment.json")
    if (type(observed) is not dict or set(observed) != {"pins", "executables", "meta"}
            or type(environment) is not dict or set(environment) != {"meta", "kernel", "system"}
            or type(observed["meta"]) is not dict or type(observed["pins"]) is not dict
            or environment["meta"] != observed["meta"]
            or any(type(environment[k]) is not str or not environment[k].strip() for k in ("kernel", "system"))
            or not environment["kernel"].startswith("Linux ")
            or observed["meta"].get("system") != "x86_64-linux"):
        raise ValueError("saved-environment-invalid")
    if (context != {"code": observed["meta"].get("code"),
            "inputs": digest({"pins": observed["pins"], "executables": observed["executables"]}),
            "environment": digest(environment)}):
        raise ValueError("saved-context-not-reproducible")
    if set(observed["pins"]) != {"A", "B", "terminal"} or set(pins) != {"A", "B", "terminal"}:
        raise ValueError("saved-supplier-set-mismatch")
    binaries = {}
    if type(observed["executables"]) is not str:
        raise ValueError("saved-executables-invalid")
    for line in observed["executables"].splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (/nix/store/[^ ]+/bin/(?:cdp-tty|meltype-tty|bcon))", line)
        if not match or match[2] in binaries:
            raise ValueError("saved-executables-invalid")
        binaries[match[2]] = match[1]
    expected_paths = set()
    for name, executable in (("A", "cdp-tty"), ("B", "meltype-tty"), ("terminal", "bcon")):
        actual, expected = observed["pins"][name], pins[name]
        if (type(actual) is not dict or set(actual) != {"rev", "narHash", "drvPath", "outputPath"}
                or re.fullmatch(r"[0-9a-f]{40}", expected.get("rev", "")) is None
                or re.fullmatch(r"sha256-[A-Za-z0-9+/]{43}=", expected.get("narHash", "")) is None
                or any(actual.get(k) != expected[k] for k in ("rev", "narHash"))
                or type(actual["outputPath"]) is not str or not actual["outputPath"].startswith("/nix/store/")
                or type(actual["drvPath"]) is not str or not actual["drvPath"].startswith("/nix/store/")
                or not actual["drvPath"].endswith(".drv")):
            raise ValueError("saved-supplier-identity-mismatch:" + name)
        expected_paths.add(actual["outputPath"] + "/bin/" + executable)
    if set(binaries) != expected_paths:
        raise ValueError("saved-executable-output-mismatch")
    return {"observedSourcePins": ["A", "B", "terminal"],
        "contextRecomputed": True, "scope": "same-ci-vm-only",
        "supplierAgreement": "NOT_INFERRED", "physicalEquivalence": "NOT_PROVEN"}


def verify_saved(root: Path, original: Path) -> dict:
    """Verify downloaded artifact bytes against this run; never grant admission."""
    for name in ("context.json", "raws.jsonl", "assessment.json", "inputs.json", "environment.json"):
        saved, produced = root / name, original / name
        if (saved.is_symlink() or not saved.is_file() or not produced.is_file()
                or saved.stat().st_size > LIMIT or produced.stat().st_size > LIMIT
                or saved.read_bytes() != produced.read_bytes()):
            raise ValueError("saved-run-file-mismatch:" + name)
    material = verify_context(root, read_json(Path(__file__).with_name("pins.json")))
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
        "material": material, "vmCases": len(required), "referencedFiles": len({
            item["path"] for row in rows for item in row["artifacts"]}),
        "missingAcceptance": [row["case"] for row in report["cases"]
            if row["status"] != "CONSISTENT"],
        "admission": "NOT_PERFORMED", "upstreamAgreement": "NOT_INFERRED"}


