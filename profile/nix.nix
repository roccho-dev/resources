# One Linux development profile for own and rent. Agent packages retain their existing fixed sources;
# nothing is installed into a host by hand. `extra` supplies role tools and the CI upgrade proof.
# own and rent keep their Tool generation separate from the OCI Base; this file does not add a service or Windows installer.
# `owner` only names the stable Git credential helper. Each repository's principal is declared by its own
# binding (profile/gh.nix), never derived from owner or the URL namespace.
# `piTarget` (own only) names one exact envs target for the existing Pi credential launcher; null keeps the plain entry.
{ pkgs, extra ? [], owner ? "roccho-dev", mode ? "legacy", piTarget ? null }:
let
  # Core(L_B, owner) never evaluates an app pin. The default retains rent/dev's existing profile.
  github = import ./gh.nix { inherit pkgs owner; };
  corePaths = with pkgs; [ bash coreutils diffutils findutils gnugrep gnused gnutar gzip nix git openssh ];
  releaseDefinitions = builtins.fromJSON (builtins.readFile ./releases.json);
  releaseVersions = builtins.mapAttrs (_: definition: definition.pin.version) releaseDefinitions;
  codex = import ../oci/own/codex.nix { inherit pkgs; definition = releaseDefinitions.codex; };
  claudeDefinition = releaseDefinitions.claude;
  claudeContract = claudeDefinition.contract;
  claudePin = claudeDefinition.pin;
  claudeBin = pkgs.fetchurl {
    url = "${claudeContract.officialSource}/${claudePin.version}/${claudeContract.platform}/${claudeContract.assetSelector}";
    sha256 = claudePin.contentHash;
  };
  # The glibc build runs through the pinned glibc loader, as the fixed W runtime runs it; updates are off.
  claude = pkgs.writeShellScriptBin "claude" ''
    export DISABLE_AUTOUPDATER=1
    exec ${pkgs.glibc}/lib/ld-linux-x86-64.so.2 --library-path ${pkgs.glibc}/lib ${claudeBin} "$@"
  '';
  releaseVersionCases = pkgs.lib.concatMapStrings (name: ''
    ${name}) printf '%s\n' '${releaseVersions.${name}}' ;;
  '') (builtins.attrNames releaseVersions);
  releaseVersion = pkgs.writeShellScriptBin "release-version" ''
    set -eu
    case "''${1:-}" in
${releaseVersionCases}      *) echo "release-version: unknown CLI ''${1:-}" >&2; exit 2 ;;
    esac
  '';
  opencode = import ./opencode.nix { inherit pkgs; };
  # Only the immutable upstream is consumed; plain own never evaluates the dev credential resolver/launcher.
  pi = import ../oci/dev/pi.nix { inherit pkgs; };
  ownPiEntry = pkgs.runCommand "own-pi-entry-${pi.version}" {
    nativeBuildInputs = [ pkgs.makeWrapper ];
  } ''
    mkdir -p "$out/bin"
    makeWrapper ${pi.upstream}/bin/pi-upstream "$out/bin/pi" \
      --set PI_PACKAGE_DIR ${pi.upstream}/share/pi
  '';
  # A target-bound own uses the same Pi source and resolver with its own binding, identity and agent directory.
  ownPi = if piTarget == null then ownPiEntry
    else (import ../oci/dev/pi.nix ({ inherit pkgs; } // piTarget)).launcher;
  # One declaration drives both Linux profile composition and its startup checks.
  # Pi keeps its existing own-only entry here; dev composes its existing launcher separately.
  cli = { inherit codex claude opencode; }
    // pkgs.lib.optionalAttrs (mode == "own") { pi = ownPi; };
  # The same bounded jev-age-init (absent-only, safe parent, public recipient only) over this target's identity, so the
  # target creates its own key in place; only its init is used (remotes are the dev values, never reached by init).
  ownAgeInit = ((import ../oci/dev/nix.nix { inherit pkgs; }).jevTools {
    envsRemote = "https://github.com/roccho-dev/envs";
    appsRemote = "https://github.com/roccho-dev/apps";
    opsRemote = "https://github.com/roccho-dev/ops";
    inherit (piTarget) identity;
  }).init;
in
assert piTarget == null || mode == "own";
assert piTarget == null || piTarget ? identity;
assert builtins.elem mode [ "legacy" "core" "rent-core" "own" "rent" ];
if builtins.elem mode [ "core" "rent-core" ] then pkgs.buildEnv {
  name = if mode == "rent-core" then "rent-core" else "own-core";
  paths = corePaths ++ [ github.wrapper github.helper ];
  pathsToLink = [ "/bin" ];
  passthru = { inherit github; credentialOwner = owner; };
} else
assert builtins.attrNames releaseDefinitions == [ "claude" "codex" ];
assert builtins.isAttrs releaseDefinitions.codex.contract;
assert builtins.isAttrs releaseDefinitions.codex.contract.proof;
assert builtins.isAttrs releaseDefinitions.codex.pin;
assert builtins.isAttrs releaseDefinitions.claude.contract;
assert builtins.isAttrs releaseDefinitions.claude.pin;
assert claudeContract.sourceKind == "claude-manifest";
assert claudeContract.channel == "stable";
assert claudeContract.versionScheme == "semver";
assert claudeContract.verifyKind == "gpg-signed-manifest";
assert claudeContract.proof.kind == "gpg-signed-manifest";
assert claudeContract.proof.keyFingerprint == "31DDDE24DDFAB679F42D7BD2BAA929FF1A7ECACE";
assert claudeContract.packageShape == "single-glibc-executable";
pkgs.buildEnv {
  name = if mode == "own" then "own-tool-profile" else if mode == "rent" then "rent-tool-profile" else "dev-profile";
  # Every supported own generation anchors the identical H_B at the existing absolute helper locator.
  # own has one T on every target; it carries zmx (#75), the persistent PTY.
  paths = (if mode == "own" then [ github.helper pkgs.zmx ] ++ pkgs.lib.optional (piTarget != null) ownAgeInit
      else if mode == "rent" then [ github.helper ]
      else corePaths ++ [ github.wrapper github.helper ])
    ++ builtins.attrValues cli ++ [ releaseVersion ] ++ extra;
  pathsToLink = [ "/bin" ];
  # Check the actual composed entries in the sandbox, not a second installation or a model call.
  postBuild = ''
    set -eu
    export HOME="$TMPDIR/cli-home"
    mkdir -p "$HOME"
    for name in ${pkgs.lib.escapeShellArgs (builtins.attrNames cli)}; do
      printf 'cli-check: %s\n' "$name"
      ${pkgs.coreutils}/bin/timeout 30 "$out/bin/$name" --version
    done
  '';
  passthru = { inherit cli releaseDefinitions releaseVersions github ownPiEntry ownPi; piUpstream = pi.upstream; }
    // pkgs.lib.optionalAttrs (piTarget != null) { inherit ownAgeInit; };
}
