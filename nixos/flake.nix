{
  description = "Minimal BIOS SSD bootstrap and own OCI for VersaPro";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/2efa67fd26b6df417c33e4603185c701f260dd83";
  inputs.windows.url = "github:roccho-dev/windows/1ac80060979feec04ad9a2eeff0b91b766cec20f";
  # Physical-console Japanese input (meltype-console.nix): bcon, and fork Meltype's Direct TTY from one release.
  inputs.bcon = { url = "github:sanohiro/bcon/v1.5.1"; flake = false; };
  inputs.meltype-src = { url = "github:roccho-dev/Meltype/v1.2.1.5"; flake = false; };
  inputs.meltype-linux = { url = "file+https://github.com/roccho-dev/Meltype/releases/download/v1.2.1.5/Meltype-1.2.1.5-linux.zip"; flake = false; };

  outputs = { self, nixpkgs, windows, bcon, meltype-src, meltype-linux, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      mkOwn = windows.lib.${system}.mkOwn;
      # This OCI's fixed Pi target (names only): no key, ciphertext or Go use follows from declaring it.
      piTarget = {
        bindingId = "opencode-go.versapro-own-oci";
        target = { repository = "roccho-dev/resources"; host = "versapro-own-oci"; kind = "pi_auth_command"; };
        identity = "/work/repos/.auth/roccho-dev/age/versapro-own-oci.key";
        agentDir = "/home/dev/.pi/agent-versapro-own-oci";
      };
      # B (image) carries no apps; T (profile) is Codex, Claude, the target-bound Pi and the fixed helper.
      defaultOwn = mkOwn { inherit piTarget; };
      extendedOwn = mkOwn {
        inherit piTarget;
        extra = [ pkgs.hello ];
      };
      ownModule = import ./own-oci.nix {
        defaultImage = defaultOwn.image;
        defaultImageName = "ghcr.io/roccho-dev/windows-own:nix";
        defaultProfile = defaultOwn.profile;
      };
      versapro = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [
          ./versapro.nix
          ownModule
          (import ./meltype-console.nix { inherit bcon meltype-src meltype-linux windows; })
          {
            services.versaproOwnOci.enable = true;
            system.configurationRevision = self.rev or null;
          }
        ];
      };
    in
    {
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
          codexVersion = windows.releaseVersions.codex;
          piAgentDir = piTarget.agentDir;
          piBindingId = piTarget.bindingId;
        });
      };
    };
}
