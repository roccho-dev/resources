# Dedicated C test entry. Missing exports fail BEFORE any network/build/VM work.
{ packagePath ? null, evidenceRun ? null, supplied ? import ./suppliers.nix { inherit packagePath; } }:
let
  inputs = (import ./contract.nix).require supplied;
  # Reuse only the existing package-set lock; do not evaluate own-OCI/windows.
  lock = builtins.fromJSON (builtins.readFile ../../flake.lock);
  # The base moved the existing host lock to the root. Keep its host package
  # set, not the distinct profile/tooling nixpkgs input.
  selected = lock.nodes.${lock.root}.inputs.host-nixpkgs;
  pin = assert builtins.isString selected; lock.nodes.${selected}.locked;
  pkgs = import (builtins.fetchTarball {
    url = "https://github.com/${pin.owner}/${pin.repo}/archive/${pin.rev}.tar.gz";
    sha256 = pin.narHash;
  }) { system = "x86_64-linux"; };
in builtins.seq inputs (
  assert builtins.isString evidenceRun
    && builtins.match "https://github.com/roccho-dev/resources/actions/runs/[0-9]+" evidenceRun != null;
  import ./test.nix { inherit pkgs inputs evidenceRun; })
