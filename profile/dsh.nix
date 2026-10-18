# One upstream DSH. The OpenCode route is nonsecret and initialized once under the persistent own HOME.
# Never put the API key or mutable session state in the Nix store.
{ pkgs, upstream }:
let
  initialSettings = pkgs.writeText "dsh-opencode-settings.yaml" ''
    llm-pi-ai:
      providers:
        opencode:
          apiKeyEnv: OPENCODE_API_KEY
  '';
in
pkgs.writeShellApplication {
  name = "dsh";
  runtimeInputs = [ pkgs.coreutils ];
  text = ''
    set +o xtrace
    umask 077
    case "''${1:-}" in
      --version|-v|--help|-h)
        exec ${upstream}/bin/dsh "$@"
        ;;
    esac

    home="''${DSH_HOME:-$HOME/.dsh}"
    case "$home" in
      /nix/store/*) echo "dsh: runtime state cannot reside in the Nix store" >&2; exit 1 ;;
      /*) ;;
      *) echo "dsh: DSH_HOME must be absolute" >&2; exit 1 ;;
    esac
    if [ -L "$home" ] || { [ -e "$home" ] && [ ! -d "$home" ]; }; then
      echo "dsh: invalid state directory" >&2; exit 1
    fi
    install -d -m 700 -- "$home"
    if [ "$(stat -c %u -- "$home")" != "$(id -u)" ] || [ "$(stat -c %a -- "$home")" != 700 ]; then
      echo "dsh: state directory ownership or mode differs" >&2; exit 1
    fi

    settings="$home/settings.yaml"
    if [ ! -e "$settings" ] && [ ! -L "$settings" ]; then
      tmp=$(mktemp "$home/.settings.XXXXXXXX")
      cp ${initialSettings} "$tmp"
      chmod 600 "$tmp"
      # link is atomic and refuses to replace a concurrent user-authored setting
      ln "$tmp" "$settings" 2>/dev/null || true
      rm -f -- "$tmp"
    fi
    if [ -L "$settings" ] || [ ! -f "$settings" ] || \
       [ "$(stat -c %u -- "$settings")" != "$(id -u)" ] || \
       [ "$(stat -c %a -- "$settings")" != 600 ]; then
      echo "dsh: settings file ownership or mode differs" >&2; exit 1
    fi
    export DSH_HOME="$home"
    exec ${upstream}/bin/dsh "$@"
  '';
}
