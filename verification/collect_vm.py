"""Collect narrow real-VM observations; log consistency is not Host acceptance."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

from acceptance import REQUIRED, reject_constant, unique_object

CLAIMS = {
    "E01": ("vm-session-smoke",),
    "E02": ("real-bcon-wheel", "real-bcon-viewer"),
    "E03": ("real-bcon-wheel", "real-bcon-viewer"),
    "E04": ("vm-session-smoke",),
    "E07": ("viewer-ctrl-q-outcome", "viewer-failed-attach-negative-control", "real-bcon-viewer"),
    "E08": ("remote-localhost-preview",),
}
KNOWN = set().union(*(set(v) for v in CLAIMS.values()))
MAX_LOG_BYTES = 10 * 1024 * 1024
# Read the raw Nix log, not echoed shell commands or GitHub's timestamped log.
LINE = re.compile(r"^\s*(?:(?:vm-test-run-)?browser-host-session> )?(\{.*)$")


def observed(event: Any) -> bool:
    if type(event) is not dict or type(event.get("test")) is not str or event["test"] not in KNOWN:
        return False
    if "status" in event and event["status"] != "PASS":
        return False
    if event["test"] == "viewer-ctrl-q-outcome":
        return event.get("exit") == "0" and event.get("stderr") == ""
    if event["test"] == "viewer-failed-attach-negative-control":
        return event.get("exit") == "1" and type(event.get("stderr")) is str and (
            "connection, terminal or frame rejected" in event["stderr"])
    return (event.get("status") == "PASS" and event.get("preapply") == "NOT_PROVEN"
            and type(event.get("scope")) is str and bool(event["scope"].strip()))


def collect(raw: bytes, source_sha: str, vm_outcome: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if type(source_sha) is not str or not re.fullmatch("[0-9a-f]{40}", source_sha):
        raise ValueError("invalid-source-sha")
    if vm_outcome not in ("success", "failure", "cancelled", "skipped", "unknown"):
        raise ValueError("invalid-vm-outcome")
    if type(raw) is not bytes or len(raw) > MAX_LOG_BYTES:
        raise ValueError("invalid-or-oversized-vm-log")
    errors = set()
    try:
        text = raw.decode("utf-8")
    except UnicodeError:
        text = ""
        errors.add("invalid-utf8")
    # Saturated counts keep memory bounded even if a log repeats a known case.
    found = {key: (0, False) for key in KNOWN}
    for line in text.splitlines():
        match = LINE.fullmatch(line)
        if not match:
            continue
        try:
            event = json.loads(match[1], object_pairs_hook=unique_object, parse_constant=reject_constant)
        except (ValueError, RecursionError):
            errors.add("invalid-json-record")
            continue
        if type(event) is not dict or "test" not in event:
            continue
        key = event["test"]
        if type(key) is not str:
            errors.add("invalid-test-id")
        elif key in found:
            count, _ = found[key]
            found[key] = (min(2, count + 1), observed(event))
    executed = vm_outcome in ("success", "failure")
    digest = hashlib.sha256(raw).hexdigest()
    rows = []
    for name in REQUIRED:
        selected = CLAIMS.get(name, ())
        checks = {key: executed and not errors and found[key] == (1, True) for key in selected}
        # Earlier partial observations survive later VM failure, not log corruption.
        rows.append({
            "id": name, "status": "PARTIAL_OBSERVED" if selected and all(checks.values()) else "NOT_PROVEN",
            "scope": "vm-log-only", "source_sha": source_sha,
            "vm_outcome": vm_outcome, "log_sha256": digest,
            "cases": {key: "OBSERVED" if value else "NOT_PROVEN" for key, value in checks.items()},
            "collection_errors": sorted(errors),
            "full_acceptance": "NOT_PROVEN", "hardware_apply": "NOT_PROVEN",
        })
    return rows, [dict(row) for row in rows if row["full_acceptance"] == "NOT_PROVEN"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--log", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--vm-outcome", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        with args.log.open("rb") as handle:
            raw = handle.read(MAX_LOG_BYTES + 1)
        rows, gaps = collect(raw, args.source_sha, args.vm_outcome)
        args.output.mkdir(parents=True, exist_ok=False)
        for name, selected in (("raws", rows), ("disruptives", gaps)):
            (args.output / (name + ".jsonl")).write_text(
                "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in selected),
                encoding="utf-8")
        print(json.dumps({"scope": "partial-vm", "source_sha": args.source_sha,
                          "vm_outcome": args.vm_outcome,
                          "observed": sum(row["status"] == "PARTIAL_OBSERVED" for row in rows),
                          "collection_errors": rows[0]["collection_errors"],
                          "full": "NOT_PROVEN"}, sort_keys=True))
        return 2 if rows[0]["collection_errors"] else 0
    except (OSError, ValueError, RecursionError):
        # Never expose paths or arbitrary exception/input text to public logs.
        print(json.dumps({"scope": "partial-vm", "full": "NOT_PROVEN",
                          "error": "invalid-or-unreadable-vm-evidence"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
