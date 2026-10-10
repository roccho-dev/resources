# Executed by the NixOS test driver; machine names come from browser-host.nix.
import json
import shlex
import time
from pathlib import Path
from PIL import Image

start_all()
browser.wait_for_unit("test-chrome.service")
browser.wait_for_open_port(9222)
browser.wait_for_unit("sshd.service")
identity = json.loads(browser.succeed("curl -fsS http://127.0.0.1:9222/json/list"))
pages = [page for page in identity if page["type"] == "page"]
assert len(pages) == 1, "fixture must start with exactly one existing page"
target = pages[0]["id"]
process = browser.succeed("systemctl show -p MainPID --value test-chrome.service").strip()
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
assert browser.succeed("systemctl show -p MainPID --value test-chrome.service").strip() == process
final = json.loads(browser.succeed("curl -fsS http://127.0.0.1:9222/json/list"))
assert [p["id"] for p in final if p["type"] == "page"] == [target]
print(json.dumps({"test": "vm-session-smoke", "status": "PASS", "remote_clients": 2,
                  "scope": "VM boot / concurrent same-target observation / SSH detach and reattach",
                  "preapply": "NOT_PROVEN"}))

# E02: QEMU captures actual display scanout, never a fake Kitty sink or CDP image.
def pixels(name):
    browser.screenshot(name)
    with Image.open(Path(browser.out_dir) / (name + ".png")) as image:
        counts = image.convert("RGB").getcolors(image.width * image.height)
        assert counts is not None
        expected = ((239, 24, 43), (32, 208, 79), (40, 95, 234))
        return [sum(count for count, color in counts
                    if all(abs(a - b) <= 3 for a, b in zip(color, wanted)))
                for wanted in expected]


try:
    browser.succeed("chvt 2; systemctl start bcon-test")
    browser.wait_for_unit("bcon-test.service")
    browser.wait_until_succeeds("pgrep -x login", timeout=30)
    before = pixels("bcon-before")
    assert min(before) < 100, "negative control unexpectedly contains the fixture"
    browser.send_chars("root\n")
    browser.wait_until_succeeds("pgrep -t pts/0 -x bash", timeout=30)
    browser.succeed("printf '%s' " + shlex.quote(pages[0]["webSocketDebuggerUrl"]) + " > /run/browser-target")
    browser.send_chars('cdp-tty "$(cat /run/browser-target)"\n')
    browser.wait_until_succeeds("pgrep -x cdp-tty", timeout=30)
    deadline = time.monotonic() + 30
    while True:
        colors = pixels("bcon-browser")
        if min(colors) > 1000:
            break
        assert time.monotonic() < deadline, "Chrome fixture not rendered by actual bcon: " + str(colors)
        time.sleep(1)
    print(json.dumps({"test": "real-bcon-chrome-render", "status": "PASS",
                      "colored_pixels": colors, "preapply": "NOT_PROVEN"}))
finally:
    browser.execute("journalctl -b -u bcon-test --no-pager -n 100")
