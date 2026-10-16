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
    modules = [
      ./versapro.nix
      ownModule
      meltypeConsole
      {
        services.versaproOwnOci.enable = true;
        system.configurationRevision = self.rev or null;
      }
    ];
  };
in {
  nixosModules."versapro-own-oci" = ownModule;
  nixosConfigurations.versapro = versapro;
  checks.${system} = {
    versapro-own-oci-host = versapro.config.system.build.toplevel;
    own-image = defaultOwn.image;
    own-profile = defaultOwn.profile;
    own-profile-extended = extendedOwn.profile;
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
