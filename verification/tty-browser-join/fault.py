# SPDX-License-Identifier: GPL-3.0-or-later
"""C-only lifecycle for A's unchanged test Audit; no product or input generator."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shlex
import time



# Bounded test-owned observations use the existing failed-build log transport.
# Hashes preserve bytes; they are not acceptance or trusted provenance.
FILES = {"unknown-effect-audit.json", "unknown-effect-diagnostic.json"}
MARKER = "C_FAULT_FILE "
LIMIT = 64 * 1024
TRIAL_LIMIT = 512 * 1024


def trial_identity(name):
    from evidence import catalog
    match = re.fullmatch(r"trial-([a-z-]+)-(before-finish|after-finish|failure)\.json", name)
    if match and match[1] in catalog()["cases"]:
        return match[1], match[2]
    return None


def retain_trial(output, trial, phase, context, observation):
    """Keep raw lifecycle/diagnostics even when a later assertion fails."""
    name = f"trial-{trial}-{phase}.json"
    if trial_identity(name) != (trial, phase):
        raise ValueError("invalid-trial-observation")
    value = {"trial": trial, "phase": phase, "context": context,
        "observation": observation, "admission": "NOT_PERFORMED"}
    text = json.dumps(value, ensure_ascii=True, sort_keys=True, allow_nan=False)
    data = text.encode("utf-8")
    if len(data) > TRIAL_LIMIT:
        raise ValueError("trial-observation-too-large")
    # A repeated phase is an error, never replacement of a previous failure.
    with (output / name).open("xb") as handle:
        handle.write(data)
    print(MARKER + json.dumps({"path": name,
        "sha256": hashlib.sha256(data).hexdigest(), "text": text},
        ensure_ascii=True, sort_keys=True), flush=True)
    return name


def viewer_command(target, error_path):
    """Observe A's stderr after B's forkpty; do not confuse it with B's stderr.

    The shell execs the unchanged viewer, preserving its PID, argv, stdin/stdout
    PTY and exit status. Only this isolated fault case redirects diagnostic fd 2.
    """
    return "sh -c " + shlex.quote('exec cdp-tty "$1" 2>"$2"') + " cdp-tty " + shlex.quote(target) + " " + shlex.quote(error_path)


def retain(output, audit_raw, parent_stderr, viewer_stderr):
    """Persist raw observations BEFORE parsing or asserting their correctness."""
    contents = {
        "unknown-effect-audit.json": audit_raw,
        "unknown-effect-diagnostic.json": json.dumps({
            "parentStderr": parent_stderr, "viewerStderr": viewer_stderr}, ensure_ascii=False, sort_keys=True),
    }
    for name, text in contents.items():
        data = text.encode("utf-8")
        if len(data) > LIMIT:
            raise ValueError("fault-observation-too-large:" + name)
        (output / name).write_bytes(data)
        print(MARKER + json.dumps({"path": name, "sha256": hashlib.sha256(data).hexdigest(),
            "text": text}, ensure_ascii=True, sort_keys=True), flush=True)
    return list(contents)


def recover(log, output):
    """Recover exact observations even if Nix cannot publish a failed output.

    No marker means NOT_OBSERVED, not a successful diagnostic. Malformed, duplicate,
    partial, oversized, hash-mismatched or non-allowlisted records are rejected.
    """
    from evidence import decode
    records = {}
    if log.is_file():
        with log.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.startswith(MARKER):
                    continue
                if len(line) > 7 * TRIAL_LIMIT:
                    raise ValueError("fault-record-too-large")
                record = decode(line[len(MARKER):])
                if type(record) is not dict or set(record) != {"path", "sha256", "text"}:
                    raise ValueError("invalid-fault-record")
                name = record["path"]
                identity = trial_identity(name) if type(name) is str else None
                if (type(name) is not str or (name not in FILES and identity is None)
                        or name in records or type(record["text"]) is not str):
                    raise ValueError("invalid-fault-path-or-duplicate")
                data = record["text"].encode("utf-8")
                if len(data) > (TRIAL_LIMIT if identity else LIMIT) or hashlib.sha256(data).hexdigest() != record["sha256"]:
                    raise ValueError("invalid-fault-bytes")
                if identity:
                    value = decode(record["text"])
                    if (type(value) is not dict or (value.get("trial"), value.get("phase")) != identity
                            or value.get("admission") != "NOT_PERFORMED"):
                        raise ValueError("trial-record-binding")
                records[name] = data
    if set(records) & FILES and not FILES <= set(records):
        raise ValueError("incomplete-fault-records")
    if records:
        output.mkdir()
        for name, data in records.items():
            (output / name).write_bytes(data)
    return {"state": "RECOVERED" if records else "NOT_OBSERVED", "files": sorted(records),
        "admission": "NOT_PERFORMED"}


def valid_result(value, expected_source):
    """A wire observer must see one acknowledged-upstream effect and no replay."""
    return (type(value) is dict and value.get("fault") == "close_after_input"
        and value.get("sourceSha256") == expected_source
        and value.get("inputForwarded") is True and type(value.get("connections")) is int
        and value["connections"] == 1 and type(value.get("methods")) is dict
        and all(type(name) is str and type(count) is int and count > 0
            for name, count in value["methods"].items())
        and value["methods"].get("Input.insertText") == 1
        and sum(count for name, count in value["methods"].items() if name.startswith("Input.")) == 1
        and value.get("stoppedByTest") is True)


def serve(source, state, upstream):
    # Import only the exact A-owned test module. Its browser launcher/main is
    # never called: C keeps its existing sandboxed Chrome and actual bcon.
    spec = importlib.util.spec_from_file_location("a_owned_proof", source)
    if spec is None or spec.loader is None:
        raise ValueError("missing-A-proof-module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    state.mkdir(mode=0o700)
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    with module.Audit(upstream, "close_after_input") as audit:
        (state / "ready.json").write_text(json.dumps({"url": audit.url, "sourceSha256": source_hash}))
        end = time.monotonic() + 90
        while not (state / "stop").exists() and time.monotonic() < end:
            time.sleep(.05)
        # Leave the audit alive until the real viewer is confirmed exited, so
        # automatic reconnects/replays cannot hide behind a stopped listener.
        stopped = (state / "stop").exists()
        result = {"fault": audit.fault, "connections": audit.connections,
            "inputForwarded": audit.input_seen, "methods": dict(Counter(audit.methods)),
            "sourceSha256": source_hash, "stoppedByTest": stopped}
        (state / "result.json").write_text(json.dumps(result, sort_keys=True))
    if not stopped:
        raise TimeoutError("fault-observer-lifecycle-deadline")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    args = parser.parse_args()
    upstream = Path("/run/c-proof/ws").read_text().strip()
    if re.fullmatch(r"ws://127\.0\.0\.1:9222/devtools/page/[0-9A-Fa-f]+", upstream) is None:
        raise ValueError("not-the-fixed-C-fixture-target")
    serve(args.source, Path("/run/c-proof/unknown-transport"), upstream)


if __name__ == "__main__":
    main()
