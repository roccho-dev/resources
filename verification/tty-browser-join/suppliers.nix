# C consumes existing producer definitions, never copies their build recipes.
# A package input is accepted only by its entire fixed NAR hash. The temporary
# download location is not an identity or authority; pins.json is the only pin set.
# No archive means no source fetch, package evaluation or VM launch.
{ packagePath ? null }:
if packagePath == null then { A = null; B = null; terminal = null; }
else let
  pins = builtins.fromJSON (builtins.readFile ./pins.json);
  verifiedPackage = builtins.path {
    path = builtins.toPath packagePath;
    name = "same-build-meltype";
    sha256 = pins.B.artifact.packageNarHash;
  };
  source = name:
    let pin = pins.${name};
    in builtins.fetchTree ({ type = "github"; inherit (pin) owner repo rev; }
      // (if pin ? narHash then { inherit (pin) narHash; } else {}));
  a = source "A";
  b = source "B";
  terminalSource = source "terminal";
  # Reuse B's tested package set and the existing terminal producer.
  pkgs = import (terminalSource.outPath + "/verification/pkgs.nix");
  supplied = name: src: package: {
    rev = pins.${name}.rev;
    inherit (src) narHash;
    inherit package;
  };
in builtins.seq verifiedPackage {
  A = supplied "A" a (import (a.outPath + "/packages/cdp-tty/proof.nix")).out;
  B = supplied "B" b (import (b.outPath + "/linux/tty/package.nix") {
    inherit pkgs; packagePath = verifiedPackage;
  });
  terminal = supplied "terminal" terminalSource
    (pkgs.callPackage (terminalSource.outPath + "/nixos/bcon.nix") {});
}
