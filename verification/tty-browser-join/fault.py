# SPDX-License-Identifier: GPL-3.0-or-later
"""C-only lifecycle for A's unchanged test Audit; no product or input generator."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import time


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
