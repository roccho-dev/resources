{
  description = "Minimal BIOS SSD bootstrap for VersaPro";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/2efa67fd26b6df417c33e4603185c701f260dd83";

  outputs = { self, nixpkgs, ... }:
    let
      system = "x86_64-linux";
      baseModules = [
        ./versapro.nix
        ./pi-cli.nix
        { system.configurationRevision = self.rev or null; }
      ];
      base = nixpkgs.lib.nixosSystem { inherit system; modules = baseModules; };
      candidate = nixpkgs.lib.nixosSystem {
        inherit system;
        modules = baseModules ++ [ { programs.piCli.enable = true; } ];
      };
      pkgs = import nixpkgs { inherit system; };
      user = candidate.config.users.users.pah;
      pi = builtins.head user.packages;
    in {
      nixosModules.pi-cli = import ./pi-cli.nix;
      # Not enabled on the actual host until CLI/live and target acceptance agree.
      nixosConfigurations.versapro = base;
      checks.${system}.pi-cli =
        assert base.config.programs.piCli.enable == false;
        assert user.isNormalUser && user.group == "pah" && user.homeMode == "0700";
        assert candidate.config.programs.piCli.bindingId == "opencode-go.versapro";
        assert candidate.config.programs.piCli.identityFile == "/home/pah/.config/age/key.txt";
        pkgs.runCommand "pi-cli-source-check" {} ''
          export HOME="$TMPDIR"
          ${pi}/bin/pi --version > version
          grep -Fx '1.0.4' version
          mkdir -p "$out"
          cp version "$out/version"
        '';
    };
}
