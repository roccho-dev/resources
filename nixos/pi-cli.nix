# One existing Pi implementation. Credentials and sessions are runtime state, never Nix inputs.
{ config, lib, pkgs, ... }:
let
  cfg = config.programs.piCli;
  source = builtins.fetchGit {
    url = "https://github.com/roccho-dev/windows.git";
    rev = "3d6f8bcb02305d20fe671568db4c9184c4caa81f";
    allRefs = true;
  };
  pi = import (source + "/oci/dev/pi.nix") {
    inherit pkgs;
    inherit (cfg) bindingId;
    identity = cfg.identityFile;
    agentDir = "${cfg.home}/.pi/agent";
    target = {
      repository = "roccho-dev/resources";
      host = config.networking.hostName;
      kind = "pi_auth_command";
    };
  };
in {
  options.programs.piCli = {
    enable = lib.mkEnableOption "the existing Pi CLI with target-bound Go authentication";
    user = lib.mkOption { type = lib.types.strMatching "[a-z_][a-z0-9_-]*"; default = "pah"; };
    home = lib.mkOption {
      type = lib.types.strMatching "/[a-zA-Z0-9_./-]+";
      default = "/home/${cfg.user}";
    };
    identityFile = lib.mkOption {
      type = lib.types.str;
      default = "${cfg.home}/.config/age/key.txt";
      description = "Runtime path only; provision an owner-only age identity outside Git/store.";
    };
    bindingId = lib.mkOption {
      type = lib.types.str;
      default = "opencode-go.${config.networking.hostName}";
    };
    authorizedKeys = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = config.users.users.root.openssh.authorizedKeys.keys;
      description = "Public manager keys; reuse the existing declaration, not private keys.";
    };
  };
  config = lib.mkIf cfg.enable {
    assertions = [
      { assertion = cfg.user != "root" && cfg.home != "/root";
        message = "Pi CLI must use a separate non-root account."; }
      { assertion = lib.hasPrefix "/" cfg.identityFile
          && !(lib.hasPrefix "/nix/store" cfg.identityFile)
          && !(lib.hasPrefix "/nix/store" cfg.home);
        message = "Pi state and the runtime identity path must stay outside the Nix store."; }
    ];
    users.groups.${cfg.user} = {};
    users.users.${cfg.user} = {
      isNormalUser = true;
      group = cfg.user;
      home = cfg.home;
      homeMode = "0700";
      createHome = true;
      packages = [ pi.launcher ];
      openssh.authorizedKeys.keys = cfg.authorizedKeys;
    };
    systemd.tmpfiles.rules = [
      "d ${cfg.home}/.pi 0700 ${cfg.user} ${cfg.user} -"
      "d ${cfg.home}/.pi/agent 0700 ${cfg.user} ${cfg.user} -"
      "d ${cfg.home}/.config 0700 ${cfg.user} ${cfg.user} -"
      "d ${cfg.home}/.config/age 0700 ${cfg.user} ${cfg.user} -"
    ];
  };
}
