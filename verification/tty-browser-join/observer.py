# SPDX-License-Identifier: GPL-3.0-or-later
"""C VM observer: read-only CDP plus local Target/session bookkeeping.

No input/DOM-write method, arbitrary JS argument, provider response or keyboard
injection exists here. The fixture is exactly one page and one named input field.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import termios
import time
import urllib.request

STATE = Path("/run/c-proof")
EXPRESSION = "JSON.stringify({text:document.querySelector('#editor').value,field:document.activeElement.id})"


def dom():
    import websocket
    with urllib.request.urlopen("http://127.0.0.1:9222/json/list", timeout=2) as response:
        pages = [p for p in json.load(response) if p.get("type") == "page"]
    if len(pages) != 1:
        raise ValueError("ambiguous-browser-target")
    page = pages[0]
    identity = STATE / "target"
    if identity.exists():
        if identity.read_text() != page["id"]:
            raise ValueError("browser-target-changed")
    else:
        identity.write_text(page["id"])
        (STATE / "ws").write_text(page["webSocketDebuggerUrl"])
    ws = websocket.create_connection(page["webSocketDebuggerUrl"], timeout=2, suppress_origin=True)
    try:
        ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {
            "expression": EXPRESSION, "returnByValue": True,
            "throwOnSideEffect": True, "timeout": 1000}}))
        until = time.monotonic() + 2
        for _ in range(512):
            if time.monotonic() > until:
                raise TimeoutError("observer-response-deadline")
            data = json.loads(ws.recv())
            if data.get("id") != 1:
                continue
            if "error" in data or "exceptionDetails" in data["result"]:
                raise ValueError("observer-read-rejected")
            result = json.loads(data["result"]["result"]["value"])
            result.update(target=page["id"], browserPid=int(subprocess.check_output(
                ["systemctl", "show", "-p", "MainPID", "--value", "c-browser"], text=True)))
            return result
        raise TimeoutError("observer-response-limit")
    finally:
        ws.close()


def children(pid):
    return [int(p) for p in Path(f"/proc/{pid}/task/{pid}/children").read_text().split()]


def session(name):
    if re.fullmatch(r"[a-z-]+", name) is None:
        raise ValueError("invalid-test-session")
    parent = int((STATE / (name + ".parent")).read_text())
    wrappers = children(parent)
    if len(wrappers) != 1:
        raise ValueError("ambiguous-input-process")
    wrapper = wrappers[0]
    owned = []
    for pid in children(wrapper):
        try:
            stdin, stdout = (os.readlink(f"/proc/{pid}/fd/{fd}") for fd in (0, 1))
            if stdin.startswith("/dev/pts/") and stdin == stdout:
                owned.append(pid)
        except FileNotFoundError:
            pass
    if len(owned) != 1:
        raise ValueError("ambiguous-viewer-child")
    tty_path = os.readlink(f"/proc/{wrapper}/fd/0")
    fd = os.open(tty_path, os.O_RDONLY | os.O_NOCTTY)
    try:
        rows, cols, _, _ = struct.unpack("HHHH", fcntl.ioctl(fd, termios.TIOCGWINSZ, b"\0" * 8))
    finally:
        os.close(fd)
    return {"wrapperPid": wrapper, "viewerPid": owned[0], "tty": tty_path, "size": [rows, cols]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("dom", "session"))
    parser.add_argument("value", nargs="?")
    args = parser.parse_args()
    result = dom() if args.mode == "dom" else session(args.value or "")
    if args.mode == "dom" and args.value is not None and result["text"] != args.value:
        # This observer is restricted to a disposable fixture. Preserve the
        # actual rejected value and existing product diagnostics; do not change
        # input, weaken the expected value, or silently retry a product effect.
        errors = {}
        for path in sorted(STATE.glob("*.errors"))[:16]:
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as handle:
                errors[path.name] = handle.read(4096).decode("utf-8", errors="replace")
        print("C_FIXTURE_DOM_MISMATCH " + json.dumps({
            "expected": args.value, "observed": result, "productErrors": errors
        }, ensure_ascii=False), flush=True)
        raise ValueError("fixture-DOM-text-mismatch")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
