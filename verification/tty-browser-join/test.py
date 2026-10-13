# SPDX-License-Identifier: GPL-3.0-or-later
# Port of the ordinary-input section of Meltype#2@d673872 tests/bcon.py.
# Only this VM's keyboard enters text. The second CDP connection observes it.
import hashlib
import json
from pathlib import Path
import shlex
import time
from PIL import Image

start_all()
machine.wait_for_unit("c-console.service")
machine.wait_for_unit("c-browser.service")
machine.succeed('test "$(cat /sys/class/tty/tty0/active)" = tty2')
machine.wait_until_succeeds("pgrep -x login")
machine.wait_until_succeeds("journalctl -u c-console.service --no-pager | grep -F 'All phases complete, entering main loop'")
machine.send_chars("root\n")
machine.wait_until_succeeds("pgrep -t pts/0 -x bash")
machine.succeed("mkdir -p /run/c-proof")

# Setup is not input proof; never write the editor's value from this observer.
probe = r'''import json,sys,urllib.request,websocket
from pathlib import Path
with urllib.request.urlopen('http://127.0.0.1:9222/json/list',timeout=2) as response:
    pages=[p for p in json.load(response) if p.get('type')=='page']
assert len(pages)==1,pages
page=pages[0]
identity=Path('/run/c-proof/target')
if identity.exists(): assert identity.read_text()==page['id']
else: identity.write_text(page['id'])
Path('/run/c-proof/ws').write_text(page['webSocketDebuggerUrl'])
ws=websocket.create_connection(page['webSocketDebuggerUrl'],timeout=2,suppress_origin=True)
try:
    ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{
        'expression':"JSON.stringify({text:document.getElementById('editor').value,focus:document.activeElement.id})",
        'returnByValue':True,'throwOnSideEffect':True}}))
    while True:
        data=json.loads(ws.recv())
        if data.get('id')==1: break
    assert 'error' not in data and 'exceptionDetails' not in data['result'],data
    value=json.loads(data['result']['result']['value'])
    assert value=={'text':sys.argv[1],'focus':'editor'},value
    print(json.dumps({'target':page['id'],**value},ensure_ascii=False))
finally: ws.close()
'''
machine.succeed("printf %s " + shlex.quote(probe) + " > /run/c-proof/probe.py")

def observed(text):
    return "python3 /run/c-proof/probe.py " + shlex.quote(text)

machine.wait_until_succeeds(observed(""))
browser_pid = machine.succeed("systemctl show -p MainPID --value c-browser").strip()
assert browser_pid.isdigit() and int(browser_pid) > 0
pins = json.loads(machine.succeed("cat /etc/c-source-pins.json"))
executables = machine.succeed("sha256sum $(readlink -f $(command -v cdp-tty)) $(readlink -f $(command -v meltype-tty)) $(readlink -f $(command -v bcon))")

# Compare termios in the same foreground-command phase, not Readline's prompt.
# --raw-text is scoped to this known text fixture; it is not secret-field proof.
script = '''stty -g > /run/c-proof/before
meltype-tty --raw-text -- cdp-tty "$(cat /run/c-proof/ws)" 2>/run/c-proof/errors
rc=$?
stty -g > /run/c-proof/after
printf %s "$rc" > /run/c-proof/exit
'''
machine.succeed("printf %s " + shlex.quote(script) + " > /run/c-proof/trial")
machine.send_chars("bash /run/c-proof/trial\n")

def scanout(name):
    machine.screenshot(name)
    with Image.open(Path(machine.out_dir) / (name + ".png")) as image:
        return image.convert("RGB").copy()

def pixels(image, color):
    return sum(n for n, rgb in image.getcolors(image.width * image.height)
        if all(abs(a - b) <= 2 for a, b in zip(rgb, color)))

def await_image(name, predicate):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        status, _ = machine.execute("test -e /run/c-proof/exit")
        assert status != 0, machine.succeed("cat /run/c-proof/exit /run/c-proof/errors")
        image = scanout(name)
        if predicate(image):
            return image
        time.sleep(.2)
    raise AssertionError("C scanout missing: " + name)

base = await_image("browser-before", lambda im: pixels(im, (215, 225, 240)) > 2000)
machine.send_chars("nihongo ")
await_image("candidate", lambda im: pixels(im, (24, 26, 32)) > pixels(base, (24, 26, 32)) + 1000)
machine.succeed(observed(""))  # Preedit has not leaked to the browser.
machine.send_key("ret")
machine.wait_until_succeeds(observed("日本語"))
scanout("browser-after")
machine.send_key("ctrl-q")
machine.wait_until_succeeds("test -e /run/c-proof/exit")
assert machine.succeed("cat /run/c-proof/exit").strip() == "0"
assert machine.succeed("cat /run/c-proof/before") == machine.succeed("cat /run/c-proof/after")
assert machine.succeed("systemctl show -p MainPID --value c-browser").strip() == browser_pid
readback = json.loads(machine.succeed(observed("日本語")))
machine.fail("pgrep -f '[f]citx5|[i]bus-daemon|[t]tyskk'")
proof = {
    "gate": "C_ORDINARY_INPUT_SMOKE_ONLY", "status": "PASS", "pins": pins,
    "executables_sha256": executables, "readback": readback,
    "candidate_png_sha256": hashlib.sha256((Path(machine.out_dir) / "candidate.png").read_bytes()).hexdigest(),
    "terminal_restored": True, "browser_pid_preserved": True,
    "input": "NixOS VM keyboard", "provider": "NOT_RUN",
    "C1_C7": "NOT_COMPLETE", "typed_proposals": "NOT_RUN",
    "physical_host": "NOT_RUN", "independent_review": "NOT_RUN",
}
(Path(machine.out_dir) / "raws.jsonl").write_text(json.dumps(proof, ensure_ascii=False) + "\n")
print(json.dumps(proof, ensure_ascii=False), flush=True)
