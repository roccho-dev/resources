#!/usr/bin/env bash
# Native own (#72): select the own tool profile T as the native generation /nix/var/nix/profiles/own-dev on VersaPro.
# B (nixos/versapro.nix) never selects a T and the dev user cannot write this profile, so root runs this on the host,
# e.g. `ssh root@<versapro> bash -s <commit> < nixos/own-native-profile.sh`. T is built from the exact resources commit
# given, never a branch. Each run adds one generation and keeps the earlier ones; return with
# `nix-env --profile /nix/var/nix/profiles/own-dev --rollback`. Run it while no codex, claude or pi of dev runs, so no
# Tool changes under a running session.
set -euo pipefail
rev=${1-}
[[ $rev =~ ^[0-9a-f]{40}$ ]] || { echo 'usage: own-native-profile.sh RESOURCES_COMMIT (40 hex)' >&2; exit 2; }
[ "$(id -u)" = 0 ] || { echo 'own-native-profile: run as root' >&2; exit 2; }
# Refuse a container before building or changing any native profile. A NixOS VM is still a native OS.
[ -e /etc/NIXOS ] || { echo 'own-native-profile: NixOS host required' >&2; exit 2; }
command -v systemd-detect-virt >/dev/null || { echo 'own-native-profile: container detection unavailable' >&2; exit 2; }
container_status=0
systemd-detect-virt --container --quiet || container_status=$?
[ "$container_status" = 1 ] || { echo 'own-native-profile: container or unknown runtime is not a native target' >&2; exit 2; }
want=$(nix build "github:roccho-dev/resources/$rev#own-profile-native" --no-link --print-out-paths)
nix-env --profile /nix/var/nix/profiles/own-dev --set "$want"
test "$(readlink -f /nix/var/nix/profiles/own-dev)" = "$want"
echo "own-native-profile: selected=$want"
