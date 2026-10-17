# SPDX-License-Identifier: GPL-3.0-or-later
"""C-specific observation consistency, not a collector, reviewer or merge authority.

Follows resources#3's separation of receipt checks and independent admission.
A matching hash cannot prove provenance or upstream consent. Synthetic unit data
never enters the VM. Callers must independently establish the expected context.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

LIMIT = 1024 * 1024
HASH = re.compile(r"[0-9a-f]{64}\Z")
FIELDS = {"case", "status", "scope", "context", "facts", "artifacts"}


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate-json-key")
        result[key] = value
    return result


def decode(raw: str) -> Any:
    def reject(_):
        raise ValueError("invalid-json-number")
    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)


def read_json(path: Path, *, lines=False) -> Any:
    if not path.is_file():
        raise ValueError("not-a-regular-evidence-file")
    with path.open("rb") as handle:
        raw = handle.read(LIMIT + 1)
    if len(raw) > LIMIT:
        raise ValueError("evidence-too-large")
    text = raw.decode("utf-8")
    return [decode(line) for line in text.splitlines() if line.strip()] if lines else decode(text)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def catalog() -> dict:
    result = read_json(Path(__file__).with_name("coverage.json"))
    assert result["version"] == 1
    assert set(result["criteria"]) == {f"C{i}" for i in range(1, 8)}
    assert set(result["legacy"]) == {f"E{i:02d}" for i in range(1, 13)}
    assert set(result["cases"]) == {name for ids in result["criteria"].values() for name in ids}
    return result


def context_valid(value: Any) -> bool:
    return (type(value) is dict and set(value) == {"code", "inputs", "environment"}
        and all(type(v) is str and HASH.fullmatch(v) is not None for v in value.values()))


def reference_list(value: Any) -> bool:
    return (type(value) is list and 0 < len(value) <= 64
        and all(type(v) is str and v.startswith("https://") and len(v) <= 2048 for v in value)
        and len(set(value)) == len(value))


def snapshot(value: Any) -> bool:
    return (type(value) is dict and set(value) == {"target", "field", "text", "browserPid"}
        and type(value["target"]) is str and bool(value["target"])
        and value["field"] == "editor" and type(value["text"]) is str
        and type(value["browserPid"]) is int and value["browserPid"] > 0)


def facts_valid(spec: dict, facts: Any) -> bool:
    if type(facts) is not dict:
        return False
    kind = spec["kind"]
    if kind in ("reference", "review"):
        valid = reference_list(facts.get("positive")) and reference_list(facts.get("negative"))
        if kind == "review":
            valid = (valid and type(facts.get("writer")) is str and bool(facts["writer"])
                and type(facts.get("reviewer")) is str and bool(facts["reviewer"])
                and facts["writer"] != facts["reviewer"] and facts.get("unresolved") == [])
        return bool(valid)
    if kind == "selection":
        offered, selected = facts.get("offered"), facts.get("selected")
        if type(offered) is not list or not offered or type(selected) is not dict:
            return False
        if any(type(c) is not dict or type(c.get("id")) is not str or not c["id"] for c in offered):
            return False
        ids = [c["id"] for c in offered]
        chosen = [c for c in offered if c["id"] == selected.get("id")]
        return (len(set(ids)) == len(ids) and len(chosen) == 1 and digest(chosen[0]) == digest(selected)
            and type(selected.get("meaning")) is dict and selected["meaning"].get("kind") == "text"
            and "evidence" in selected and type(selected.get("representation")) is str
            and bool(selected["representation"]) and type(facts.get("query")) is dict
            and set(facts["query"]) == {"generation", "raw"}
            and type(facts["query"]["generation"]) is int and facts["query"]["generation"] > 0
            and type(facts["query"]["raw"]) is str and bool(facts["query"]["raw"])
            and type(facts.get("selectedQuery")) is dict
            and digest(facts["selectedQuery"]) == digest(facts["query"]) and facts.get("effectCount") == 1
            and type(facts["effectCount"]) is int and facts.get("capture") == "B-original-selection")
    before, after = facts.get("before"), facts.get("after")
    if not snapshot(before) or not snapshot(after):
        return False
    if any(before[k] != after[k] for k in ("target", "field", "browserPid")):
        return False
    suffix = spec.get("suffix", "")
    if after["text"] != before["text"] + suffix:
        return False
    if kind == "insert":
        return (facts.get("input") == "vm-keyboard" and facts.get("preeditText") == before["text"])
    if kind == "unchanged":
        return facts.get("input") == "vm-keyboard"
    if kind == "target-rejection":
        return (type(facts.get("attemptedTarget")) is str and bool(facts["attemptedTarget"])
            and facts["attemptedTarget"] != before["target"] and facts.get("refused") is True)
    if kind == "resize":
        values = [facts.get(k) for k in ("sizeBefore", "sizeChanged", "sizeRestored")]
        return (all(type(v) is list and len(v) == 2
            and all(type(n) is int and n > 0 for n in v) for v in values)
            and values[0] != values[1] and values[0] == values[2])
    if kind in ("cleanup", "reconnect", "disconnect"):
        valid = (type(facts.get("termiosBefore")) is str and bool(facts["termiosBefore"])
            and facts["termiosBefore"] == facts.get("termiosAfter")
            and type(facts.get("profileBefore")) is str and bool(facts["profileBefore"])
            and facts["profileBefore"] == facts.get("profileAfter")
            and type(facts.get("exitCode")) is int)
        if kind == "disconnect":
            return (valid and facts.get("fault") == "tcp-disconnect" and facts["exitCode"] != 0
                and type(facts.get("closedSockets")) is str and bool(facts["closedSockets"]))
        if kind == "reconnect":
            pids = facts.get("viewerPids")
            valid = valid and type(pids) is list and len(pids) == 2 and all(
                type(p) is int and p > 0 for p in pids) and pids[0] != pids[1]
        return valid and facts["exitCode"] == 0
    return False


def artifact_errors(root: Path, rows: list) -> dict[int, list[str]]:
    """Read bounded files under this run only. Never follow a supplied symlink."""
    errors = {}
    root = root.resolve()
    for index, row in enumerate(rows):
        reasons = []
        artifacts = row.get("artifacts") if type(row) is dict else None
        if type(artifacts) is not list or not 0 < len(artifacts) <= 32:
            errors[index] = ["missing-artifacts"]
            continue
        seen = set()
        for value in artifacts:
            if (type(value) is not dict or set(value) != {"path", "sha256"}
                    or type(value["path"]) is not str or type(value["sha256"]) is not str
                    or HASH.fullmatch(value["sha256"]) is None):
                reasons.append("invalid-artifact")
                continue
            name = value["path"]
            path = Path(name)
            if (not name or path.is_absolute() or any(p in (".", "..") for p in name.split("/"))
                    or "\\" in name or name in seen):
                reasons.append("unsafe-or-duplicate-artifact")
                continue
            seen.add(name)
            full = root / path
            try:
                if any((root / Path(*path.parts[:i])).is_symlink() for i in range(1, len(path.parts) + 1)):
                    raise ValueError("symlink")
                if not full.is_file() or not full.resolve().is_relative_to(root):
                    raise ValueError("outside-root")
                with full.open("rb") as handle:
                    raw = handle.read(16 * LIMIT + 1)
                if not raw or len(raw) > 16 * LIMIT or hashlib.sha256(raw).hexdigest() != value["sha256"]:
                    raise ValueError("bad-digest")
            except (OSError, ValueError):
                reasons.append("unreadable-or-mismatched-artifact")
        # Bind the receipt fields to the captured bytes, not an unrelated PNG.
        capture_name = "capture-" + str(row.get("case")) + ".json"
        try:
            if capture_name not in seen or reasons:
                raise ValueError("capture-not-verified")
            capture = read_json(root / capture_name)
            if digest(capture) != digest({key: value for key, value in row.items() if key != "artifacts"}):
                raise ValueError("capture-fields-mismatch")
        except (OSError, ValueError, RecursionError):
            reasons.append("missing-or-mismatched-capture")
        if reasons:
            errors[index] = reasons
    return errors


def assess(expected: Any, rows: Any, root: Path) -> dict:
    rules = catalog()
    errors, groups = [], {case: [] for case in rules["cases"]}
    if not context_valid(expected):
        errors.append("invalid-expected-context")
    if type(rows) is not list or len(rows) > 128:
        errors.append("invalid-record-list")
        rows = []
    bad_files = artifact_errors(root, rows)
    for index, row in enumerate(rows):
        if type(row) is not dict or type(row.get("case")) is not str or row["case"] not in groups:
            errors.append("invalid-or-unknown-case")
            continue
        groups[row["case"]].append((index, row))
    cases = []
    for name, spec in rules["cases"].items():
        group, reasons = groups[name], []
        if len(group) != 1:
            reasons.append("missing" if not group else "duplicate")
        else:
            index, row = group[0]
            if set(row) != FIELDS:
                reasons.append("invalid-fields")
            if row.get("status") != "PASS" or row.get("scope") != spec["scope"]:
                reasons.append("not-required-scope-pass")
            if not context_valid(row.get("context")) or row["context"] != expected:
                reasons.append("context-mismatch")
            if not facts_valid(spec, row.get("facts")):
                reasons.append("observation-mismatch")
            reasons.extend(bad_files.get(index, []))
        cases.append({"case": name, "status": "NOT_PROVEN" if reasons else "CONSISTENT", "reasons": reasons})
    missing = {case["case"] for case in cases if case["reasons"]}
    return {
        "gate": "C_EVIDENCE_CONSISTENCY_ONLY", "errors": errors,
        "consistent": not errors and not missing, "admission": "NOT_PERFORMED",
        "upstreamAgreement": "NOT_INFERRED", "cases": cases,
        "criteria": [{"id": key, "status": "NOT_PROVEN" if errors or any(x in missing for x in ids)
            else "CONSISTENT_NOT_ADMITTED", "missing": [x for x in ids if x in missing]}
            for key, ids in rules["criteria"].items()],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        report = assess(read_json(args.expected), read_json(args.records, lines=True), args.root)
    except (OSError, ValueError, RecursionError):
        report = {"gate": "C_EVIDENCE_CONSISTENCY_ONLY", "consistent": False,
            "errors": ["unreadable-or-invalid-evidence"], "admission": "NOT_PERFORMED"}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["consistent"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
