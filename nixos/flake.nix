{
  description = "Minimal BIOS SSD bootstrap and own OCI for VersaPro";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/2efa67fd26b6df417c33e4603185c701f260dd83";
  inputs.windows.url = "github:roccho-dev/windows/355b038bcbe2b24a8ad0121f79b7cc4c72b76b3f";

  outputs = { self, nixpkgs, windows, ... }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      mkOwn = windows.lib.${system}.mkOwn;
      defaultOwn = mkOwn { };
      extendedImageName = "ghcr.io/roccho-dev/windows-own:resources-next";
      extendedOwn = mkOwn {
        extra = [ pkgs.hello ];
        tag = "resources-next";
      };
      # Candidate Native T comes from the same fixed windows producer, but is NOT installed
      # in the NixOS system profile or owned by the OCI image lifecycle.
      nativeT0 = defaultOwn.profile;
      nativeT1 = extendedOwn.profile;
      ownModule = import ./own-oci.nix {
        defaultImage = defaultOwn.image;
        defaultImageName = "ghcr.io/roccho-dev/windows-own:nix";
      };
      versapro = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = [
          ./versapro.nix
          ownModule
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
      # SOURCE candidates only; envs acceptance and actual native selection stay separate.
      packages.${system} = {
        native-tool-candidate = nativeT0;
        native-tool-next-fixture = nativeT1;
      };

      checks.${system} = {
        versapro-own-oci-host = versapro.config.system.build.toplevel;
        own-image = defaultOwn.image;
        own-image-extended = extendedOwn.image;
        own-oci-vm = pkgs.testers.runNixOSTest (import ./tests/own-oci.nix {
          inherit pkgs ownModule extendedImageName;
          extendedImage = extendedOwn.image;
          codexVersion = windows.releaseVersions.codex;
          nativeProfile = nativeT0;
          nativeProfileNext = nativeT1;
        });
      };
    };
}
