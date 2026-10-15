# SPDX-License-Identifier: GPL-3.0-or-later
# C input/fault collection; extends the preserved ordinary-input test, not A/B.
# Fixed-loopback fixture != real Shared Provider. Missing original-ID/target
# observation remains absent; do not infer it from a matching display string.
import base64
import hashlib
import json
from pathlib import Path
import shlex
import time
from PIL import Image
import evidence
import fault

out = Path(machine.out_dir)
rows = []
context = None
current = "ordinary"
trial: str = ""
last_image = None
failed = False
# Diagnostic timing must never be an implicit prerequisite of ordinary acceptance.
trace_requested = False


def command(value):
    return machine.succeed(value, timeout=5)


def wait(value, seconds=15):
    return machine.wait_until_succeeds(value, timeout=seconds)


def put(path, value):
    command("printf %s " + shlex.quote(value) + " > " + shlex.quote(path))


def observer(mode="dom", value=None):
    return "python3 /etc/c-observer.py " + mode + (" " + shlex.quote(value) if value is not None else "")


def snapshot(text=None):
    if text is not None:
        wait(observer(value=text))
    result = json.loads(command(observer()))
    assert evidence.snapshot(result), result
    return result


def png(name):
    global last_image
    machine.screenshot(name)
    last_image = name + ".png"
    with Image.open(out / last_image) as image:
        return image.convert("RGB").copy()


def pixels(image, color):
    return sum(n for n, rgb in image.getcolors(image.width * image.height)
        if all(abs(a - b) <= 2 for a, b in zip(rgb, color)))


def await_image(name, predicate):
    assert trial, "test session has not started"
    until = time.monotonic() + 15
    while time.monotonic() < until:
        status, _ = machine.execute("test -e /run/c-proof/" + trial + ".exit", timeout=5)
        assert status != 0, command("cat /run/c-proof/" + trial + ".exit /run/c-proof/" + trial + ".errors")
        image = png(name)
        if predicate(image):
            return image
        time.sleep(.2)
    raise AssertionError("C scanout missing: " + name)


def record(name, facts, images=(), status="PASS"):
    capture = {"case": name, "status": status, "scope": evidence.catalog()["cases"][name]["scope"], "context": context, "facts": facts}
    path = out / ("capture-" + name + ".json")
    path.write_text(json.dumps(capture, ensure_ascii=False))
    names = [path.name] + list(images)
    row = {**capture, "artifacts": [{"path": n, "sha256": hashlib.sha256((out / n).read_bytes()).hexdigest()} for n in names]}
    rows.append(row)
    with (out / "raws.jsonl").open("a") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    print("C_OBSERVATION " + json.dumps(row, ensure_ascii=False), flush=True)


def begin(name, mode=None, websocket=None, expect_ready=True, *, diagnostic_trace=False):
    global trial, trace_requested
    if diagnostic_trace and (name != "cancel" or not expect_ready):
        raise ValueError("trace-is-only-for-an-explicit-cancel-diagnostic")
    trial = name
    trace_requested = diagnostic_trace
    prefix = "/run/c-proof/" + name
    if mode is not None:
        put("/run/c-provider/mode", mode)
        command("rm -f /run/c-provider/held /run/c-provider/release; : > /run/c-provider/requests.jsonl; : > /run/c-provider/responses.jsonl")
    env = "MELTYPE_PROPOSAL_URL=http://127.0.0.1:8031/proposal " if mode else ""
    target = shlex.quote(websocket) if websocket is not None else '"$(cat /run/c-proof/ws)"'
    viewer = "cdp-tty " + target
    if name == "unknown-effect":
        assert websocket is not None, "fault observer target is required"
        viewer = fault.viewer_command(websocket, prefix + ".viewer.errors")
    script = (f"umask 077\nprintf %s $$ > {prefix}.parent\nstty -g > {prefix}.before\n"
        + env + 'meltype-tty --raw-text --selection-fd 3 -- ' + viewer
        + f" 3>>{prefix}.selection.jsonl 2>{prefix}.errors\nrc=$?\nstty -g > {prefix}.after\nprintf %s \"$rc\" > {prefix}.exit\n")
    put(prefix + ".trial", script)
    machine.send_chars("bash " + prefix + ".trial\n")
    if not expect_ready:
        return None, None
    image = await_image(name + "-before", lambda im: pixels(im, (215, 225, 240)) > 2000)
    info = json.loads(command(observer("session", name)))
    if diagnostic_trace:
        traces = json.loads(command(observer("trace-cancel")))
        for trace in traces["traces"]:
            wait("grep -Eq '^TracerPid:[[:space:]]+" + str(trace["tracerPid"]) +
                "$' /proc/" + str(trace["pid"]) + "/status", seconds=5)
    return image, info


def capture_trial(phase, result=None, error=None):
    value = {"result": result, "error": error, "observedAtNs": time.monotonic_ns(),
        "conditions": {"mode": "traced-diagnostic" if trace_requested else "ordinary-untraced",
            "traceRequested": trace_requested,
            "extraBeforeInput": ["strace-attach", "TracerPid-wait"] if trace_requested else [],
            "extraBeforeQuit": ["diagnostic-file-and-DOM-read"] if trace_requested else [],
            "guestReadPhase": phase}}
    try:
        code, text = machine.execute(observer("diagnostic", trial), timeout=5)
        value["collectorExit"] = code
        value["guest"] = json.loads(text) if code == 0 else {"raw": text}
    except Exception as failure:
        value["collectorError"] = type(failure).__name__
    return fault.retain_trial(out, trial, phase, context, value)


def finish(before, *, fault=False):
    assert trial, "test session has not started"
    prefix = "/run/c-proof/" + trial
    # The ordinary path sends the original quit immediately. The already
    # observed `before` value is retained in result after exit, not re-read
    # synchronously before quit. Traced observations remain explicit diagnostics.
    if trace_requested:
        capture_trial("before-finish", {"before": before, "faultExpected": fault})
    if not fault:
        machine.send_key("ctrl-q")
    wait("test -e " + prefix + ".exit")
    result = {"before": before, "after": snapshot(),
        "termiosBefore": command("cat " + prefix + ".before").strip(),
        "termiosAfter": command("cat " + prefix + ".after").strip(),
        "profileBefore": profile_marker,
        "profileAfter": command("cat /run/c-browser/profile/c-fixture-marker").strip(),
        "exitCode": int(command("cat " + prefix + ".exit").strip())}
    capture_trial("after-finish", result)
    assert result["termiosBefore"] == result["termiosAfter"]
    assert result["profileBefore"] == result["profileAfter"]
    assert before == result["after"], result
    if fault:
        assert result["exitCode"] != 0
    else:
        assert result["exitCode"] == 0
    return result


def offered():
    wait("test -s /run/c-provider/responses.jsonl")
    return [json.loads(line) for line in command("cat /run/c-provider/responses.jsonl").splitlines()]


def selection_facts(selections, responses):
    assert len(selections) == 1, "one original product selection is required"
    selected = selections[0]
    query = {key: selected[key] for key in ("generation", "raw")}
    matching = [response for response in responses if response["query"] == query]
    assert len(matching) == 1, "selection response is missing or ambiguous"
    response = matching[0]
    body = response["body"]
    assert hashlib.sha256(body.encode("utf-8")).hexdigest() == response["sha256"]
    supplied = json.loads(body)
    assert {key: supplied[key] for key in ("generation", "raw")} == query
    facts = {"offered": supplied["proposals"], "selected": selected["proposal"],
        "query": query, "selectedQuery": query, "effectCount": 1, "capture": "B-original-selection"}
    assert evidence.facts_valid({"kind": "selection"}, facts), "invalid original selected ID"
    return facts


def require_vm_cases(report):
    required = {name for name, spec in evidence.catalog()["cases"].items() if spec["scope"] == "vm"}
    checked = {case["case"]: case for case in report["cases"]}
    failures = sorted(name for name in required
        if name not in checked or checked[name]["status"] != "CONSISTENT" or checked[name]["reasons"])
    assert not report["errors"] and not failures, {"errors": report["errors"], "vm": failures}
    return sorted(required)


try:
    start_all()
    machine.wait_for_unit("c-console.service", timeout=90)
    machine.wait_for_unit("c-browser.service", timeout=90)
    command('test "$(cat /sys/class/tty/tty0/active)" = tty2')
    wait("pgrep -x login")
    wait("journalctl -u c-console.service --no-pager | grep -F 'All phases complete, entering main loop'")
    machine.send_chars("root\n")
    wait("pgrep -t pts/0 -x bash")
    command("mkdir -p /run/c-proof /run/c-provider")
    before = snapshot("")
    profile_marker = "C-fixture-profile-not-user-data"
    put("/run/c-browser/profile/c-fixture-marker", profile_marker)
    pins = json.loads(command("cat /etc/c-source-pins.json"))
    executables = command("sha256sum $(readlink -f $(command -v cdp-tty)) $(readlink -f $(command -v meltype-tty)) $(readlink -f $(command -v bcon))")
    meta = json.loads(command("cat /etc/c-code.json"))
    environment = {"meta": meta, "kernel": command("uname -sr"), "system": command("nixos-version")}
    context = {"code": meta["code"], "inputs": evidence.digest({"pins": pins, "executables": executables}),
        "environment": evidence.digest(environment)}
    # Retain the original observations, not only an irreversible environment hash.
    # This attests this VM, never a physical Windows/NixOS host.
    (out / "environment.json").write_text(json.dumps(environment, sort_keys=True))
    (out / "context.json").write_text(json.dumps(context, sort_keys=True))
    (out / "inputs.json").write_text(json.dumps({"pins": pins, "executables": executables, "meta": meta}, sort_keys=True))

    base, _ = begin("ordinary")
    machine.send_chars("nihongo ")
    await_image("ordinary-candidate", lambda im: pixels(im, (24, 26, 32)) > pixels(base, (24, 26, 32)) + 1000)
    preedit = snapshot("")
    machine.send_key("ret")
    after = snapshot("日本語")
    png("ordinary-after")
    record(current, {"before": before, "after": after, "preeditText": preedit["text"], "input": "vm-keyboard"},
        ["ordinary-candidate.png", "ordinary-after.png"])
    cleanup = finish(after)
    record("cleanup", cleanup, ["ordinary-after.png"])

    put("/run/c-provider/mode", "typed")
    command("systemctl start c-provider.service")
    wait("test -e /run/c-provider/ready")
    for name in ("typed", "cancel", "stale", "duplicate-confirm", "invalid-json", "duplicate-id", "action", "control-text", "wrong-raw"):
        current = name
        mode = "typed" if name in ("cancel", "duplicate-confirm") else name
        before = snapshot()
        base, _ = begin(name, mode)
        machine.send_chars("u")
        if name == "stale":
            wait("test -e /run/c-provider/held")
            machine.send_chars("x")
            command("touch /run/c-provider/release")
            wait("test $(wc -l < /run/c-provider/responses.jsonl) -ge 2")
        offered()
        if name in ("typed", "cancel", "stale", "duplicate-confirm"):
            # Rendering threshold is only readiness. DOM and IDs are distinct evidence.
            threshold = 45000 if name != "stale" else 38000
            await_image(name + "-candidate", lambda im: pixels(im, (24, 26, 32)) > pixels(base, (24, 26, 32)) + threshold)
        preedit = snapshot(before["text"])
        if name == "cancel":
            machine.send_key("esc"); time.sleep(.1); machine.send_key("esc")
            expected = before["text"]
        else:
            if name in ("typed", "duplicate-confirm"):
                machine.send_key("down")
            elif name not in ("stale",):
                # Explicit user's original-text fallback, never injected into DOM.
                machine.send_key("f10")
            machine.send_key("ret")
            if name == "duplicate-confirm":
                snapshot(before["text"] + "乙候補")
                machine.send_key("ret")
            expected = before["text"] + evidence.catalog()["cases"][name].get("suffix", "")
        after = snapshot(expected)
        png(name + "-after")
        record(name, {"before": before, "after": after, "preeditText": preedit["text"], "input": "vm-keyboard",
            "provider": "C-local-fixture", "responses": offered()}, [name + "-after.png"])
        if name == "typed":
            # Product writes its existing original selection through the caller's
            # explicit private fd. DOM observation is a distinct receipt.
            raw_selection = command("cat /run/c-proof/typed.selection.jsonl")
            selections = [json.loads(line) for line in raw_selection.splitlines()]
            selected = selection_facts(selections, offered())
            (out / "B-original-selection.jsonl").write_text(raw_selection)
            record("typed-id", selected, ["B-original-selection.jsonl", "typed-after.png"])
        finish(after)

    current = "wrong-target"
    before = snapshot()
    attempted = "0" * 32 if before["target"] != "0" * 32 else "1" * 32
    original_ws = command("cat /run/c-proof/ws").strip()
    bad_ws = original_ws.rsplit("/", 1)[0] + "/" + attempted
    begin("wrong-target", websocket=bad_ws, expect_ready=False)
    facts = finish(before, fault=True)
    facts.update(attemptedTarget=attempted, refused=True)
    record("wrong-target", facts)

    current = "resize"
    before = snapshot()
    _, first = begin("resize")
    size = first["size"]
    changed = [max(10, size[0] - 3), max(20, size[1] - 7)]
    tty = shlex.quote(first["tty"])
    command(f"stty -F {tty} rows {changed[0]} cols {changed[1]}")
    measured = json.loads(command(observer("session", "resize")))["size"]
    assert measured == changed and measured != size
    await_image("resized", lambda im: pixels(im, (215, 225, 240)) > 2000)
    command(f"stty -F {tty} rows {size[0]} cols {size[1]}")
    restored = json.loads(command(observer("session", "resize")))["size"]
    after = snapshot(before["text"])
    record("resize", {"before": before, "after": after, "sizeBefore": size, "sizeChanged": measured, "sizeRestored": restored}, ["resized.png"])
    finish(after)

    current = "reconnect"
    before = snapshot()
    _, second = begin("reconnect")
    after = snapshot(before["text"])
    png("reattached")
    facts = finish(after)
    facts["viewerPids"] = [first["viewerPid"], second["viewerPid"]]
    record("reconnect", facts, ["reattached.png"])

    current = "disconnect"
    before = snapshot()
    begin("disconnect")
    # Fault injection in the isolated VM, not a CDP writer or replacement Viewer.
    killed = command("ss -K -Hnt dst 127.0.0.1 dport = :9222").strip()
    assert killed, "kernel did not confirm any closed socket"
    facts = finish(before, fault=True)
    facts.update(fault="tcp-disconnect", closedSockets=killed)
    record("disconnect", facts)
    command("systemctl stop c-provider.service")

    current = "unknown-effect"
    before = snapshot()
    command("systemctl start c-unknown-effect.service")
    wait("test -s /run/c-proof/unknown-transport/ready.json")
    ready = json.loads(command("cat /run/c-proof/unknown-transport/ready.json"))
    assert ready["sourceSha256"] == meta["faultSource"]
    base, _ = begin("unknown-effect", websocket=ready["url"])
    machine.send_chars("nihongo ")
    await_image("unknown-effect-candidate", lambda im: pixels(im, (24, 26, 32)) > pixels(base, (24, 26, 32)) + 1000)
    preedit = snapshot(before["text"])
    machine.send_key("ret")
    after = snapshot(before["text"] + "日本語")
    # The real effect was acknowledged to A's audit, but that response was not
    # forwarded to the viewer. A/B must exit without replay or reconnection.
    cleanup = finish(after, fault=True)
    command("touch /run/c-proof/unknown-transport/stop")
    wait("test -s /run/c-proof/unknown-transport/result.json")
    audit_raw = command("cat /run/c-proof/unknown-transport/result.json")
    parent_errors = command("cat /run/c-proof/unknown-effect.errors")
    errors = command("cat /run/c-proof/unknown-effect.viewer.errors")
    # These bytes must survive even a bad audit or an empty/wrong diagnostic.
    saved_fault = fault.retain(out, audit_raw, parent_errors, errors)
    audit = json.loads(audit_raw)
    assert fault.valid_result(audit, meta["faultSource"]), audit
    assert "stage=input-dispatch" in errors and "completion=unknown" in errors, errors
    assert before["target"] == after["target"] and before["field"] == after["field"]
    assert before["browserPid"] == after["browserPid"]
    # Independent means the separate wire observer and read-only DOM channel,
    # not a different person/actor or an independent merge/admission reviewer.
    record("unknown-effect", {"positive": [meta["evidenceRun"]], "negative": [meta["evidenceRun"]],
        "execution": "nixos-vm", "observers": "A-wire-audit-and-read-only-C-DOM",
        "before": before, "after": after, "preeditText": preedit["text"],
        "cleanup": cleanup, "audit": audit, "input": "vm-keyboard", "effectCount": 1,
        "admission": "NOT_PERFORMED"}, saved_fault)
    machine.fail("pgrep -f '[f]citx5|[i]bus-daemon|[t]tyskk'")
except Exception as error:
    failed = True
    # Capture even when this case already has a partial DOM PASS. Do not turn
    # that partial observation or another trial's cleanup into exit success.
    if trial:
        try:
            capture_trial("failure", error={"type": type(error).__name__, "message": str(error)})
        except Exception as secondary:
            print("C_DIAGNOSTIC_ERROR " + type(secondary).__name__, flush=True)
    if context is not None and not any(row["case"] == current for row in rows):
        record(current, {"error": type(error).__name__}, status="FAIL")
    if last_image is not None:
        raw = (out / last_image).read_bytes()
        if len(raw) <= 1024 * 1024:
            print("C_FAILURE_PNG " + last_image + " " + base64.b64encode(raw).decode(), flush=True)
    raise
finally:
    report = evidence.assess(context, rows, out)
    (out / "assessment.json").write_text(json.dumps(report, ensure_ascii=False, sort_keys=True))
    (out / "disruptives.jsonl").write_text("".join(json.dumps(row) + "\n" for row in report["cases"] if row["reasons"]))
    print("C_ASSESSMENT " + json.dumps(report, ensure_ascii=False), flush=True)
    # Every declared VM observation is mandatory. External provider/physical/
    # review evidence stays NOT_PROVEN, not fabricated from a VM success.
    # The original exception remains primary. A second coverage assertion must
    # not replace it; this never converts a failing run to success.
    if not failed:
        verified_vm = require_vm_cases(report)
        unknown = next(case for case in report["cases"] if case["case"] == "unknown-effect")
        assert unknown["status"] == "CONSISTENT", unknown
        print("C_VM_RESULT " + json.dumps({"cases": verified_vm, "status": "PASS",
            "additionalCI": ["unknown-effect"], "fullAcceptance": "NOT_PROVEN"}), flush=True)
