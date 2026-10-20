# Root-only selector for an already running B-only rent OCI. The caller obtains
# this command from an exact resources commit and independently checks the Tool
# descriptor against that commit before invoking it. It never reads /work/repos.
{ pkgs }:
pkgs.writeShellScriptBin "rent-tool-apply" ''
  set -euo pipefail
  export PATH=${pkgs.lib.makeBinPath [ pkgs.coreutils pkgs.nix pkgs.util-linux pkgs.jq pkgs.procps ]}
  fail() { echo "rent-tool-apply: $*" >&2; exit 2; }
  [ "$#" -eq 4 ] || fail 'usage: BEFORE_STORE DESIRED_STORE DESIRED_NAR CODEX_VERSION'
  before_store=$1 desired=$2 wanted_nar=$3 version=$4
  [[ $before_store =~ ^/nix/store/[0-9a-z]{32}-[^/[:space:]]+$ ]] || fail 'invalid previous store path'
  [[ $desired =~ ^/nix/store/[0-9a-z]{32}-rent-tool-profile$ ]] || fail 'invalid desired Tool path'
  [[ $wanted_nar =~ ^sha256-[A-Za-z0-9+/]{43}=$ ]] || fail 'invalid SRI NAR hash'
  [[ $version =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || fail 'invalid Codex version'
  [ "$(id -u)" = 0 ] || fail 'root is required'
  [ "$(cat /nix/var/rent-nix 2>/dev/null || true)" = 'windows-rent-nix v1' ] || fail 'foreign /nix volume'
  [ "$(readlink /bin/codex)" = /nix/var/nix/profiles/rent-dev/bin/codex ] || fail 'B-only Codex entry is absent'

  admin=/nix/var/rent-tool-admin
  [ ! -L "$admin" ] || fail 'admin directory is a symlink'
  install -d -m 700 -o 0 -g 0 "$admin"
  [ "$(stat -c '%u:%g %a' "$admin")" = '0:0 700' ] || fail 'admin directory ownership or mode changed'
  lock=$admin/apply.lock
  [ ! -L "$lock" ] || fail 'apply lock is a symlink'
  : >> "$lock"
  chmod 600 "$lock"
  exec 9>"$lock"
  flock -x -n 9 || fail 'another Tool apply is active'
  export HOME=$admin XDG_CACHE_HOME=$admin/cache

  dir=/nix/var/nix/profiles
  profile=$dir/rent-dev
  [ -d "$dir" ] && [ ! -L "$dir" ] && [ "$(stat -c %u "$dir")" = 0 ] || fail 'profile directory is foreign'
  [ -L "$profile" ] && [ "$(stat -c %u "$profile")" = 0 ] || fail 'selection is absent or foreign'
  before_generation=$(readlink "$profile")
  [[ $before_generation =~ ^rent-dev-[1-9][0-9]*-link$ ]] || fail 'invalid selected generation'
  [ -L "$dir/$before_generation" ] && [ "$(stat -c %u "$dir/$before_generation")" = 0 ] || fail 'generation is foreign'
  [ "$(readlink "$dir/$before_generation")" = "$before_store" ] || fail 'selected Tool changed before apply'
  [ -d "$desired" ] || fail 'desired Tool is not installed'
  actual_nar=$(nix path-info --json --json-format 1 "$desired" | jq -er 'if type == "array" then .[0].narHash else .[].narHash end') || fail 'desired NAR unreadable'
  [ "$actual_nar" = "$wanted_nar" ] || fail 'desired NAR differs'
  closure_text=$(nix-store --query --requisites "$desired") || fail 'desired requisites are unreadable'
  mapfile -t closure <<< "$closure_text"
  [ ''${#closure[@]} -gt 0 ] || fail 'desired closure is empty'
  nix-store --check-validity "''${closure[@]}" || fail 'desired closure is not valid'
  nix store verify --recursive --no-trust "$desired" || fail 'desired closure bytes are not valid'
  core_helper=$(readlink -e /bin/git-credential-github-roccho-dev) || fail 'B helper is absent'
  tool_helper=$(readlink -e "$desired/bin/git-credential-github-roccho-dev") || fail 'Tool helper is absent'
  [ "$core_helper" = "$tool_helper" ] || fail 'Tool helper differs from B'
  for app in codex claude python3 uv; do
    [ -x "$desired/bin/$app" ] || fail "Tool lacks $app"
  done
  [ "$("$desired/bin/codex" --version)" = "codex-cli $version" ] || fail 'desired Codex version differs'
  [ "$(readlink "$profile")" = "$before_generation" ] &&
    [ "$(readlink "$dir/$before_generation")" = "$before_store" ] || fail 'selection changed during validation'
  # Refuse active app processes, including argv[0] aliases used by wrappers.
  for proc in /proc/[0-9]*; do
    [ -e "$proc" ] || continue
    [ -r "$proc/cmdline" ] || fail 'process table is unreadable'
    IFS= read -r -d $'\0' command < "$proc/cmdline" || command=
    case "''${command##*/}" in codex|claude|python3|uv|hello) fail "active app process: $proc";; esac
  done
  if [ "$before_store" != "$desired" ]; then
    nix-env --profile "$profile" --set "$desired" || fail 'selector command failed; read back state before retry'
  fi
  after_generation=$(readlink "$profile") || fail 'selection unreadable after apply'
  [[ $after_generation =~ ^rent-dev-[1-9][0-9]*-link$ ]] || fail 'selection malformed after apply'
  [ "$(readlink "$dir/$after_generation")" = "$desired" ] || fail 'selected store differs after apply'
  [ "$(/bin/codex --version)" = "codex-cli $version" ] || fail 'default Codex version differs after apply'
  echo "selection=SELECTED generation=$after_generation store=$desired codex=$version"
''
