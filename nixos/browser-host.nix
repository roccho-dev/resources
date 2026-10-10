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
