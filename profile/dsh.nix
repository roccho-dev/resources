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
  DSH_CLIENT_COMMIT_HASH = source.rev;
  # Native Node24 loader compatibility, unchanged from Nixpkgs 2c2a3163666052c31fd5dc505d61f5631bd2f809.
  patches = [ ./dsh-expose-internals-profile-resolution.patch ];
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
    # Bound each registry request while limiting parallel transfers on the target host.
    pnpmInstallFlags = [
      "--fetch-timeout=300000"
      "--network-concurrency=8"
    ];
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
    # Preserve the frozen dependency graph instead of resolving legacy deploy dependencies again.
    mkdir -p "$out/lib/dsh" "$out/bin"
    cp -r . "$out/lib/dsh/"
    find "$out/lib/dsh/node_modules/.pnpm" -type l ! -exec test -e {} \; -delete

    # Cordis resolves scoped packages from the installation root.
    shopt -s nullglob
    store_scopes=("$out/lib/dsh/node_modules/.pnpm/node_modules/"@*/)
    for scope in "''${store_scopes[@]}"; do
      scope_name=$(basename "$scope")
      mkdir -p "$out/lib/dsh/node_modules/$scope_name"
      for pkg in "$scope"*; do
        ln -sfn "../.pnpm/node_modules/$scope_name/$(basename "$pkg")" \
          "$out/lib/dsh/node_modules/$scope_name/$(basename "$pkg")"
      done
    done

    test -s "$out/lib/dsh/apps/cli/lib/bin.js"
    makeWrapper ${node}/bin/node "$out/bin/dsh" \
      --prefix PATH : ${pkgs.lib.makeBinPath [ pnpm ]} \
      --add-flags --expose-internals \
      --add-flags "$out/lib/dsh/apps/cli/lib/bin.js"
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
