#!/usr/bin/env python3
"""Fixed Chromium Snapshot proof. Own new instance/profile only; never cleans up."""
import argparse
import base64
import hashlib
import json
import os
import pwd
import stat
from pathlib import Path
import re
import socket
import struct
import subprocess
import time
import urllib.request

def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

class CDP:
    def __init__(self, port, path):
        if not re.fullmatch(r"/devtools/browser/[0-9a-f-]+", path):
            raise ValueError("Unexpected browser endpoint")
        self.sock = socket.create_connection(("127.0.0.1", port), timeout=10)
        self.sock.settimeout(15)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
                           f"Upgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
                           "Sec-WebSocket-Version: 13\r\n\r\n").encode())
        response = b""
        deadline = time.monotonic()+15
        while not response.endswith(b"\r\n\r\n"):
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError("WebSocket handshake timeout")
            self.sock.settimeout(remaining)
            part = self.sock.recv(1)
            if not part:
                raise EOFError("WebSocket handshake closed")
            response += part
            if len(response) > 16384:
                raise ValueError("Oversized handshake")
        expected = base64.b64encode(hashlib.sha1((key+"258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        if not response.startswith(b"HTTP/1.1 101 ") or expected.encode() not in response:
            raise ValueError("WebSocket handshake refused")
        self.seq = 0

    def exact(self, n):
        out = b""
        deadline = time.monotonic()+15
        while len(out) < n:
            remaining = deadline-time.monotonic()
            if remaining <= 0:
                raise TimeoutError("CDP frame timeout")
            self.sock.settimeout(remaining)
            part = self.sock.recv(n-len(out))
            if not part:
                raise EOFError("CDP closed")
            out += part
        return out

    def send(self, value):
        raw = json.dumps(value).encode()
        mask = os.urandom(4)
        size = len(raw)
        header = bytes([0x81, 0x80 | size]) if size < 126 else bytes([0x81, 0xfe])+struct.pack("!H", size)
        self.sock.sendall(header+mask+bytes(v ^ mask[i % 4] for i, v in enumerate(raw)))

    def read(self):
        # Large chrome://credits results may use continuation frames.
        data = bytearray()
        first = True
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            head = self.exact(2)
            opcode = head[0] & 15
            if head[0] & 0x70 or head[1] & 0x80 or opcode != (1 if first else 0):
                raise ValueError("Unexpected CDP frame")
            size = head[1] & 127
            if size == 126:
                size = struct.unpack("!H", self.exact(2))[0]
            elif size == 127:
                size = struct.unpack("!Q", self.exact(8))[0]
            if len(data)+size > 16*1024*1024:
                raise ValueError("Oversized CDP message")
            data.extend(self.exact(size))
            if head[0] & 0x80:
                return json.loads(data)
            first = False
        raise TimeoutError("CDP message timeout")

    def call(self, method, params=None, session=None):
        self.seq += 1
        request = dict(id=self.seq, method=method, params=params or {})
        if session:
            request["sessionId"] = session
        self.send(request)
        deadline = time.monotonic()+20
        while time.monotonic() < deadline:
            result = self.read()
            if result.get("id") == self.seq:
                if "error" in result:
                    raise ValueError(result["error"])
                return result.get("result", {})
        raise TimeoutError("CDP response timeout")

def source_revision_evidence(reported, expected):
    if reported == "@"+expected:
        return "embedded-source-matches"
    if reported == "@"+"0"*40:
        # Upstream's non-official-build LASTCHANGE.dummy is not source evidence.
        # Archive provenance and the actual derived executable hash stay required.
        return "unavailable-upstream-dummy"
    raise ValueError("CDP source revision differs or is malformed")

def plain_ancestors(path):
    for parent in [path] + list(path.parents):
        if parent.is_symlink():
            raise ValueError(f"Symlink ancestor: {parent}")

def credits_evidence(observation):
    """Classify only the real credits DOM or the exact upstream Snapshot sample."""
    if not (observation.get("href") == "chrome://credits/" and
            observation.get("ready") == "complete" and observation.get("title") == "Credits"):
        return None
    text = observation.get("text", "")
    full = (observation.get("pageTitle") == "Credits" and observation.get("products", 0) > 0 and
            observation.get("licenseBlocks") == observation.get("products") and
            observation.get("completeProducts") == observation.get("products") and len(text) > 1000)
    if full:
        return dict(availability="bundled-full-credits", fullCreditsAvailable=True,
                    textKind="license-textContent", sha256=hashlib.sha256(text.encode()).hexdigest())
    sample = (observation.get("pageTitle") == "" and observation.get("products") == 0 and
              observation.get("licenseBlocks") == 0 and observation.get("completeProducts") == 0 and
              text == "" and observation.get("sampleLinkCount") == 1 and
              observation.get("sampleLinkTag") == "A" and observation.get("sampleLinkHref") == "#" and
              observation.get("sampleLinkText") == "Print" and observation.get("sampleText") == 'This is sample credits page. To get correct credits page, set `generate_about_credits=true` in args.gn. Print Layout tests are based on layout tests from webkit.org.')
    if not sample:
        return None
    return dict(availability="sample-only", fullCreditsAvailable=False,
                textKind="normalized-sample-body-textContent",
                sha256=hashlib.sha256(observation["sampleText"].encode()).hexdigest(),
                expectedSourceSampleSha256="c2a338c4f1f5f5e19d3020a25f8dc47e394ba4fed1ec2d8dc5b2a915170e02bc")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    args = parser.parse_args()
    package, result = args.package, args.result.absolute()
    if not str(package).startswith("/nix/store/") or not package.is_dir():
        raise ValueError("A source-built Nix output is required")
    allowed_parents = {Path("/work/repos/resources/.worktrees/windows-core-chromium-snapshot-20261023/.generated")}
    # Existing nix flake check runs the same installed helper in a disposable
    # normal builder. Accept only that builder's exact, known scratch directory.
    top = os.environ.get("NIX_BUILD_TOP", "")
    if top == "/build" or re.fullmatch(r"/tmp/nix-build-chromium-snapshot-cdp\.drv-[0-9]+", top):
        build_top = Path(top)
        plain_ancestors(build_top)
        if Path.cwd().resolve() == build_top.resolve():
            allowed_parents.add(build_top.resolve()/".generated")
    guest_parent = Path("/home/chromium-proof/.generated")
    guest_context = None
    if result.parent == guest_parent:
        # Only this existing test framework's source-bound, nonroot guest.
        account = pwd.getpwuid(os.getuid())
        if os.getuid() == 0 or account.pw_name != "chromium-proof" or account.pw_dir != "/home/chromium-proof":
            raise ValueError("Guest proof requires its dedicated nonroot user")
        for directory in [Path(account.pw_dir), guest_parent]:
            plain_ancestors(directory)
            metadata = directory.stat()
            if not stat.S_ISDIR(metadata.st_mode) or metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
                raise ValueError("Guest home/result parent ownership or mode differs")
        marker = Path("/etc/chromium-snapshot-cdp-guest.json")
        plain_ancestors(marker)
        metadata = marker.stat()
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_uid != 0 or metadata.st_mode & 0o022:
            raise ValueError("Guest source marker is not root-owned and protected")
        expected = dict(purpose="resources-chromium-snapshot-cdp-guest-v1",
                        package=str(package), proofSha256=sha(Path(__file__)))
        if json.loads(marker.read_text()) != expected:
            raise ValueError("Guest source marker differs")
        allowed_parents.add(guest_parent)
        guest_context = dict(uid=os.getuid(), user=account.pw_name, home=account.pw_dir,
                             marker=str(marker), markerSha256=sha(marker))
    if result.parent.resolve() not in allowed_parents or ".." in result.parts:
        raise ValueError("Result must be new in an exact source-bound proof namespace")
    plain_ancestors(result.parent)
    profile = result.with_suffix(".profile")
    stdout, stderr = result.with_suffix(".stdout"), result.with_suffix(".stderr")
    if any(p.exists() or p.is_symlink() for p in [result, profile, stdout, stderr]):
        raise ValueError("Proof paths already exist; no retry or overwrite")
    manifest = json.loads((package/"share/chromium/snapshot.json").read_text())
    exe = Path(manifest["executable"])
    if sha(exe) != manifest["executableSha256"] or sha(Path(__file__)) != manifest["proofSha256"]:
        raise ValueError("Derived executable/proof identity differs")
    with exe.open("rb") as stream:
        header = stream.read(20)
    if header[:5] != b"\x7fELF\x02" or header[18:20] != b"\x3e\x00":
        raise ValueError("Not an x86_64 ELF")
    record = dict(state="not-started", snapshot=manifest, profile=str(profile),
                  package=str(package), sandbox="enabled; no disabling flags", cleanup="none",
                  guestContext=guest_context)
    process, cdp = None, None
    owned_endpoint, close_requested = False, False
    code = 1
    try:
        # Crashpad uses the default config location independently of --user-data-dir.
        # Give only this child a new writable namespace; never fall back to user config.
        profile.mkdir(mode=0o700)
        child_env = dict(os.environ)
        child_state = {}
        for variable, leaf in [("CHROME_CONFIG_HOME", "config"), ("XDG_CONFIG_HOME", "config"),
                               ("XDG_CACHE_HOME", "cache"), ("BREAKPAD_DUMP_LOCATION", "crash")]:
            directory = profile/leaf
            directory.mkdir(mode=0o700, exist_ok=True)
            child_env[variable] = str(directory)
            child_state[variable] = str(directory)
        record["childState"] = child_state
        version = subprocess.run([manifest["launcher"], "--version"], capture_output=True, text=True, timeout=30, env=child_env)
        record["version"] = dict(exit=version.returncode, stdout=version.stdout, stderr=version.stderr)
        if version.returncode or version.stdout.strip() != "Chromium "+manifest["productVersion"]:
            raise ValueError("Actual Chromium product/version differs")
        argv = [manifest["launcher"], "--headless", "--no-first-run", "--no-default-browser-check",
                "--remote-debugging-address=127.0.0.1", "--remote-debugging-port=0",
                "--user-data-dir="+str(profile), "about:blank"]
        record["argv"] = argv
        with stdout.open("xb") as out, stderr.open("xb") as err:
            process = subprocess.Popen(argv, stdout=out, stderr=err, env=child_env)
        record.update(state="started", pid=process.pid)
        result.write_text(json.dumps(record, indent=2)+"\n")
        deadline = time.monotonic()+5
        while Path(f"/proc/{process.pid}/exe").resolve() != exe.resolve():
            if process.poll() is not None:
                raise RuntimeError("Launcher exited before executable identity readback")
            if time.monotonic() > deadline:
                raise ValueError("New process executable differs")
            time.sleep(0.01)
        port_file = profile/"DevToolsActivePort"
        deadline = time.monotonic()+30
        while not port_file.exists():
            if process.poll() is not None:
                record["exit"] = process.returncode
                raise RuntimeError("Browser exited before DevTools endpoint")
            if time.monotonic() > deadline:
                raise TimeoutError("Browser endpoint UNKNOWN; instance/profile preserved")
            time.sleep(0.1)
        plain_ancestors(port_file)
        lines = port_file.read_text().splitlines()
        if len(lines) != 2 or not lines[0].isdigit() or not 0 < int(lines[0]) < 65536:
            raise ValueError("Invalid private DevToolsActivePort")
        cdp = CDP(int(lines[0]), lines[1])
        record["cdpVersion"] = cdp.call("Browser.getVersion")
        owned_endpoint = True
        record["cdpRevisionEvidence"] = source_revision_evidence(
            record["cdpVersion"].get("revision"), manifest["sourceCommit"])
        if record["cdpVersion"].get("product") not in (
                "Chrome/"+manifest["productVersion"], "HeadlessChrome/"+manifest["productVersion"]):
            raise ValueError("CDP product version differs from the actual executable")
        target = cdp.call("Target.createTarget", {"url":"data:text/html,<title>resources-chromium-proof</title><p>snapshot-proof</p>"})["targetId"]
        session = cdp.call("Target.attachToTarget", {"targetId":target,"flatten":True})["sessionId"]
        for _ in range(50):
            evaluation = cdp.call("Runtime.evaluate", {"expression":"({title:document.title,value:6*7,body:document.body.textContent.trim()})","returnByValue":True}, session)
            if evaluation["result"].get("value") == dict(title="resources-chromium-proof", value=42, body="snapshot-proof"):
                break
            time.sleep(0.1)
        record["synthetic"] = evaluation
        if evaluation["result"].get("value") != dict(title="resources-chromium-proof", value=42, body="snapshot-proof"):
            raise ValueError("Fixed representative page failed")
        credits = cdp.call("Target.createTarget", {"url":"chrome://credits/"})["targetId"]
        cs = cdp.call("Target.attachToTarget", {"targetId":credits,"flatten":True})["sessionId"]
        # Official Snapshots can compile the exact upstream sample instead of full credits.
        # Observe and distinguish that supply limit without inventing missing notices.
        credits_expression = r"(() => { const products = Array.from(document.querySelectorAll('.product')); const licenses = Array.from(document.querySelectorAll('.product .license pre')); return {href: location.href, title: document.title, ready: document.readyState, pageTitle: document.querySelector('.page-title')?.textContent.trim() || '', products: products.length, licenseBlocks: licenses.length, completeProducts: products.filter(p => p.querySelector('.title')?.textContent.trim() && p.querySelectorAll('.license pre').length === 1 && p.querySelector('.license pre').textContent.trim()).length, text: licenses.map(p => p.textContent).join(String.fromCharCode(10)), sampleText: document.body?.textContent.replace(/\s+/g, ' ').trim() || '', sampleLinkCount: document.querySelectorAll('#print-link').length, sampleLinkTag: document.querySelector('#print-link')?.tagName || '', sampleLinkHref: document.querySelector('#print-link')?.getAttribute('href') || '', sampleLinkText: document.querySelector('#print-link')?.textContent.trim() || '', sampleLinkHidden: document.querySelector('#print-link')?.hidden ?? null}; })()"
        text, credits_ready = "", False
        deadline = time.monotonic()+30
        while time.monotonic() < deadline:
            answer = cdp.call("Runtime.evaluate", {"expression":credits_expression,"returnByValue":True}, cs)
            observation = answer["result"].get("value") or {}
            text = observation.get("text", "")
            record["credits"] = {k:v for k,v in observation.items() if k not in ("text", "sampleText")}
            record["credits"]["characters"] = len(text)
            evidence = credits_evidence(observation)
            credits_ready = evidence is not None
            if credits_ready:
                record["credits"].update(evidence)
            if credits_ready:
                break
            time.sleep(0.1)
        if not credits_ready:
            raise ValueError("Unrecognized credits page; neither full credits nor the exact upstream sample")
        close_requested = True
        cdp.seq += 1
        cdp.send(dict(id=cdp.seq, method="Browser.close", params={}))
        record["exit"] = process.wait(timeout=15)
        if record["exit"] != 0:
            raise ValueError("Owned instance did not close cleanly")
        record["state"], code = "pass-representative-cdp-only", 0
    except Exception as error:
        record["error"] = type(error).__name__+": "+str(error)
        if owned_endpoint and not close_requested and process.poll() is None:
            close_requested = True
            try:
                cdp.seq += 1
                cdp.send(dict(id=cdp.seq, method="Browser.close", params={}))
                record["failureCloseExit"] = process.wait(timeout=15)
            except Exception as close_error:
                record["failureCloseUnknown"] = str(close_error)
        record["state"] = "hold" if process is None or process.poll() is not None else "unknown-live-instance-preserved"
        if process is not None:
            record["exit"] = process.poll()
    finally:
        record["existingProfilesOrInstances"] = "unused"
        result.write_text(json.dumps(record, indent=2)+"\n")
    print(json.dumps(record))
    return code

if __name__ == "__main__":
    raise SystemExit(main())
