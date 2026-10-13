# Dedicated C test entry. Missing exports fail BEFORE any network/build/VM work.
{ packagePath ? null, supplied ? import ./suppliers.nix { inherit packagePath; } }:
let
  inputs = (import ./contract.nix).require supplied;
  # Reuse only the existing package-set lock; do not evaluate own-OCI/windows.
  lock = builtins.fromJSON (builtins.readFile ../../nixos/flake.lock);
  selected = lock.nodes.${lock.root}.inputs.nixpkgs;
  pin = assert builtins.isString selected; lock.nodes.${selected}.locked;
  pkgs = import (builtins.fetchTarball {
    url = "https://github.com/${pin.owner}/${pin.repo}/archive/${pin.rev}.tar.gz";
    sha256 = pin.narHash;
  }) { system = "x86_64-linux"; };
in builtins.seq inputs (import ./test.nix { inherit pkgs inputs; })
