# Read-only diagnostic of the pinned Chromium/ops fixture; NOT viewer acceptance.
let
  pkgs = import ./pkgs.nix;
  ops = builtins.fetchGit {
    url = "https://github.com/roccho-org/ops.git";
    rev = "9e6603324e5d7691dd06675c3267e887ce1e8915";
  };
  # Build the exact upstream C/probe with checks disabled ONLY in this isolated
  # diagnostic producer. The normal Browser Host dependency keeps doCheck=true.
  diagnosticProbe = (pkgs.callPackage (ops + "/packages/cdp-tty/default.nix") { }).overrideAttrs (_: {
    outputs = [ "out" ];
    doCheck = false;
    installPhase = ''
      runHook preInstall
      make probe
      mkdir -p "$out/package/tests"
      cp cdp-tty probe libcdp-tty.a cdp.c cdp.h tty.c tty.h main.c Makefile "$out/package/"
      cp tests/probe.c "$out/package/tests/"
      runHook postInstall
    '';
  });
in pkgs.mkShell {
  packages = [ pkgs.chromium (pkgs.python3.withPackages (p: [ p.websocket-client ])) pkgs.binutils diagnosticProbe ];
  CHROME_BIN = "${pkgs.chromium}/bin/chromium";
  OPS_PROOF = "${ops}/verification/cdp-tty/proof.py";
  CDP_TTY_PACKAGE = "${diagnosticProbe}/package";
  FONTCONFIG_FILE = pkgs.makeFontsConf {
    fontDirectories = [ pkgs.noto-fonts-cjk-sans ];
  };
}
