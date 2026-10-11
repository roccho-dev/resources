"""Collect narrow real-VM proof references, never declare full Host acceptance."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

CLAIMS = {
    "E01": ("vm-session-smoke",),
    "E02": ("real-bcon-wheel", "real-bcon-viewer"),
    "E03": ("real-bcon-wheel", "real-bcon-viewer"),
    "E04": ("vm-session-smoke",),
    "E07": ("viewer-ctrl-q-outcome", "viewer-failed-attach-negative-control", "real-bcon-viewer"),
    "E08": ("remote-localhost-preview",),
}
KNOWN = set().union(*(set(v) for v in CLAIMS.values()))

def observed(event: Any) -> bool:
    if not isinstance(event, dict) or event.get("test") not in KNOWN:
        return False
    if event["test"] == "viewer-ctrl-q-outcome":
        return event.get("exit") == "0" and event.get("stderr") == ""
    if event["test"] == "viewer-failed-attach-negative-control":
        return event.get("exit") == "1" and isinstance(event.get("stderr"), str) and (
            "connection, terminal or frame rejected" in event["stderr"])
    return (event.get("status") == "PASS" and event.get("preapply") == "NOT_PROVEN"
            and isinstance(event.get("scope"), str) and bool(event["scope"]))

def collect(raw: bytes, source_sha: str, vm_outcome: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not re.fullmatch("[0-9a-f]{40}", source_sha):
        raise ValueError("invalid-source-sha")
    if vm_outcome not in ("success", "failure", "cancelled", "skipped", "unknown"):
        raise ValueError("invalid-vm-outcome")
    found: dict[str, list[bool]] = {key: [] for key in KNOWN}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        at = line.find('{"test":')
        if at < 0:
            continue
        try:
            event, _ = json.JSONDecoder().raw_decode(line[at:])
        except (TypeError, ValueError):
            continue
        if isinstance(event, dict) and event.get("test") in KNOWN:
            found[event["test"]].append(observed(event))
    rows = []
    for index in range(1, 13):
        name = f"E{index:02d}"
        selected = CLAIMS.get(name, ())
        checks = {key: len(found[key]) == 1 and found[key][0] for key in selected}
        # Observations preceding a later failure remain useful. Never promote to full.
        rows.append({
            "id": name, "status": "PARTIAL_OBSERVED" if selected and all(checks.values()) else "NOT_PROVEN",
            "scope": "vm-log-only", "source_sha": source_sha,
            "vm_outcome": vm_outcome, "log_sha256": hashlib.sha256(raw).hexdigest(),
            "cases": {key: "OBSERVED" if value else "NOT_PROVEN" for key, value in checks.items()},
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
        raw = args.log.read_bytes()
        if len(raw) > 10 * 1024 * 1024:
            raise ValueError("vm-log-too-large")
        rows, gaps = collect(raw, args.source_sha, args.vm_outcome)
        args.output.mkdir(parents=True, exist_ok=False)
        for name, selected in (("raws", rows), ("disruptives", gaps)):
            (args.output / (name + ".jsonl")).write_text(
                "".join(json.dumps(row, sort_keys=True) + "\n" for row in selected),
                encoding="utf-8")
        print(json.dumps({"scope": "partial-vm", "source_sha": args.source_sha,
                          "vm_outcome": args.vm_outcome,
                          "observed": sum(row["status"] == "PARTIAL_OBSERVED" for row in rows),
                          "full": "NOT_PROVEN"}, sort_keys=True))
        return 0
    except (OSError, ValueError) as exc:
        print(json.dumps({"scope": "partial-vm", "full": "NOT_PROVEN", "error": str(exc)}))
        return 2

if __name__ == "__main__":
    raise SystemExit(main())
