# First executable closure step; NOT full pre-apply acceptance.
# Exact package set selected by ops #426, without unrelated private flake inputs.
let
  pkgs = import (builtins.fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/1c3fe55ad329cbcb28471bb30f05c9827f724c76.tar.gz";
    sha256 = "sha256-bxrdOn8SCOv8tN4JbTF/TXq7kjo9ag4M+C8yzzIRYbE=";
  }) { system = "x86_64-linux"; };
  bcon = pkgs.callPackage ../nixos/bcon.nix { };
  ops = builtins.fetchGit {
    url = "https://github.com/roccho-org/ops.git";
    rev = "9e6603324e5d7691dd06675c3267e887ce1e8915";
  };
  viewer = pkgs.callPackage (ops + "/packages/cdp-tty/default.nix") { };
  fixture = pkgs.writeText "browser-host-page.html" (builtins.readFile ./page.html);
  remote = { ... }: {
    environment.systemPackages = [ pkgs.curl pkgs.openssh pkgs.procps ];
    virtualisation.memorySize = 512;
  };
in pkgs.testers.runNixOSTest {
  name = "browser-host-session";
  globalTimeout = 300;
  extraPythonPackages = p: [ p.pillow ];
  nodes = {
    browser = { ... }: {
      virtualisation.memorySize = 2048;
      environment.systemPackages = [ pkgs.curl pkgs.openssh pkgs.kbd pkgs.procps bcon viewer
        (pkgs.python3.withPackages (p: [ p.websocket-client ])) ];
      hardware.graphics.enable = true;
      services.dbus.enable = true;
      fonts.packages = [ pkgs.noto-fonts pkgs.noto-fonts-cjk-sans ];
      systemd.services."getty@tty2".enable = false;
      systemd.services.bcon-test = {
        after = [ "systemd-user-sessions.service" ];
        environment = {
          HOME = "/root";
          XDG_RUNTIME_DIR = "/run/bcon-test";
          TERM = "xterm-256color";
          LIBGL_ALWAYS_SOFTWARE = "1";
          RUST_LOG = "info";
        };
        serviceConfig = {
          ExecStart = "${bcon}/bin/bcon";
          StandardInput = "tty";
          StandardOutput = "tty";
          StandardError = "journal";
          TTYPath = "/dev/tty2";
          RuntimeDirectory = "bcon-test";
          Restart = "no";
        };
      };
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
          ExecStart = "${pkgs.chromium}/bin/chromium --headless --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir=/var/lib/test-chrome/profile --window-size=800,600 file://${fixture}";
          Restart = "no";
        };
      };
    };
    remoteA = remote;
    remoteB = remote;
  };
  testScript = builtins.readFile ./browser-host.py;
}
