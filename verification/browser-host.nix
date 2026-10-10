# First executable closure step. This is NOT full pre-apply acceptance.
# Reuse the package set selected by ops #426; never silently select another lock node.
let
  pkgs = import (builtins.fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/1c3fe55ad329cbcb28471bb30f05c9827f724c76.tar.gz";
    sha256 = "sha256-bxrdOn8SCOv8tN4JbTF/TXq7kjo9ag4M+C8yzzIRYbE=";
  }) { system = "x86_64-linux"; };
  remote = { ... }: {
    environment.systemPackages = [ pkgs.curl pkgs.openssh ];
    virtualisation.memorySize = 512;
  };
in pkgs.testers.runNixOSTest {
  name = "browser-host-session";
  nodes = {
    browser = { ... }: {
      virtualisation.memorySize = 2048;
      environment.systemPackages = [ pkgs.curl pkgs.openssh ];
      users.users.browser = { isSystemUser = true; group = "browser"; };
      users.groups.browser = { };
      services.openssh.enable = true;
      # Disposable VM only; no production credentials or external network listener.
      services.openssh.settings.PermitRootLogin = "prohibit-password";
      systemd.services.test-chrome = {
        wantedBy = [ "multi-user.target" ];
        environment.HOME = "/var/lib/test-chrome";
        serviceConfig = {
          User = "browser";
          StateDirectory = "test-chrome";
          ExecStart = "${pkgs.chromium}/bin/chromium --headless --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir=/var/lib/test-chrome/profile --window-size=800,600 about:blank";
          Restart = "no";
        };
      };
    };
    remoteA = remote;
    remoteB = remote;
  };
  testScript = ''
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
    for client in (remoteA, remoteB):
        client.wait_for_unit("multi-user.target")
        client.succeed("install -d -m 700 /root/.ssh; ssh-keygen -q -t ed25519 -N '' -f /root/.ssh/id_ed25519")
        public_key = client.succeed("cat /root/.ssh/id_ed25519.pub").strip()
        browser.succeed("printf '%s\\n' " + shlex.quote(public_key) + " >> /root/.ssh/authorized_keys")
        client.succeed("printf '%s\\n' " + shlex.quote("browser " + host_key) + " > /root/.ssh/known_hosts")
        # Direct remote CDP must fail; only an authenticated SSH path is tested here.
        client.fail("curl --connect-timeout 2 --max-time 3 -fsS http://browser:9222/json/list")
        client.succeed(tunnel)
        observed = json.loads(client.succeed("curl -fsS http://127.0.0.1:19222/json/list"))
        assert [p["id"] for p in observed if p["type"] == "page"] == [target]
        client.fail("pgrep -f '[c]hrom(e|ium)' ")
        client.succeed("ssh -S /tmp/browser-ssh -O exit root@browser")
        client.succeed(tunnel)
        rebound = json.loads(client.succeed("curl -fsS http://127.0.0.1:19222/json/list"))
        assert [p["id"] for p in rebound if p["type"] == "page"] == [target]
        client.succeed("ssh -S /tmp/browser-ssh -O exit root@browser")
    assert browser.succeed("systemctl show -p MainPID --value test-chrome.service").strip() == process
    final = json.loads(browser.succeed("curl -fsS http://127.0.0.1:9222/json/list"))
    assert [p["id"] for p in final if p["type"] == "page"] == [target]
    print(json.dumps({"test": "vm-session-smoke", "status": "PASS", "remote_clients": 2,
                      "scope": "VM boot / same target / SSH detach and reattach",
                      "preapply": "NOT_PROVEN",
                      "remaining": ["bcon-render", "cdp-tty-input", "IME", "writer-isolation",
                                    "unknown-effects", "profile-recovery", "preview", "performance",
                                    "target-hardware"]}))
  '';
}
