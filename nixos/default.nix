{ self, nixpkgs, producer, bcon, meltype-src, meltype-linux }:
let
  system = "x86_64-linux";
  pkgs = import nixpkgs { inherit system; };
  mkOwn = producer.lib.${system}.mkOwn;
  # Names only: declaring this target does not supply a credential or call a provider.
  piTarget = {
    bindingId = "opencode-go.versapro-own-oci";
    target = { repository = "roccho-dev/resources"; host = "versapro-own-oci"; kind = "pi_auth_command"; };
    identity = "/work/repos/.auth/roccho-dev/age/versapro-own-oci.key";
    agentDir = "/home/dev/.pi/agent-versapro-own-oci";
  };
  defaultOwn = mkOwn { inherit piTarget; };
  extendedOwn = mkOwn { inherit piTarget; extra = [ pkgs.hello ]; };
  ownModule = import ./own-oci.nix {
    defaultImage = defaultOwn.image;
    defaultImageName = "ghcr.io/roccho-dev/windows-own:nix";
    defaultProfile = defaultOwn.profile;
  };
  meltypeConsole = import ./meltype-console.nix { inherit bcon meltype-src meltype-linux; };
  versapro = nixpkgs.lib.nixosSystem {
    inherit system;
    # Native own's B carries the own Core, the same one the own OCI's B carries (#72).
    specialArgs.ownCore = defaultOwn.core;
    modules = [
      ./versapro.nix
      meltypeConsole
      {
        system.configurationRevision = self.rev or null;
      }
    ];
  };
in {
  nixosConfigurations.versapro = versapro;
  checks.${system} = {
    versapro-native-host = versapro.config.system.build.toplevel;
    # The actual target configuration must stay native-only. The separate OCI VM below is regression evidence only.
    versapro-native-boundary =
      assert !versapro.config.virtualisation.docker.enable;
      assert versapro.config.virtualisation.oci-containers.containers == {};
      assert !(builtins.hasAttr "docker-versapro-own-oci" versapro.config.systemd.services);
      assert !(builtins.hasAttr "versapro-own-oci-profile" versapro.config.systemd.services);
      assert versapro.config.users.users.dev.isNormalUser;
      assert builtins.elem "/nix/var/nix/profiles/own-dev" versapro.config.environment.profiles;
      pkgs.runCommand "versapro-native-boundary" {} "touch $out";
    own-image = defaultOwn.image;
    own-profile = defaultOwn.profile;
    own-profile-extended = extendedOwn.profile;
    own-native-profile-vm = pkgs.testers.runNixOSTest (import ./tests/native-profile.nix { inherit pkgs; });
    # Historical isolated OCI regression: this must never count as a native target proof.
    own-oci-vm = pkgs.testers.runNixOSTest (import ./tests/own-oci.nix {
      inherit pkgs ownModule;
      extendedProfile = extendedOwn.profile;
      codexVersion = producer.releaseVersions.codex;
      piAgentDir = piTarget.agentDir;
      piBindingId = piTarget.bindingId;
    });
    # Preserve the concurrently merged real keyboard/evdev/bcon/Meltype VM proof.
    meltype-console-vm = pkgs.testers.runNixOSTest (import ./tests/meltype-console.nix {
      inherit pkgs meltypeConsole;
    });
  };
}
