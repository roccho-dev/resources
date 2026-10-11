{
  description = "Minimal BIOS SSD bootstrap for VersaPro";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/2efa67fd26b6df417c33e4603185c701f260dd83";

  outputs = { self, nixpkgs, ... }: {
    nixosConfigurations.versapro = nixpkgs.lib.nixosSystem {
      system = "x86_64-linux";
      modules = [
        ./versapro.nix
        { system.configurationRevision = self.rev or null; }
      ];
    };
  };
}
