# Transitional M check of roccho-dev/resources#25 PoC a: this selection, evaluated with the nixpkgs that the
# locked windows input pins, must equal windows' common-fonts byte for byte. A NixOS system check, so the
# existing `nix flake check ./nixos` builds it with the host. Remove it with the windows input (D9).
{ windows }:
{ pkgs, ... }:
let
  system = pkgs.stdenv.hostPlatform.system;
  moved = (import ./fonts.nix { pkgs = windows.inputs.nixpkgs.legacyPackages.${system}; }).commonFonts;
  original = windows.packages.${system}.common-fonts;
in
{
  system.checks = [
    (pkgs.runCommand "common-fonts-parity" { } ''
      diff -r --no-dereference ${original} ${moved}
      touch "$out"
    '')
  ];
}
