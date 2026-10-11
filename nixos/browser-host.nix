# Host owns one persistent browser/profile. The VM fixture imports this same module.
# CDP is loopback-only, but SSH tunnel access is NOT writer isolation (E05 still fails).
{ config, lib, pkgs, ... }:
let
  cfg = config.services.browserHost;
  bcon = pkgs.callPackage ./bcon.nix { };
  ops = builtins.fetchGit {
    url = "https://github.com/roccho-org/ops.git";
    rev = "9e6603324e5d7691dd06675c3267e887ce1e8915";
  };
  viewer = pkgs.callPackage (ops + "/packages/cdp-tty/default.nix") { };
in {
  options.services.browserHost = {
    enable = lib.mkEnableOption "one host-owned Chromium/profile with bcon and existing cdp-tty";
    initialUrl = lib.mkOption {
      type = lib.types.str;
      default = "about:blank";
      description = "First page created by the Host; viewers must attach to an explicit target.";
    };
  };
  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ bcon viewer ];
    users.groups.browser = { };
    users.users.browser = { isSystemUser = true; group = "browser"; };
    # Keep tty1 for recovery; logind must not autospawn agetty on the bcon VT.
    services.logind.settings.Login = { NAutoVTs = 1; ReserveVT = 1; };
    systemd.services."getty@tty2".enable = false;
    systemd.services.browser-host-terminal = {
      wantedBy = [ "multi-user.target" ];
      after = [ "systemd-user-sessions.service" ];
      environment = {
        HOME = "/root";
        XDG_RUNTIME_DIR = "/run/browser-host-terminal";
        TERM = "xterm-256color";
        RUST_LOG = "info";
      };
      serviceConfig = {
        # Upstream bcon waits for tty2 to become active but does not activate it.
        # Activate here before the 10s VT_WAITACTIVE deadline; keep tty1 for recovery.
        ExecStartPre = "${pkgs.kbd}/bin/chvt 2";
        ExecStart = "${bcon}/bin/bcon";
        StandardInput = "tty";
        StandardOutput = "tty";
        StandardError = "journal";
        TTYPath = "/dev/tty2";
        RuntimeDirectory = "browser-host-terminal";
        TimeoutStopSec = "5s";
        Restart = "no";
      };
    };
    systemd.services.browser-host = {
      wantedBy = [ "multi-user.target" ];
      environment.HOME = "/var/lib/browser-host";
      serviceConfig = {
        User = "browser";
        StateDirectory = "browser-host";
        ExecStart = "${pkgs.chromium}/bin/chromium --headless --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir=/var/lib/browser-host/profile --window-size=800,600 ${lib.escapeShellArg cfg.initialUrl}";
        Restart = "no";
      };
    };
  };
}
