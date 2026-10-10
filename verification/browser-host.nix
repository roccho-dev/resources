# First executable closure step; NOT full pre-apply acceptance.
# Exact package set selected by ops #426, without unrelated private flake inputs.
let
  pkgs = import (builtins.fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/1c3fe55ad329cbcb28471bb30f05c9827f724c76.tar.gz";
    sha256 = "sha256-bxrdOn8SCOv8tN4JbTF/TXq7kjo9ag4M+C8yzzIRYbE=";
  }) { system = "x86_64-linux"; };
  remote = { ... }: {
    environment.systemPackages = [ pkgs.curl pkgs.openssh pkgs.procps ];
    virtualisation.memorySize = 512;
  };
in pkgs.testers.runNixOSTest {
  name = "browser-host-session";
  globalTimeout = 180;
  nodes = {
    browser = { ... }: {
      virtualisation.memorySize = 2048;
      environment.systemPackages = [ pkgs.curl pkgs.openssh ];
      users.users.browser = { isSystemUser = true; group = "browser"; };
      users.groups.browser = { };
      services.openssh.enable = true;
      # Disposable VM network only; no production credentials.
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
  testScript = builtins.readFile ./browser-host.py;
}
