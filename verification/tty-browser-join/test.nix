# C input/fault collection. No A/B build recipes, live configuration or admission.
# Assembly follows Meltype#2@d673872 linux/tty/tests/bcon.nix; products are arguments.
{ pkgs, inputs }:
let
  viewer = inputs.A.package;
  input = inputs.B.package;
  terminal = inputs.terminal.package;
  python = pkgs.python3.withPackages (p: [ p.websocket-client p.pillow ]);
  page = pkgs.writeText "c-input.html" ''
    <!doctype html><meta charset="utf-8"><title>C input test</title>
    <style>body{background:rgb(215,225,240)}textarea{font:28px sans-serif;width:600px;height:120px}</style>
    <textarea id="editor" autofocus></textarea>
  '';
  support = pkgs.linkFarm "c-evidence-support" [
    { name = "evidence.py"; path = ./evidence.py; }
    { name = "coverage.json"; path = ./coverage.json; }
  ];
  code = pkgs.writeText "c-code.json" (builtins.toJSON {
    code = builtins.hashString "sha256" (builtins.concatStringsSep "\n"
      (map builtins.readFile [ ./default.nix ./contract.nix ./suppliers.nix ./pins.json
        ./test.nix ./test.py ./observer.py ./fixture.py ./evidence.py ./coverage.json
        ./test-contract.nix ./test_unit.py ]));
    nixpkgs = toString pkgs.path;
    chrome = toString pkgs.chromium;
    system = "x86_64-linux";
  });
  sourcePins = pkgs.writeText "c-source-pins.json" (builtins.toJSON
    (builtins.mapAttrs (_: value: {
      inherit (value) rev narHash;
      outputPath = toString value.package;
      drvPath = value.package.drvPath;
    }) inputs));
in pkgs.testers.runNixOSTest {
  name = "tty-browser-join-smoke";
  # The additional bounded scenarios extend coverage, not a prior timeout workaround.
  globalTimeout = 420;
  extraPythonPackages = p: [ p.pillow ];
  nodes.machine = { ... }: {
    virtualisation.memorySize = 3072;
    virtualisation.cores = 2;
    hardware.graphics.enable = true;
    services.dbus.enable = true;
    fonts.packages = [ pkgs.noto-fonts-cjk-sans ];
    environment.systemPackages = [ viewer input terminal python pkgs.kbd pkgs.procps pkgs.iproute2 ];
    environment.etc."bcon/config.toml".text = "[terminal]\nime = false\n";
    environment.etc."c-source-pins.json".source = sourcePins;
    environment.etc."c-code.json".source = code;
    environment.etc."c-observer.py".source = ./observer.py;
    environment.etc."c-fixture.py".source = ./fixture.py;
    systemd.services.c-provider = {
      # Starts only in this isolated test after the ordinary-input scenario.
      serviceConfig = {
        RuntimeDirectory = "c-provider";
        ExecStart = "${python}/bin/python3 /etc/c-fixture.py --state-dir /run/c-provider --port 8031";
        Restart = "no";
      };
    };
    services.logind.settings.Login = { NAutoVTs = 1; ReserveVT = 1; };
    systemd.services."getty@tty2".enable = false;
    users.groups.c-browser = {};
    users.users.c-browser = { isSystemUser = true; group = "c-browser"; };
    systemd.services.c-browser = {
      wantedBy = [ "multi-user.target" ];
      environment.HOME = "/run/c-browser";
      serviceConfig = {
        User = "c-browser";
        RuntimeDirectory = "c-browser";
        ExecStart = "${pkgs.chromium}/bin/chromium --headless --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir=/run/c-browser/profile --window-size=800,600 file://${page}";
        Restart = "no";
      };
    };
    systemd.services.c-console = {
      wantedBy = [ "multi-user.target" ];
      after = [ "systemd-user-sessions.service" ];
      path = [ pkgs.coreutils ];
      environment = {
        HOME = "/root";
        XDG_RUNTIME_DIR = "/run/c-console";
        TERM = "xterm-256color";
        LIBGL_ALWAYS_SOFTWARE = "1";
        RUST_LOG = "info";
      };
      serviceConfig = {
        ExecStartPre = pkgs.writeShellScript "c-ready" ''
          set -eu
          test -x ${viewer}/bin/cdp-tty
          test -x ${input}/bin/meltype-tty
          test -x ${terminal}/bin/bcon
          for i in $(seq 1 100); do
            for card in /dev/dri/card*; do
              if test -c "$card"; then exec ${pkgs.kbd}/bin/chvt 2; fi
            done
            sleep .1
          done
          exit 1
        '';
        ExecStart = "${terminal}/bin/bcon";
        StandardInput = "tty";
        StandardOutput = "tty";
        StandardError = "journal";
        TTYPath = "/dev/tty2";
        RuntimeDirectory = "c-console";
        TimeoutStopSec = "5s";
      };
    };
  };
  testScript = ''
    import sys
    sys.path.insert(0, "${support}")
  '' + builtins.readFile ./test.py;
}
