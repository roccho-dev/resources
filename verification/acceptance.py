"""Pure E01-E12 receipt consistency; not a collector or release authority.

The caller supplies trusted source/contract/artifact/environment manifest hashes.
Case coverage, provenance, hardware equivalence and apply enforcement remain E12.
Existing VM smoke PASS records must never be promoted to full receipts.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

REQUIRED = tuple(f"E{n:02d}" for n in range(1, 13))
CONTEXT = {"source_sha": 40, "contract_sha256": 64,
           "artifact_sha256": 64, "environment_sha256": 64}


def valid_context(value: Any) -> bool:
    return (type(value) is dict and set(value) == set(CONTEXT)
            and all(type(value[key]) is str
                    and re.fullmatch(r"[0-9a-f]{%d}" % size, value[key]) is not None
                    for key, size in CONTEXT.items()))


def references(value: Any) -> bool:
    return (type(value) is list and bool(value)
            and all(type(item) is str and bool(item.strip()) for item in value)
            and len(value) == len(set(value)))


def evaluate(expected: Any, receipts: Any) -> dict[str, Any]:
    """Validate structure and exact context, without I/O or changing inputs."""
    errors = []
    context_ok = valid_context(expected)
    if not context_ok:
        errors.append("invalid-expected-context")
    groups: dict[str, list[dict[str, Any]]] = {key: [] for key in REQUIRED}
    if type(receipts) is not list:
        errors.append("invalid-receipt-list")
        receipts = []
    for row in receipts:
        if type(row) is not dict or type(row.get("id")) is not str or row["id"] not in groups:
            errors.append("invalid-or-unknown-requirement")
        else:
            groups[row["id"]].append(row)
    records = []
    for key, rows in groups.items():
        reasons = []
        if len(rows) != 1:
            reasons.append("missing" if not rows else "duplicate")
        else:
            row = rows[0]
            if set(row) != {"id", "status", "scope", "context", "positive", "negative"}:
                reasons.append("invalid-receipt-fields")
            if row.get("status") != "PASS" or row.get("scope") != "full":
                reasons.append("not-full-pass")
            if not context_ok or not valid_context(row.get("context")) or row["context"] != expected:
                reasons.append("context-mismatch")
            for side in ("positive", "negative"):
                if not references(row.get(side)):
                    reasons.append("missing-or-invalid-" + side)
        records.append({"id": key, "status": "NOT_PROVEN" if reasons else "CONSISTENT",
                        "reasons": reasons})
    return {"scope": "receipt-consistency-only", "errors": errors,
            "context": dict(expected) if context_ok else None,
            "consistent": not errors and all(not row["reasons"] for row in records),
            "records": records}


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate-json-key")
        result[key] = value
    return result


def reject_constant(_value: str) -> None:
    raise ValueError("non-json-number")


def load(path: Path, *, lines: bool = False) -> Any:
    with path.open("rb") as handle:
        raw = handle.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError("evidence-too-large")
    text = raw.decode("utf-8")

    def decode(value: str) -> Any:
        return json.loads(value, object_pairs_hook=unique_object, parse_constant=reject_constant)

    return [decode(line) for line in text.splitlines() if line.strip()] if lines else decode(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--receipts", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    inputs: dict[str, Any] = {"context": None, "receipts": []}
    errors = []
    for name in inputs:
        try:
            inputs[name] = load(getattr(args, name), lines=name == "receipts")
        except (OSError, ValueError, RecursionError):
            errors.append("unreadable-or-invalid-" + name)
    report = evaluate(inputs["context"], inputs["receipts"])
    report["errors"].extend(errors)
    report["consistent"] = report["consistent"] and not errors
    header = {key: value for key, value in report.items() if key != "records"}
    rows = [header] + report["records"]
    # Write once per run; emit verdicts, never unvalidated input contents or secrets.
    try:
        args.output.mkdir(parents=True, exist_ok=False)
        for name, selected in (("raws", rows), ("disruptives", [row for row in rows
                if row.get("errors") or row.get("status") == "NOT_PROVEN"])):
            (args.output / (name + ".jsonl")).write_text(
                "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in selected),
                encoding="utf-8")
    except OSError:
        print(json.dumps({"scope": "receipt-consistency-only", "error": "output-not-created"}))
        return 2
    print(json.dumps(header, sort_keys=True))
    return 0 if report["consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
