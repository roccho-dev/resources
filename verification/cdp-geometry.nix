# Read-only diagnostic of the pinned Chromium/ops fixture; NOT viewer acceptance.
let
  pkgs = import ./pkgs.nix;
  ops = builtins.fetchGit {
    url = "https://github.com/roccho-org/ops.git";
    rev = "9e6603324e5d7691dd06675c3267e887ce1e8915";
  };
in pkgs.mkShell {
  packages = [ pkgs.chromium (pkgs.python3.withPackages (p: [ p.websocket-client ])) ];
  CHROME_BIN = "${pkgs.chromium}/bin/chromium";
  OPS_PROOF = "${ops}/verification/cdp-tty/proof.py";
  FONTCONFIG_FILE = pkgs.makeFontsConf {
    fontDirectories = [ pkgs.noto-fonts-cjk-sans ];
  };
}
