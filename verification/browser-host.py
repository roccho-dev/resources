# Executed by the NixOS test driver; machine names come from browser-host.nix.
import json
import shlex

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
