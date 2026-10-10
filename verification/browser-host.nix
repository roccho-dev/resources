# First executable closure step; NOT full pre-apply acceptance.
# Exact package set selected by ops #426, without unrelated private flake inputs.
let
  pkgs = import (builtins.fetchTarball {
    url = "https://github.com/NixOS/nixpkgs/archive/1c3fe55ad329cbcb28471bb30f05c9827f724c76.tar.gz";
    sha256 = "sha256-bxrdOn8SCOv8tN4JbTF/TXq7kjo9ag4M+C8yzzIRYbE=";
  }) { system = "x86_64-linux"; };
  bcon = pkgs.callPackage ../nixos/bcon.nix { };
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
      imports = [ ../nixos/browser-host.nix ];
      services.browserHost = { enable = true; initialUrl = "file://${fixture}"; };
      virtualisation.memorySize = 2048;
      environment.systemPackages = [ pkgs.curl pkgs.openssh pkgs.kbd pkgs.procps
        (pkgs.python3.withPackages (p: [ p.websocket-client ])) ];
      hardware.graphics.enable = true;
      services.dbus.enable = true;
      fonts.packages = [ pkgs.noto-fonts pkgs.noto-fonts-cjk-sans ];
      # logind autospawns getty on VT switch even if the per-instance unit is disabled.
      # Keep tty1 as the rescue console; dedicate tty2 to the bcon session.
      services.logind.settings.Login = { NAutoVTs = 1; ReserveVT = 1; };
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
          TimeoutStopSec = "5s";
          Restart = "no";
        };
      };
      services.openssh.enable = true;
      # Disposable VM network only; no production credentials.
      services.openssh.settings.PermitRootLogin = "prohibit-password";
    };
    remoteA = remote;
    remoteB = remote;
  };
  testScript = builtins.readFile ./browser-host.py;
}
