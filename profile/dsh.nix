# Only the pinned Shiguredo source is built. DSH owns provider selection, auth and sessions.
# No DSH wrapper, extra credential store or model router in resources.
{ pkgs, source }:
let
  node = pkgs.nodejs_24;
  pnpm = pkgs.pnpm_11;
in
pkgs.stdenv.mkDerivation (finalAttrs: {
  pname = "dsh-shiguredo";
  version = "0.2.1-rc.2-fbe85cf3";
  src = source;
  nativeBuildInputs = [
    node
    pnpm
    pkgs.pnpmConfigHook
    pkgs.makeWrapper
    pkgs.python3
    pkgs.pkg-config
  ];
  pnpmDeps = pkgs.fetchPnpmDeps {
    inherit (finalAttrs) pname version src;
    inherit pnpm;
    fetcherVersion = 4;
    hash = "sha256-C9Aw9AS4r7zubaEuT6mLXQ+AhhMVlTxPZRKTpzRUkcU=";
  };
  buildPhase = ''
    runHook preBuild
    export HOME="$TMPDIR/dsh-build-home"
    mkdir -p "$HOME"
    pnpm run build:artifacts
    runHook postBuild
  '';
  installPhase = ''
    runHook preInstall
    pnpm --filter @deepseek-ai/dsh deploy --prod --legacy "$out/lib/dsh"
    test -s "$out/lib/dsh/lib/bin.js"
    mkdir -p "$out/bin"
    makeWrapper ${node}/bin/node "$out/bin/dsh" \\
      --add-flags --expose-internals \\
      --add-flags "$out/lib/dsh/lib/bin.js"
    runHook postInstall
  '';
  doInstallCheck = true;
  installCheckPhase = ''
    runHook preInstallCheck
    export HOME="$TMPDIR/dsh-install-check-home"
    mkdir -p "$HOME"
    "$out/bin/dsh" --version
    runHook postInstallCheck
  '';
  meta = {
    description = "Shiguredo fork of DeepSeek Harness CLI";
    homepage = "https://github.com/shiguredo/deepseek-harness";
    license = pkgs.lib.licenses.mit;
    platforms = [ "x86_64-linux" ];
    mainProgram = "dsh";
  };
})
