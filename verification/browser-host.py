# Executed by the NixOS test driver; machine names come from browser-host.nix.
import json
import shlex
import time
from pathlib import Path
from PIL import Image

start_all()
browser.wait_for_unit("browser-host.service")
browser.wait_for_open_port(9222)
browser.wait_for_unit("sshd.service")
identity = json.loads(browser.succeed("curl -fsS http://127.0.0.1:9222/json/list"))
pages = [page for page in identity if page["type"] == "page"]
assert len(pages) == 1, "fixture must start with exactly one existing page"
target = pages[0]["id"]
process = browser.succeed("systemctl show -p MainPID --value browser-host.service").strip()
assert int(process) > 0
host_key = browser.succeed("cat /etc/ssh/ssh_host_ed25519_key.pub").strip()
browser.succeed("install -d -m 700 /root/.ssh")
browser.succeed("touch /root/.ssh/authorized_keys; chmod 600 /root/.ssh/authorized_keys")
tunnel = "ssh -M -S /tmp/browser-ssh -fNT -o ExitOnForwardFailure=yes -L 127.0.0.1:19222:127.0.0.1:9222 root@browser"
read_target = "curl -fsS http://127.0.0.1:19222/json/list"
clients = (remoteA, remoteB)
for client in clients:
    client.wait_for_unit("multi-user.target")
    client.succeed("command -v curl; command -v ssh; command -v pgrep")
    client.succeed("install -d -m 700 /root/.ssh; ssh-keygen -q -t ed25519 -N '' -f /root/.ssh/id_ed25519")
    public_key = client.succeed("cat /root/.ssh/id_ed25519.pub").strip()
    browser.succeed("printf '%s\\n' " + shlex.quote(public_key) + " >> /root/.ssh/authorized_keys")
    client.succeed("printf '%s\\n' " + shlex.quote("browser " + host_key) + " > /root/.ssh/known_hosts")
    # Failure is meaningful only because curl is verified above and SSH works below.
    client.fail("curl --connect-timeout 2 --max-time 3 -fsS http://browser:9222/json/list")
    client.succeed(tunnel)

# Both independent tunnels stay live during observation and the A reconnect.
for client in clients:
    observed = json.loads(client.succeed(read_target))
    assert [p["id"] for p in observed if p["type"] == "page"] == [target]
    client.fail("pgrep -f '[c]hrom(e|ium)'")
remoteA.succeed("ssh -S /tmp/browser-ssh -O exit root@browser")
assert [p["id"] for p in json.loads(remoteB.succeed(read_target)) if p["type"] == "page"] == [target]
remoteA.succeed(tunnel)
for client in clients:
    rebound = json.loads(client.succeed(read_target))
    assert [p["id"] for p in rebound if p["type"] == "page"] == [target]
    client.succeed("ssh -S /tmp/browser-ssh -O exit root@browser")
assert browser.succeed("systemctl show -p MainPID --value browser-host.service").strip() == process
final = json.loads(browser.succeed("curl -fsS http://127.0.0.1:9222/json/list"))
assert [p["id"] for p in final if p["type"] == "page"] == [target]
print(json.dumps({"test": "vm-session-smoke", "status": "PASS", "remote_clients": 2,
                  "scope": "VM boot / concurrent same-target observation / SSH detach and reattach",
                  "preapply": "NOT_PROVEN"}))

# Actual QEMU scanout, never a fake Kitty sink or a CDP screenshot.
def pixels(name):
    browser.screenshot(name)
    with Image.open(Path(browser.out_dir) / (name + ".png")) as image:
        counts = image.convert("RGB").getcolors(image.width * image.height)
        assert counts is not None
        expected = ((239, 24, 43), (32, 208, 79), (40, 95, 234), (232, 203, 41))
        return [sum(count for count, color in counts
                    if all(abs(a - b) <= 3 for a, b in zip(color, wanted)))
                for wanted in expected]


def wait_pixels(name, predicate):
    deadline = time.monotonic() + 30
    while True:
        colors = pixels(name)
        if predicate(colors):
            return colors
        assert time.monotonic() < deadline, "Missing rendered fixture: " + str(colors)
        time.sleep(1)


def wait_process(command, timeout=30):
    # Preserve the first failure; no restart/recovery that hides initialization state.
    deadline = time.monotonic() + timeout
    while True:
        status, output = browser.execute(command, timeout=5)
        if status == 0:
            return output.strip()
        assert time.monotonic() < deadline, "Process readiness failed: " + command
        time.sleep(1)


def page_state():
    # Independent, fixed fixture read. Never inject input through the oracle.
    script = """import json, pathlib, websocket
from contextlib import closing
with closing(websocket.create_connection(pathlib.Path('/run/browser-target').read_text(),
                                 timeout=5, suppress_origin=True)) as ws:
    ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate', 'params': {
        'expression': '({text:document.getElementById("text").value,scrollY:window.scrollY,wheels:window.wheelEvents})',
        'returnByValue': True}}))
    for _ in range(100):
        reply = json.loads(ws.recv())
        if reply.get('id') == 1:
            assert 'error' not in reply and 'exceptionDetails' not in reply.get('result', {})
            print(json.dumps(reply['result']['result']['value']))
            break
    else:
        raise AssertionError('missing CDP result')
"""
    return json.loads(browser.succeed("python3 -c " + shlex.quote(script)))


def browser_geometry():
    # Read-only, independent CDP probe. Exact fields mirror pinned cdp.c
    # geometry(); this never sends input or modifies Chrome/CDP settings.
    script = """import json, pathlib, websocket
from contextlib import closing
with closing(websocket.create_connection(
        pathlib.Path('/run/browser-target').read_text(),
        timeout=5, suppress_origin=True)) as ws:
    def request(i, method, params):
        ws.send(json.dumps({'id': i, 'method': method, 'params': params}))
        for _ in range(100):
            message = json.loads(ws.recv())
            if message.get('id') == i:
                assert 'error' not in message, (method, message['error'])
                return message['result']
        raise AssertionError('missing CDP response: ' + method)
    metrics = request(1, 'Page.getLayoutMetrics', {})
    tree = request(2, 'Page.getFrameTree', {})
    view = request(3, 'Runtime.evaluate', {
        'expression': '({width:innerWidth,height:innerHeight,dpr:devicePixelRatio})',
        'returnByValue': True, 'throwOnSideEffect': True,
        'silent': True, 'timeout': 1000})
    assert 'exceptionDetails' not in view
    print(json.dumps({
        'visual': metrics.get('cssVisualViewport'),
        'layout': metrics.get('cssLayoutViewport'),
        'loader': tree.get('frameTree', {}).get('frame', {}).get('loaderId'),
        'view': view.get('result', {}).get('value')}))
"""
    status, output = browser.execute("python3 -c " + shlex.quote(script), timeout=8)
    if status:
        return {"probe": "unavailable", "exit": status}
    try:
        return json.loads(output)
    except ValueError:
        return {"probe": "invalid-response"}


def viewer_write_activity():
    # Passive /proc sample. Distinguishes no redraw from substantial output,
    # but a write counter alone is not proof that Kitty acknowledged the image.
    status, output = browser.execute(
        "p=$(pgrep -x cdp-tty) && awk '$1 == \"wchar:\" || $1 == \"syscw:\" {print $1, $2}' /proc/$p/io",
        timeout=5)
    if status:
        return None
    try:
        return {key.rstrip(":"): int(value) for key, value in
                (line.split() for line in output.splitlines())}
    except (TypeError, ValueError):
        return None


def viewer_observation(phase, shot):
    # Observe without sending CDP input; early failure is not Ctrl-Q success.
    exited = browser.execute("test -f /run/viewer-exit-status")[0] == 0
    observation = {
        "test": "viewer-timeline", "phase": phase,
        "process_live": browser.execute("pgrep -x cdp-tty")[0] == 0,
        "early_exit": exited,
        "exit": browser.succeed("cat /run/viewer-exit-status").strip() if exited else None,
        "stderr": browser.succeed("cat /run/viewer-errors").strip(),
        "pixels": pixels(shot),
        "geometry": browser_geometry(),
        "viewer_writes": viewer_write_activity(),
    }
    print(json.dumps(observation), flush=True)
    return observation


try:
    # The shared module, not a test-only chvt, must activate tty2 on boot.
    browser.succeed("test \"$(cat /sys/class/tty/tty0/active)\" = tty2")
    # Regression: service availability is not proof while autovt's agetty owns tty2.
    browser.fail("pgrep -f '[a]getty .*tty2'")
    browser.succeed("systemctl is-enabled browser-host-terminal.service")
    browser.wait_for_unit("browser-host-terminal.service")
    wait_process("pgrep -x login")
    before = pixels("bcon-before")
    assert min(before[:3]) < 100, "negative control unexpectedly contains the fixture"
    browser.send_chars("root\n")
    wait_process("pgrep -t pts/0 -x bash")
    saved_mode = browser.succeed("stty -F /dev/pts/0 -g").strip()
    browser.succeed("printf '%s' " + shlex.quote(pages[0]["webSocketDebuggerUrl"]) + " > /run/browser-target")
    browser.succeed("rm -f /run/viewer-exit-status /run/viewer-errors")
    # Capture the original shell child status; pgrep disappearance alone is not a clean exit.
    browser.send_chars('cdp-tty "$(cat /run/browser-target)" 2>/run/viewer-errors; printf "%s\\n" "$?" > /run/viewer-exit-status\n')
    wait_process("pgrep -x cdp-tty")
    colors = wait_pixels("bcon-browser", lambda colors: min(colors[:3]) > 1000)
    assert page_state() == {"text": "", "scrollY": 0, "wheels": 0}
    # Settle the terminal acknowledgement before the one deliberately sent key.
    time.sleep(1)
    browser.send_chars("a")
    deadline = time.monotonic() + 10
    while page_state()["text"] != "a":
        assert time.monotonic() < deadline, "physical-key route did not change the fixture"
        time.sleep(0.2)
    changed = wait_pixels("bcon-input", lambda colors: colors[3] > 1000)
    # Negative control: no wheel and no new input; baseline should remain live
    # beyond tty.c's 3-second no-ACK timeout.
    for second in range(1, 5):
        time.sleep(1)
        idle = viewer_observation(f"ascii-idle-{second}s", "bcon-idle")
        assert idle["process_live"] and not idle["early_exit"], "viewer died without wheel"
        assert min(idle["pixels"][:3]) > 1000, "baseline RGB fixture vanished without wheel"
    print(json.dumps({"test": "pre-wheel-geometry", "geometry": browser_geometry()}), flush=True)
    # QMP injects a virtual physical wheel; the independent CDP client only reads.
    assert browser.qmp_client is not None
    for down in (True, False):
        # Pinned QMPSession.send annotates scalar values, but QMP events is an array.
        # Keep this one annotation exception local; payload and outcome checks stay intact.
        result = browser.qmp_client.send("input-send-event", {"events": [  # type: ignore[dict-item]
            {"type": "btn", "data": {"button": "wheel-down", "down": down}}]})
        assert "return" in result, "QMP wheel injection rejected: " + repr(result)
    deadline = time.monotonic() + 10
    while True:
        state = page_state()
        assert state["wheels"] <= 1, "duplicated wheel event: " + repr(state)
        if state["wheels"] == 1 and state["scrollY"] > 0:
            break
        assert time.monotonic() < deadline, "virtual wheel did not reach page: " + repr(state)
        time.sleep(0.2)
    # Scroll 80 leaves half of each 160px tile. All-zero RGB is NOT a redraw.
    # Sample >3s so pre-quit viewer failure cannot masquerade as Ctrl-Q success.
    wheel_samples = []
    for index in range(8):
        sample = viewer_observation(f"wheel-sample-{index}", f"bcon-wheel-{index}")
        wheel_samples.append(sample)
        if not sample["process_live"] or sample["early_exit"]:
            break
        time.sleep(0.5)
    wheel_frames = [s for s in wheel_samples if s["process_live"] and
                    min(s["pixels"][:3]) > 1000 and
                    sum(s["pixels"][:3]) < sum(colors[:3]) - 3000]
    assert all(s["process_live"] and not s["early_exit"] for s in wheel_samples), \
        "viewer exited after wheel before Ctrl-Q: " + repr(wheel_samples[-1])
    assert wheel_frames, "wheel DOM changed, but no valid VT RGB redraw"
    wheel_frame = wheel_frames[-1]["pixels"]
    print(json.dumps({"test": "real-bcon-wheel", "status": "PASS",
                      "wheel_events": state["wheels"], "page_scrollY": state["scrollY"],
                      "before_pixels": colors[:3], "after_pixels": wheel_frame[:3],
                      "scope": "one QEMU wheel event via bcon/cdp-tty + independent DOM and VT RGB; no blank frames",
                      "preapply": "NOT_PROVEN"}))
    quit_ready = viewer_observation("before-ctrl-q", "bcon-pre-quit")
    assert quit_ready["process_live"] and not quit_ready["early_exit"], \
        "viewer already terminated before Ctrl-Q"
    browser.send_key("ctrl-q")
    wait_process("test -f /run/viewer-exit-status", timeout=10)
    viewer_exit = browser.succeed("cat /run/viewer-exit-status").strip()
    viewer_stderr = browser.succeed("cat /run/viewer-errors").strip()
    print(json.dumps({"test": "viewer-ctrl-q-outcome", "exit": viewer_exit,
                      "stderr": viewer_stderr}))
    assert viewer_exit == "0", "Ctrl-Q did not end viewer cleanly"
    assert not viewer_stderr, "Ctrl-Q viewer had an error message"
    wait_process("! pgrep -x cdp-tty", timeout=10)
    assert browser.succeed("stty -F /dev/pts/0 -g").strip() == saved_mode
    # Negative control: the exact exit-code capture must reject a failed attach.
    browser.succeed("rm -f /run/viewer-negative-exit /run/viewer-negative-errors")
    browser.send_chars('cdp-tty ws://127.0.0.1:1/devtools/page/none 2>/run/viewer-negative-errors; printf "%s\\n" "$?" > /run/viewer-negative-exit\n')
    wait_process("test -f /run/viewer-negative-exit", timeout=10)
    negative_exit = browser.succeed("cat /run/viewer-negative-exit").strip()
    negative_error = browser.succeed("cat /run/viewer-negative-errors").strip()
    print(json.dumps({"test": "viewer-failed-attach-negative-control",
                      "exit": negative_exit, "stderr": negative_error}))
    assert negative_exit == "1", "failed attach must exit nonzero"
    assert "connection, terminal or frame rejected" in negative_error
    assert browser.succeed("systemctl show -p MainPID --value browser-host.service").strip() == process
    final = json.loads(browser.succeed("curl -fsS http://127.0.0.1:9222/json/list"))
    assert [p["id"] for p in final if p["type"] == "page"] == [target]
    print(json.dumps({"test": "real-bcon-viewer", "status": "PASS",
                      "rendered_pixels": colors, "after_input_pixels": changed,
                      "scope": "real VT / ASCII / DOM and display; Ctrl-Q exit 0 and empty stderr / failed attach exit 1",
                      "preapply": "NOT_PROVEN"}))

    # E08 finite positive/negative: the *existing Host Chrome target* opens a
    # Remote A localhost HTTP fixture through reverse SSH, then the route dies
    # without killing Chrome. This does not claim Atlas/SSE coverage.
    preview_html = '<!doctype html><meta charset="utf-8"><main id="proof">REMOTE-A-PREVIEW-615</main>'
    remoteA.succeed("mkdir -p /tmp/host-preview && printf '%s' " +
                    shlex.quote(preview_html) + " > /tmp/host-preview/index.html")
    remoteA.succeed("nohup python3 -m http.server 18080 --bind 127.0.0.1 "
                    "--directory /tmp/host-preview >/tmp/host-preview.log 2>&1 </dev/null &")
    remoteA.wait_for_open_port(18080)
    remoteA.succeed("curl -fsS http://127.0.0.1:18080/index.html")
    # A direct Host request is refused before SSH forwarding, by construction.
    preview_url = "http://127.0.0.1:18080/index.html"
    browser.fail("curl --connect-timeout 1 --max-time 2 -fsS " + preview_url)
    remoteA.succeed("ssh -M -S /tmp/host-preview-ssh -fNT "
                    "-o ExitOnForwardFailure=yes "
                    "-R 127.0.0.1:18080:127.0.0.1:18080 root@browser")
    assert browser.succeed("curl -fsS " + preview_url) == preview_html

    # Fixture setup navigates the one existing tab, not a second browser/tab.
    # The oracle only reads DOM after this explicit test-only navigation.
    preview_probe = """import json, pathlib, time, websocket
ws = websocket.create_connection(pathlib.Path('/run/browser-target').read_text(),
                                 timeout=5, suppress_origin=True)
def call(ident, method, params):
    ws.send(json.dumps({'id': ident, 'method': method, 'params': params}))
    while True:
        reply = json.loads(ws.recv())
        if reply.get('id') == ident:
            assert 'error' not in reply, (method, reply.get('error'))
            return reply['result']
response = call(1, 'Page.navigate', {'url': 'http://127.0.0.1:18080/index.html'})
assert 'errorText' not in response, response
deadline = time.monotonic() + 12
for index in range(2, 80):
    result = call(index, 'Runtime.evaluate', {
        'expression': '({marker:document.querySelector("#proof")?.textContent || "",url:location.href})',
        'returnByValue': True})['result']['value']
    if result == {'marker': 'REMOTE-A-PREVIEW-615',
                  'url': 'http://127.0.0.1:18080/index.html'}:
        print(json.dumps(result))
        break
    assert time.monotonic() < deadline, 'Host Chrome did not render remote preview: ' + repr(result)
    time.sleep(0.15)
else:
    raise AssertionError('preview DOM missing')
ws.close()
"""
    preview_dom = json.loads(browser.succeed("python3 -c " + shlex.quote(preview_probe)))
    assert preview_dom["marker"] == "REMOTE-A-PREVIEW-615"
    assert browser.succeed("systemctl show -p MainPID --value browser-host.service").strip() == process
    same_page = json.loads(browser.succeed("curl -fsS http://127.0.0.1:9222/json/list"))
    assert [p["id"] for p in same_page if p["type"] == "page"] == [target]
    remoteA.succeed("ssh -S /tmp/host-preview-ssh -O exit root@browser")
    browser.fail("curl --connect-timeout 1 --max-time 2 -fsS " + preview_url)
    assert browser.succeed("systemctl show -p MainPID --value browser-host.service").strip() == process
    print(json.dumps({"test": "remote-localhost-preview", "status": "PASS",
                      "browser_target_unchanged": True, "browser_pid_unchanged": True,
                      "remote_consumers": 1,
                      "scope": "SSH reverse localhost tunnel + existing Chrome DOM; "
                               "tunnel removal refused; Atlas/SSE/port-conflict NOT_RUN",
                      "preapply": "NOT_PROVEN"}))
finally:
    # Record the failing phase without mutating/restarting the tested service.
    for command in (
        "systemctl show browser-host-terminal -p MainPID -p ActiveState -p SubState -p NRestarts",
        "journalctl -b -u browser-host-terminal --no-pager -n 160",
        "ps -eo pid,ppid,tty,stat,wchan:32,args",
        "cat /sys/class/tty/tty0/active; ls -l /dev/dri/",
        "cat /run/viewer-errors 2>/dev/null",
        "cat /run/viewer-trace.jsonl 2>/dev/null",
    ):
        status, output = browser.execute(command, timeout=5)
        print(json.dumps({"diagnostic": command, "exit": status, "output": output}))