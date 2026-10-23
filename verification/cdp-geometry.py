"""Finite geometry comparison on the pinned Chrome and upstream fixture.
No changes to the pinned viewer, no real profile, no E01-E12 completion claim.
"""
import ast
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import urllib.request
import websocket

SHOT = {"format": "png", "captureBeyondViewport": False, "fromSurface": False}
VIEW = {"expression": "({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})",
        "returnByValue": True, "throwOnSideEffect": True, "silent": True, "timeout": 1000}
N = 12


def eventually(fn, timeout=8):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            answer = fn()
            if answer:
                return answer
        except (OSError, ValueError, KeyError, websocket.WebSocketException):
            pass
        time.sleep(.02)
    raise AssertionError("bounded wait expired")


def fixture_from_pinned_source():
    # Parse a literal; NEVER import/execute the upstream test harness.
    module = ast.parse(Path(os.environ["OPS_PROOF"]).read_text())
    value = next(x.value for x in module.body if isinstance(x, ast.Assign)
                 and any(isinstance(t, ast.Name) and t.id == "PAGE" for t in x.targets))
    return ast.literal_eval(value).decode("utf-8")


class CDP:
    def __init__(self, url):
        self.ws = websocket.create_connection(url, timeout=5, suppress_origin=True)
        self.seq = 0

    def call(self, method, params=None):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params or {}}))
        while True:
            reply = json.loads(self.ws.recv())
            if reply.get("id") == self.seq:
                assert "error" not in reply, (method, reply.get("error"))
                return reply["result"]

    def eval(self, expression):
        answer = self.call("Runtime.evaluate",
                           {"expression": expression, "returnByValue": True})
        assert "exceptionDetails" not in answer
        return answer["result"].get("value")

    def geometry(self):
        # Preserve upstream geometry()'s exact observation order and keys.
        metrics = self.call("Page.getLayoutMetrics")
        tree = self.call("Page.getFrameTree")
        view = self.call("Runtime.evaluate", VIEW)["result"]["value"]
        return {"visual": metrics["cssVisualViewport"],
                "layout": metrics["cssLayoutViewport"],
                "loader": tree["frameTree"]["frame"]["loaderId"],
                "view": view}

    def compare(self, mutate=None):
        before = self.geometry()
        if mutate is not None:
            mutate()
        assert self.call("Page.captureScreenshot", SHOT).get("data")
        after = self.geometry()
        keys = set()
        for part in ("visual", "layout", "view"):
            for key in set(before[part]) | set(after[part]):
                if before[part].get(key) != after[part].get(key):
                    keys.add(part + "." + key)
        if before["loader"] != after["loader"]:
            keys.add("loaderId")
        return sorted(keys)

    def close(self):
        self.ws.close()


def run():
    binary = os.environ["CHROME_BIN"]
    source_page = fixture_from_pinned_source()
    for dpr in (1, 2):
        with tempfile.TemporaryDirectory(prefix="geometry-reduction-") as tmp:
            profile = Path(tmp) / "profile"
            with open(Path(tmp) / "chrome.log", "wb") as log:
                chrome = subprocess.Popen(
                    [binary, "--headless=new", "--no-sandbox",
                     "--disable-dev-shm-usage", "--disable-gpu", "--no-first-run",
                     "--no-default-browser-check", "--remote-debugging-port=0",
                     f"--user-data-dir={profile}", "--window-size=800,600",
                     f"--force-device-scale-factor={dpr}", "about:blank"],
                    stdout=log, stderr=log, start_new_session=True)
                try:
                    portfile = profile / "DevToolsActivePort"
                    eventually(lambda: portfile.exists() and len(portfile.read_text().splitlines()) >= 2)
                    port = int(portfile.read_text().splitlines()[0])
                    def target():
                        pages = json.load(urllib.request.urlopen(
                            f"http://127.0.0.1:{port}/json/list", timeout=2))
                        return next((x for x in pages if x["type"] == "page"
                                     and x["url"] == "about:blank"), None)
                    page = eventually(target)
                    c = CDP(page["webSocketDebuggerUrl"])
                    try:
                        frame = c.call("Page.getFrameTree")["frameTree"]["frame"]["id"]
                        c.call("Page.setDocumentContent",
                               {"frameId": frame, "html": source_page})
                        eventually(lambda: c.eval("!!document.querySelector('#text')"))
                        # One negative and one deliberately perturbed positive control.
                        stable = c.compare()
                        assert stable == [], ("negative control", stable)
                        c.eval("scrollTo(0,0)")
                        positive = c.compare(lambda: c.eval("scrollTo(0,240)"))
                        assert "visual.pageY" in positive and "layout.pageY" in positive, positive
                        print(json.dumps({"test": "geometry-positive-negative-controls",
                                          "status": "PASS", "dpr": dpr,
                                          "positive_keys": positive}), flush=True)
                        for delay_ms in (0, 100):
                            changes = []
                            for trial in range(N):
                                c.eval("scrollTo(0,0)")
                                eventually(lambda: c.eval("scrollY===0"))
                                count = len(c.eval("events.filter(e=>e.type==='wheel')"))
                                c.call("Input.dispatchMouseEvent", {"type": "mouseWheel",
                                      "x": 400, "y": 400, "deltaX": 0, "deltaY": 80})
                                eventually(lambda: len(c.eval("events.filter(e=>e.type==='wheel')")) == count + 1)
                                c.eval("scrollTo(0,0)")
                                eventually(lambda: c.eval("scrollY===0"))
                                if delay_ms:
                                    time.sleep(delay_ms / 1000)
                                changes.append(c.compare())
                            print(json.dumps({"test": "post-wheel-geometry", "dpr": dpr,
                                              "delay_ms": delay_ms, "samples": N,
                                              "unequal": sum(bool(x) for x in changes),
                                              "changed_keys": sorted({key for row in changes for key in row}),
                                              "status": "OBSERVED_NOT_ACCEPTANCE"}), flush=True)
                    finally:
                        c.close()
                finally:
                    chrome.terminate()
                    try:
                        chrome.wait(timeout=4)
                    except subprocess.TimeoutExpired:
                        chrome.kill()
                        chrome.wait(timeout=4)
    print(json.dumps({"scope": "reduced Chrome + exact upstream PAGE and geometry ordering, "
                 "not pinned cdp-tty execution, not root-cause confirmation",
                 "chromium": subprocess.check_output([binary, "--version"],
                                                    text=True).strip()}), flush=True)


if __name__ == "__main__":
    run()
