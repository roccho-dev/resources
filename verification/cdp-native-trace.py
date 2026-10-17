"""Observe the actual pinned native C probe, via the unchanged upstream proof.
Disposable fixture only. A diagnostic result never certifies acceptance.
"""
import importlib.util
import json
import os
import threading
from collections import Counter

spec = importlib.util.spec_from_file_location("frozen_ops_proof", os.environ["OPS_PROOF"])
proof = importlib.util.module_from_spec(spec)
spec.loader.exec_module(proof)
main_thread = threading.current_thread()
wire = []
observed = Counter()
lock = threading.Lock()
real_call = proof.Controller.call
real_command = proof.Probe.command
VIEW_EXPR = "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})"


def recorded_call(self, method, params=None):
    result = real_call(self, method, params)
    if threading.current_thread() is main_thread:
        return result
    entry = None
    if method == "Page.getLayoutMetrics":
        entry = ("metrics", {
            "visual": result.get("cssVisualViewport", {}),
            "layout": result.get("cssLayoutViewport", {})})
    elif method == "Page.getFrameTree":
        entry = ("tree", {"loader": result.get("frameTree", {}).get("frame", {}).get("loaderId")})
    elif method == "Runtime.evaluate" and (params or {}).get("expression") == VIEW_EXPR:
        entry = ("view", result.get("result", {}).get("value", {}))
    elif method == "Page.captureScreenshot":
        # Never retain base64 images, cookies, endpoint or page contents.
        entry = ("shot", None)
    if entry:
        with lock:
            wire.append(entry)
    return result


def differences(before, after):
    changes = {}
    for area in ("visual", "layout", "view"):
        old = before.get(area, {})
        new = after.get(area, {})
        for key in sorted(set(old) | set(new)):
            a, b = old.get(key), new.get(key)
            # json-c equality is strict about JSON integer vs floating-number type.
            if type(a) is not type(b) or a != b:
                changes[f"{area}.{key}"] = {
                    "before": {"value": a, "type": type(a).__name__},
                    "after": {"value": b, "type": type(b).__name__},
                }
    if before.get("loader") != after.get("loader"):
        changes["loaderId"] = {"changed": True}  # Do not expose target identifiers.
    return changes


def native_geometry_pairs(rows):
    pattern = ("metrics", "tree", "view", "shot", "metrics", "tree", "view")
    out = []
    for k in range(max(0, len(rows) - len(pattern) + 1)):
        sample = rows[k:k+len(pattern)]
        if tuple(x[0] for x in sample) != pattern:
            continue
        before = dict(sample[0][1])
        before["loader"] = sample[1][1]["loader"]
        before["view"] = sample[2][1]
        after = dict(sample[4][1])
        after["loader"] = sample[5][1]["loader"]
        after["view"] = sample[6][1]
        out.append(differences(before, after))
    return out


def recorded_command(self, cmd):
    with lock:
        mark = len(wire)
    outcome = real_command(self, cmd)
    with lock:
        sample = wire[mark:]
    kind = cmd.split(" ", 1)[0]
    observed[f"{kind}-status-{int(outcome[0])}"] += 1
    comparisons = native_geometry_pairs(sample)
    mismatches = [c for c in comparisons if c]
    if mismatches or (kind == "frame" and outcome[0] == 2):
        print(json.dumps({"test": "actual-upstream-C-geometry",
                          "command": kind, "status": int(outcome[0]),
                          "geometry_pairs": len(comparisons),
                          "changed": mismatches, "scope": "diagnostic-only"},
                         sort_keys=True), flush=True)
    return outcome


proof.Controller.call = recorded_call
proof.Probe.command = recorded_command
try:
    # Execute the ORIGINAL pinned proof without altering its assertions.
    proof.run()
except AssertionError as error:
    print(json.dumps({"test": "pinned-proof-observation",
                      "status": "FAIL_OBSERVED_NOT_ACCEPTANCE",
                      "assertion": str(error)[:160],
                      "counts": dict(observed)}), flush=True)
    # The normal pinned doCheck=true package still runs independently and MUST fail
    # if the product proof fails. This diagnostic step is never an acceptance gate.
else:
    print(json.dumps({"test": "pinned-proof-observation",
                      "status": "PASS_DIAGNOSTIC_NOT_ACCEPTANCE",
                      "counts": dict(observed)}), flush=True)
