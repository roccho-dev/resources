{
  description = "Minimal BIOS SSD bootstrap and own OCI for VersaPro";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/2efa67fd26b6df417c33e4603185c701f260dd83";
  inputs.windows.url = "github:roccho-dev/windows/d8e980b3dcf502dd2cda3e1d81b92147aad8e0f9";

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
            # Materialize the same accepted root partition already named by
            # versapro.nix's kernel root argument so the full NixOS closure is buildable.
            fileSystems."/" = {
              device = "/dev/disk/by-uuid/31515680-c79f-4b95-aef1-15b8634be20c";
              fsType = "ext4";
            };
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
        own-image-extended = extendedOwn.image;
        own-oci-vm = pkgs.testers.runNixOSTest (import ./tests/own-oci.nix {
          inherit pkgs ownModule extendedImageName;
          extendedImage = extendedOwn.image;
          codexVersion = windows.releaseVersions.codex;
        });
      };
    };
}
