#!/usr/bin/env bash
# Disposable SOURCE proof for the fixed rent B-only OCI, not a live update controller.
# CI alone owns the quiet window. Target version/admission, real credentials and WSLC are outside this proof.
# D is CI-only: the Target is one file of the pinned envs host-binding; B and T are this commit's builds.
set -Eeuo pipefail
[ "$#" = 6 ] || { echo 'usage: native-proof.sh BASE_STUB_ARCHIVE T0_STORE_PATH T1_STORE_PATH HOST_BINDINGS_DIR TARGET_REF TOOL_APPLY' >&2; exit 2; }
archive=$1 t0=$2 t1=$3 hb=$4 target=$5 apply=$6
[ -d "$hb" ] && [ ! -L "$hb" ] || { echo 'missing pinned host-binding directory' >&2; exit 2; }
[[ $t0 =~ ^/nix/store/[0-9a-z]{32}-[^/]+$ && $t1 =~ ^/nix/store/[0-9a-z]{32}-[^/]+$ ]] &&
  [ "$t0" != "$t1" ] || { echo 'expected two distinct immutable Nix Tool closures' >&2; exit 2; }
[[ $apply =~ ^/nix/store/[0-9a-z]{32}-rent-tool-apply$ ]] &&
  [ -x "$apply/bin/rent-tool-apply" ] || { echo 'expected immutable ToolApply command' >&2; exit 2; }
p="rent-native-proof-$$"
c="$p-container" repos="$p-repos" state="$p-state" nixvol="$p-nix"
evidence=$(mktemp -d)
fail() { echo "rent-native-proof: $*" >&2; exit 1; }
cleanup() {
  status=$?
  trap - EXIT
  if [ "$status" -ne 0 ]; then docker logs "$c" 2>&1 | tail -n 25 || true; fi
  docker rm -f "$c" >/dev/null 2>&1 || true
  docker volume rm "$repos" "$state" "$nixvol" >/dev/null 2>&1 || true
  rm -f -- "$evidence/seed" "$evidence/import" "$evidence"/binding*.json
  rmdir -- "$evidence" || status=1
  exit "$status"
}
trap cleanup EXIT
docker load < "$archive" >/dev/null
image=$(docker image inspect ghcr.io/roccho-dev/windows-rent:base-stub --format '{{.Id}}')
for v in "$repos" "$state" "$nixvol"; do docker volume create "$v" >/dev/null; done
docker run --rm --network none -v "$state:/s" "$image" /bin/bash -euc '
  install -d -m 700 /s/cloudflared
  printf "ci-synthetic-token\n" > /s/cloudflared/token
  chmod 600 /s/cloudflared/token
  install -d -m 755 /s/dev
  install -d -m 700 -o 1000 -g 1000 /s/dev/codex /s/dev/claude
  printf "ci-auth-not-a-credential\n" > /s/dev/codex/auth.json
  printf "ci-session-marker\n" > /s/dev/claude/ci-session-marker
  chown 1000:1000 /s/dev/codex/auth.json /s/dev/claude/ci-session-marker
  chmod 600 /s/dev/codex/auth.json /s/dev/claude/ci-session-marker'
docker run --rm --network none -v "$repos:/r" "$image" /bin/bash -euc 'printf "ci-repository-marker\n" > /r/proof-marker'
seed() {
  docker run --rm --network none -v "$nixvol:/seed" -e "RENT_NIX_VOLUME=$nixvol" \
    "$image" /bin/rent-nix-seed
}
seed > "$evidence/seed"
mount_args=(--network none -v "$repos:/work/repos" -v "$state:/var/lib/rent"
  --mount "type=volume,source=$nixvol,target=/nix,volume-nocopy"
  -e "RENT_REPOS_VOLUME=$repos" -e "RENT_STATE_VOLUME=$state" -e "RENT_NIX_VOLUME=$nixvol"
  -e "RENT_AUTHORIZED_KEY=ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHJlbnQtZGV2LXByb29mLW5vdC1hLXJlYWwta2V5 ci")
launch() {
  docker run -d --name "$c" "${mount_args[@]}" "$image" >/dev/null
  ok=0
  for _ in {1..75}; do
    if docker logs "$c" 2>&1 | grep -qF 'rent-start ok services=nix-daemon,cloudflared,sshd' &&
       docker exec "$c" /bin/test -S /nix/var/nix/daemon-socket/socket >/dev/null 2>&1; then
      ok=1; break
    fi
    [ "$(docker inspect --format '{{.State.Running}}' "$c")" = true ] || break
    sleep 1
  done
  [ "$ok" = 1 ] || fail 'base-only OCI did not become service-ready'
}
launch
# Read O using only ordinary shell and filesystem evidence; no Nix daemon query or write.
observe() { docker exec -i -u 1000:1000 "$c" /bin/bash -s < oci/rent/read-selected.sh; }
observe_ro() {
  docker run --rm -i --network none -v "$nixvol:/nix:ro" "$image" /bin/bash -s < oci/rent/read-selected.sh
}
[ "$(observe)" = 'selection=ABSENT proof=geometry-only' ] ||
  fail 'fresh B was not observed as Tool-absent'
[ "$(observe_ro)" = 'selection=ABSENT proof=geometry-only' ] ||
  fail 'readonly volume observation of empty B failed'
[ ! -e /work ] || fail 'CI proof ran with a live /work mount'
initial=$(docker exec "$c" /bin/bash -euc '
  test ! -e /nix/var/nix/profiles/rent-dev && test ! -L /nix/var/nix/profiles/rent-dev
  test ! -x /bin/codex && test -x /bin/nix && test -x /bin/gh
  printf "base-only\n"')
[ "$initial" = base-only ] || fail 'unexpected initially selected Tool'
# READ has its own scope: neither a previous UNKNOWN effect nor an admitted D
# is a precondition for this disposable readonly observation.
actual_o=$(observe_ro)
bound_read=$(python3 oci/rent/proposed-binding-proof.py /nonexistent-public-source-binding \
  --mode read --observation "$actual_o") || fail 'synthetic READ failed'
[[ $bound_read == *'"selection": "ABSENT"'* && $bound_read == *'"effect": "FORBIDDEN"'* ]] ||
  fail 'readonly observation was promoted to an effect'
# Transport the exact pre-built T closures, not an image rebuild or an implicit latest fetch.
nix-store --export $(nix-store --query --requisites "$t0" "$t1" "$apply") |
  docker exec -i "$c" /bin/nix-store --import > "$evidence/import"
for t in "$t0" "$t1" "$apply"; do
  docker exec "$c" /bin/nix-store --check-validity "$t"
done
# The narHash of a T as this disposable Target's own store reports it.
nar_of() { docker exec "$c" /bin/nix-store --query --hash "$1"; }
# D (CI only): the Target from the pinned host-binding; B is this base image and T is T0 with its narHash.
binding="$evidence/binding.json"
python3 oci/rent/proposed-binding-proof.py "$binding" --mode build --host-bindings "$hb" \
  --target "$target" --image "$image" --tool "$t0" --nar-hash "$(nar_of "$t0")" >/dev/null ||
  fail 'D could not be built from the pinned host-binding and this commit'
# This helper lives only in the fixture. Real target changes require an independent current D/authority,
# continuous quiet ownership and a recovery plan; this process does not grant any of them.
native_set() {
  local desired=$1 processes wanted_helper core_helper paths path
  [ "$(docker inspect --format '{{.State.Running}}' "$c")" = true ] || return 1
  [ "$(docker exec "$c" /bin/id -u)" = 0 ] || return 1
  processes=$(docker top "$c" -eo pid,args) || return 1
  [[ $processes == *rent-start* && $processes == *nix-daemon* && $processes == *sshd* ]] || return 1
  if grep -qE '/bin/(codex|claude|python3|uv|hello)( |$)' <<< "$processes"; then return 1; fi
  core_helper=$(docker exec "$c" /bin/readlink -e /bin/git-credential-github-roccho-dev) || return 1
  wanted_helper=$(docker exec "$c" /bin/readlink -e "$desired/bin/git-credential-github-roccho-dev") || return 1
  [ "$wanted_helper" = "$core_helper" ] || return 1
  for app in codex claude python3 uv; do
    docker exec "$c" /bin/test -x "$desired/bin/$app" || return 1
  done
  paths=$(docker exec "$c" /bin/nix-store --query --requisites "$desired") || return 1
  # shellcheck disable=SC2086
  docker exec "$c" /bin/nix-store --check-validity $paths || return 1
  docker exec "$c" /bin/nix-env --profile /nix/var/nix/profiles/rent-dev --set "$desired"
}
# CI-only functional bridge: same proposed q/Host/scope goes from readonly O
# to actual fixed closure selection. No admitted D, credential or Target GO.
q_of() {
  python3 - "$1" <<'PY'
import json,sys
with open(sys.argv[1], encoding="utf-8") as f:
    x=json.load(f)
print(x["proposed_q"])
PY
}
bound_q=$(q_of "$binding")
# bound_preflight SOURCE WANTED Q HOST SCOPE PRIOR OBSERVATION [ACTUAL_B [ACTUAL_NAR]]
bound_preflight() {
  local source=$1 wanted=$2 q=$3 host=$4 scope=$5 prior=$6 observation=$7
  local base=${8:-$image} nar=${9:-}
  [ -n "$nar" ] || nar=$(nar_of "$wanted")
  python3 oci/rent/proposed-binding-proof.py "$source" --mode preflight --host-bindings "$hb" \
    --candidate "$wanted" --expected-store "$t0" --nar-hash "$nar" --q "$q" --host-ref "$host" --scope "$scope" \
    --previous "$prior" --observation "$observation" --base "$base" \
    --launch ci:rent-start-S0 --config-binding ci:rent-binding-C0 \
    --state-contract ci:rent-state-K0
}
# variant NAME PYTHON: a copy of D changed by PYTHON (on x), with q recomputed for its own Target and material.
variant() {
  python3 - "$binding" "$evidence/binding-$1.json" "$2" <<'PY'
import hashlib,json,sys
x=json.load(open(sys.argv[1],encoding="utf-8"))
exec(sys.argv[3])
canon=json.dumps({"target_ref":x["target_ref"],"material":x["material"]},sort_keys=True,separators=(",",":"),ensure_ascii=True)
x["proposed_q"]="sha256:"+hashlib.sha256(canon.encode()).hexdigest()
json.dump(x,open(sys.argv[2],"w",encoding="utf-8"))
PY
  printf '%s\n' "$evidence/binding-$1.json"
}
selection() {
  local want=$1
  [ "$(docker exec "$c" /bin/readlink -e /nix/var/nix/profiles/rent-dev)" = "$want" ] ||
    fail "the selected native T is not $want"
  docker exec "$c" /bin/bash -euc '
    for app in codex claude python3 uv; do
      test "$(readlink -e /bin/$app)" = "$(readlink -e /nix/var/nix/profiles/rent-dev/bin/$app)"
    done
    test "$(codex --version)" = "codex-cli $(release-version codex)"
    claude --version >/dev/null
    python3 --version >/dev/null
    uv --version >/dev/null'
}
state_snapshot() {
  docker exec "$c" /bin/bash -euc '
    sha256sum /var/lib/rent/dev/codex/auth.json /var/lib/rent/dev/claude/ci-session-marker /work/repos/proof-marker
    stat -c "%n %u:%g %a" /var/lib/rent/dev/codex/auth.json /var/lib/rent/dev/claude/ci-session-marker'
}
snapshot=$(state_snapshot)
# F2: negatives against the SAME D. Each must refuse for its own reason before any native_set,
# so the empty selector, image and state persist.
before_o=$(observe_ro)
refusals=0
refuse_p1() {
  local label=$1 want=$2 out; shift 2
  if out=$(bound_preflight "$@" 2>&1); then fail "bounded SOURCE input $label reached native mutation"; fi
  [[ $out == *"SOURCE_PROPOSED_BINDING_REFUSED: $want"* ]] || fail "$label refused for another reason: $out"
  [ "$(observe_ro)" = "$before_o" ] && [ "$(state_snapshot)" = "$snapshot" ] ||
    fail "bounded refusal $label changed selection or auth/work state"
  refusals=$((refusals + 1))
  echo "REFUSED P1 $label: $want"
}
nar0=$(nar_of "$t0") nar1=$(nar_of "$t1")
[ "$nar0" != "$nar1" ] || fail 'T0 and T1 report the same narHash'
other_b="sha256:$(printf 'b%.0s' {1..64})"
ok=(ci-host-rent-1 ci-session-1 NONE "$before_o")
refuse_p1 other-T-store-path 'candidate is not the D Tool store path' "$binding" "$t1" "$bound_q" "${ok[@]}"
refuse_p1 other-T-narHash 'candidate narHash differs from the D Tool' "$binding" "$t0" "$bound_q" "${ok[@]}" "$image" "$nar1"
refuse_p1 other-B 'I(D) and actual SOURCE B/launch/config/state facts differ' "$binding" "$t0" "$bound_q" "${ok[@]}" "$other_b"
refuse_p1 wrong-q 'wrong q' "$binding" "$t0" "sha256:$(printf 'a%.0s' {1..64})" "${ok[@]}"
refuse_p1 wrong-host 'wrong explicit scoped Host/Unit' "$binding" "$t0" "$bound_q" ci-host-foreign ci-session-1 NONE "$before_o"
refuse_p1 wrong-scope 'wrong explicit scoped Host/Unit' "$binding" "$t0" "$bound_q" ci-host-rent-1 ci-other-session NONE "$before_o"
refuse_p1 unknown-effect 'prior effect unresolved' "$binding" "$t0" "$bound_q" ci-host-rent-1 ci-session-1 UNKNOWN "$before_o"
v=$(variant target-not-in-host-binding 'x["target_ref"]="rent/PC0000"')
refuse_p1 target-not-in-host-binding 'Target is not in the pinned host-binding' "$v" "$t0" "$(q_of "$v")" "${ok[@]}"
v=$(variant target-of-another-role 'x["target_ref"]="own/G6I3"')
refuse_p1 target-of-another-role 'Target is not a rent host-binding path' "$v" "$t0" "$(q_of "$v")" "${ok[@]}"
v=$(variant tool-without-toolFrom 'del x["toolFrom"]')
refuse_p1 tool-without-toolFrom 'tool and toolFrom are selected together' "$v" "$t0" "$bound_q" "${ok[@]}"
v=$(variant toolFrom-without-tool 'del x["tool"]')
refuse_p1 toolFrom-without-tool 'tool and toolFrom are selected together' "$v" "$t0" "$bound_q" "${ok[@]}"
v=$(NAR1="$nar1" variant D-narHash-of-another-T 'import os; x["toolFrom"]=x["toolFrom"].rsplit("=",1)[0]+"="+os.environ["NAR1"]')
refuse_p1 D-narHash-of-another-T 'candidate narHash differs from the D Tool' "$v" "$t0" "$bound_q" "${ok[@]}"
echo "P1 refusals: $refusals"
# The positive bound preflight is a non-executable candidate. The existing
# native_set is the ONLY Nix mutation inside this disposable Docker CI process.
preflight=$(bound_preflight "$binding" "$t0" "$bound_q" ci-host-rent-1 ci-session-1 NONE "$before_o") ||
  fail 'bound q/Host/unit/source material rejected actual first O'
[[ $preflight == *'"stage": "SYNTHETIC_PROPOSED_DQ_PREFLIGHT_ONLY"'* &&
   $preflight == *'"effect": "FORBIDDEN"'* &&
   $preflight == *'"candidate_store": "'$t0'"'* ]] ||
  fail 'bound candidate did not select the exact actual T0 closure'
native_set "$t0"
selection "$t0"
actual_bound_o=$(observe_ro)
[ "$actual_bound_o" = "selection=SELECTED generation=rent-dev-1-link store=$t0 proof=geometry-only" ] ||
  fail 'bound q effect did not read back the actual T0'
[ "$(state_snapshot)" = "$snapshot" ] || fail 'bound T changed auth/session/repo'
[ "$(docker inspect --format '{{.Image}}' "$c")" = "$image" ] ||
  fail 'bound T-only selection changed the base OCI image'
# A finite test receipt is derived from the ACTUAL post-write readback and the
# SAME preflight q/Host/store. It is a shell variable, not a runtime ledger.
bound_receipt=$(python3 - "$preflight" "$before_o" "$actual_bound_o" "$t0" "$bound_q" <<'PY'
import json,sys
intent=json.loads(sys.argv[1])
before,after,selected,q=sys.argv[2:]
assert intent["proposed_q"]==q and intent["candidate_store"]==selected
assert intent["effect"]=="FORBIDDEN" and intent["admission"]=="NOT_ADMITTED"
assert before=="selection=ABSENT proof=geometry-only"
assert after=="selection=SELECTED generation=rent-dev-1-link store="+selected+" proof=geometry-only"
print(json.dumps({"kind":"ci-rent-bound-observation.v0","attempt":"ci-rent-bound-1",
                  "proposed_q":q,"target_ref":intent["target_ref"],
                  "host_ref":intent["host_ref"],"unit_ref":intent["unit_ref"],
                  "before":before,"after":after,"store":selected,
                  "admission":"NOT_ADMITTED","target_effect_authorized":False,
                  "result":"SOURCE_CI_READBACK_ONLY"},sort_keys=True))
PY
) || fail 'bound actual O/readback attempt did not match q'
[[ $bound_receipt == *'"result": "SOURCE_CI_READBACK_ONLY"'* ]] ||
  fail 'missing bounded SOURCE attempt evidence'
# A lost receipt is UNKNOWN, not success or automatic NOOP. Re-read O but
# never perform an equivalent second write; a preflight retry must be denied.
if out=$(bound_preflight "$binding" "$t0" "$bound_q" ci-host-rent-1 ci-session-1 UNKNOWN "$actual_bound_o" 2>&1); then
  fail 'unknown bound effect retried blindly'
fi
[[ $out == *'SOURCE_PROPOSED_BINDING_REFUSED: prior effect unresolved'* ]] || fail "UNKNOWN retry refused for another reason: $out"
echo 'REFUSED P1 retry-after-UNKNOWN: prior effect unresolved'
[ "$(observe_ro)" = "$actual_bound_o" ] ||
  fail 'UNKNOWN reconciliation read mutated the selected Tool'
# Simulate losing the caller's in-memory CI receipt; selection must remain
# observed, but retry cannot fabricate an additional successful effect.
unset bound_receipt
echo 'PASS: proposed D/q/Host binding -> actual OCI O -> exact T0 Nix selector -> readback; other T (store path, narHash)/B, Target not in the host-binding, half pair, wrong q/Host/scope and UNKNOWN refused'
case "$(observe)" in
  "selection=SELECTED generation=rent-dev-1-link store=$t0 proof=geometry-only") ;;
  *) fail 'T0 observed generation does not match selected T0' ;;
esac
test "$(observe)" = "$(observe_ro)" || fail 'running/readonly observation disagrees'
if docker exec -u 1000:1000 "$c" /bin/nix-env --profile /nix/var/nix/profiles/rent-dev --set "$t1"; then
  fail 'untrusted dev selected a root-owned profile'
fi
selection "$t0"
# Failed/unknown candidate is refused before mutation; the selected generation stays current.
if native_set /nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-not-registered; then
  fail 'unregistered candidate was selected'
fi
selection "$t0"
# Real non-quiescent app-parent fixture: do not kill a process and do not switch T.
docker exec -d "$c" /bin/bash -c 'exec -a /bin/codex /bin/bash -c "sleep 4; :"'
observed=
for _ in {1..20}; do
  observed=$(docker top "$c" -eo pid,args) || fail 'process observation UNKNOWN'
  grep -qF '/bin/codex -c' <<< "$observed" && break
  sleep 0.1
done
grep -qF '/bin/codex -c' <<< "$observed" || fail 'active app-parent fixture did not stay observable'
if native_set "$t1"; then fail 'Tool switched while an app was still active'; fi
selection "$t0"
sleep 5
version=$("$t1/bin/codex" --version)
[[ $version =~ ^codex-cli\ ([0-9]+\.[0-9]+\.[0-9]+)$ ]] || fail 'T1 Codex version unreadable'
codex_version=${BASH_REMATCH[1]}
sri1=$(docker exec "$c" /bin/nix path-info --json "$t1" | jq -er 'if type == "array" then .[0].narHash else .[].narHash end')
if docker exec -u 1000:1000 "$c" "$apply/bin/rent-tool-apply" "$t0" "$t1" "$sri1" "$codex_version"; then
  fail 'dev could invoke root ToolApply'
fi
if docker exec "$c" "$apply/bin/rent-tool-apply" "$t0" "$t1" "sha256-$(printf 'A%.0s' {1..43})=" "$codex_version"; then
  fail 'ToolApply accepted a wrong NAR hash'
fi
selection "$t0"
docker exec -d "$c" /bin/bash -c 'exec -a /bin/codex /bin/bash -c "sleep 4; :"'
sleep 0.2
if docker exec "$c" "$apply/bin/rent-tool-apply" "$t0" "$t1" "$sri1" "$codex_version"; then
  fail 'ToolApply selected while Codex was active'
fi
selection "$t0"
sleep 5
docker exec "$c" "$apply/bin/rent-tool-apply" "$t0" "$t1" "$sri1" "$codex_version" |
  grep -qF "store=$t1 codex=$codex_version" || fail 'ToolApply did not acknowledge exact T1'
selection "$t1"
case "$(observe)" in
  "selection=SELECTED generation=rent-dev-2-link store=$t1 proof=geometry-only") ;;
  *) fail 'T1 selected geometry mismatch' ;;
esac
docker exec "$c" /bin/test -x /nix/var/nix/profiles/rent-dev/bin/hello || fail 'T1 extra missing'
docker exec "$c" /nix/var/nix/profiles/rent-dev/bin/hello >/dev/null
[ "$(state_snapshot)" = "$snapshot" ] || fail 'T-only generation update changed auth/session/repository'
before=$(docker exec "$c" /bin/readlink /nix/var/nix/profiles/rent-dev)
docker exec "$c" /bin/nix-env --profile /nix/var/nix/profiles/rent-dev --rollback
after=$(docker exec "$c" /bin/readlink /nix/var/nix/profiles/rent-dev)
[ "$before" != "$after" ] || fail 'native rollback did not select an earlier generation'
selection "$t0"
case "$(observe)" in
  "selection=SELECTED generation=rent-dev-1-link store=$t0 proof=geometry-only") ;;
  *) fail 'rollback was not observed as T0' ;;
esac
# A restart and a recreation retain T0; B itself does not re-select the highest T.
docker stop -t 30 "$c" >/dev/null
if native_set "$t1"; then fail 'Tool switched with no observable running context'; fi
docker start "$c" >/dev/null
for _ in {1..75}; do
  if docker exec "$c" /bin/test -S /nix/var/nix/daemon-socket/socket >/dev/null 2>&1; then break; fi
  sleep 1
done
selection "$t0"
[ "$(state_snapshot)" = "$snapshot" ] || fail 'restart changed recorded state'
native_set "$t1"
selection "$t1"
docker exec "$c" /bin/nix-store --gc >/dev/null
docker exec "$c" /bin/nix-store --check-validity "$t0" "$t1"
docker stop -t 30 "$c" >/dev/null
docker rm "$c" >/dev/null
seed > "$evidence/seed"
launch
selection "$t1"
[ "$(state_snapshot)" = "$snapshot" ] || fail 'recreation changed auth/session/repository'
test "$(observe)" = "$(observe_ro)" || fail 'recreation changed observed selection geometry'
docker exec "$c" /bin/nix-env --profile /nix/var/nix/profiles/rent-dev --list-generations
# P2/P3 SOURCE fixture: same actual Docker/Nix instance and native generations.
# The receiver is never installed into B, launched by logon, or authorized LIVE.
python3 - "$c" "$t0" "$t1" "$binding" "$hb" <<'PY'
import copy, importlib.util, json, re, subprocess, sys
from pathlib import Path
container,t0,t1,source_path,host_bindings=sys.argv[1:]
binding=json.loads(Path(source_path).read_text(encoding="utf-8"))
spec=importlib.util.spec_from_file_location("rent_receiver",Path("oci/rent/tool-receiver.py"))
assert spec and spec.loader
receiver=importlib.util.module_from_spec(spec)
spec.loader.exec_module(receiver)
spec=importlib.util.spec_from_file_location("rent_ci_bound_source",Path("oci/rent/proposed-binding-proof.py"))
assert spec and spec.loader
source=importlib.util.module_from_spec(spec)
spec.loader.exec_module(source)
q=binding["proposed_q"]
rev="ci-"+q[7:23]
subject=dict(target_ref=binding["target_ref"],host_ref=binding["host_ref"],
             unit_ref=binding["unit_ref"],scope=binding["scope"],
             actor_ref="ci-fixed-W",work_ref="ci-rent-source-SUT",
             attempt_ref="ci-rent-source-1",route_ref="ci-only-route")
def grant(granted_step,**updates):
    # Use a distinct positional variable so an intentionally invalid
    # grant_over={"step":"RECORD"} reaches the receiver rather than raising.
    g=dict(kind="envs.syntheticStageGrant.v0",**subject,step=granted_step,
           permit=True,issuer_fixture="ci-independent-source-issuer")
    g.update(updates)
    return g
def request(action,**updates):
    r=dict(kind="envs.syntheticHostSourceRequest.v0",**subject,
           action=action,proposed_q=q,
           requested_store=None if action=="READ" else t0)
    r.update(updates)
    return r
def bound(**updates):
    b=dict(kind="windows.syntheticBoundSource.v0",binding=copy.deepcopy(binding),
           host_bindings=host_bindings,
           desired=dict(kind="envs.syntheticDesired.v0",target_ref=binding["target_ref"],
                        proposed_q=q,material=binding["material"],
                        revision=rev,store_path=t0),
           current_q=rev,previous_state="NONE",read_grant=grant("READ"),
           quiet=True,single_writer=True,recovery=True,
           fixture_issuer="ci-independent-source-issuer")
    b.update(updates)
    return b
def docker(*args,input=None):
    p=subprocess.run(["docker",*args],input=input,stdout=subprocess.PIPE,
                     stderr=subprocess.PIPE,text=True)
    if p.returncode:
        raise RuntimeError("disposable Docker/Nix command failed: "+p.stderr[-700:])
    return p.stdout.strip()
def nar_of(store):
    # The narHash of a T as this disposable Target's own store reports it.
    return docker("exec",container,"/bin/nix-store","--query","--hash",store)
class Actual:
    kind="windows.syntheticDisposableNixTransport.v0"
    fixture_only=True
    def __init__(self):
        self.reads=self.selects=self.records=self.rollbacks=0
        self.fail_after_write=False
        self.fail_before_write=False
        self.fail_record_ack=False
        self.fail_rollback_before_write=False
        self.reader=Path("oci/rent/read-selected.sh").read_text(encoding="utf-8")
    def expected_producer_store(self):
        # $t0 is this commit's actual Nix-built Tool-only output, held to the
        # PIN material by output identity, independent of caller-proposed store/desired/q.
        return t0
    def observe(self):
        self.reads+=1
        try:
            raw=docker("exec","-i","-u","1000:1000",container,
                       "/bin/bash","-s",input=self.reader)
        except RuntimeError:
            return self.wrap("UNKNOWN",None,None,False)
        if raw=="selection=ABSENT proof=geometry-only":
            return self.wrap("ABSENT",None,None,True)
        matched=re.fullmatch(
            r"selection=SELECTED generation=(rent-dev-[1-9][0-9]*-link) "
            r"store=(/nix/store/[0-9a-z]{32}-[^/\s]+) proof=geometry-only",raw)
        if not matched:
            return self.wrap("UNKNOWN",None,None,False)
        store=matched.group(2)
        try:
            docker("exec",container,"/bin/nix-store","--check-validity",store)
            valid=True
        except RuntimeError:
            valid=False
        return self.wrap("SELECTED",store,matched.group(1),valid)
    def wrap(self,state,store,generation,valid):
        ident=None
        if state!="UNKNOWN":
            ident=copy.deepcopy(binding["identity"])
            ident["tool"]=("ci:rent-tool-T0" if store==t0 else
                           "ci:rent-tool-T1" if store==t1 else "ci:Tool-ABSENT")
        return dict(kind="windows.syntheticRentObservation.v0",
                    **{k:binding[k] for k in
                       ("target_ref","host_ref","unit_ref","scope")},
                    state=state,store_path=store,generation=generation,
                    identity=ident,fresh=state!="UNKNOWN",closure_valid=valid)
    def quiet(self):
        top=docker("top",container,"-eo","pid,args")
        if not all(token in top for token in ("rent-start","nix-daemon","sshd")):
            return False
        return not any(re.search(r"/bin/"+exe+r"(?:\s|$)",top)
                       for exe in ("codex","claude","python3","uv","hello"))
    def validate_closure(self,store):
        if store not in (t0,t1):
            return False
        try:
            paths=docker("exec",container,"/bin/nix-store",
                         "--query","--requisites",store).splitlines()
            for path in paths:
                docker("exec",container,"/bin/nix-store","--check-validity",path)
            helper=docker("exec",container,"/bin/readlink","-e",
                          store+"/bin/git-credential-github-roccho-dev")
            core=docker("exec",container,"/bin/readlink","-e",
                        "/bin/git-credential-github-roccho-dev")
            return helper==core
        except RuntimeError:
            return False
    def select(self,store):
        self.selects+=1
        if self.fail_before_write:
            raise RuntimeError("CI synthetic write acknowledgement unknown before Nix")
        docker("exec",container,"/bin/nix-env","--profile",
               "/nix/var/nix/profiles/rent-dev","--set",store)
        if self.fail_after_write:
            raise RuntimeError("CI synthetic acknowledgement lost after real Nix write")
    def record(self,receipt):
        self.records+=1
        if self.fail_record_ack:
            raise RuntimeError("CI record stored but acknowledgement lost")
        # This is a disposable transport ACK, not a Target receipt or ledger.
        return "CI_ONLY_RECORD_NO_TARGET_LEDGER"
    def rollback(self,preimage):
        assert preimage in (t0,t1)
        self.rollbacks+=1
        if self.fail_rollback_before_write:
            raise RuntimeError("CI-only rollback transport UNKNOWN before Nix write")
        docker("exec",container,"/bin/nix-env","--profile",
               "/nix/var/nix/profiles/rent-dev","--rollback")
port=Actual()
image=docker("inspect","-f","{{.Image}}",container)
state=docker("exec",container,"/bin/bash","-euc",
             "sha256sum /var/lib/rent/dev/codex/auth.json "
             "/var/lib/rent/dev/claude/ci-session-marker /work/repos/proof-marker")
assert port.observe()["store_path"]==t1
assert binding["image"]==image and binding["tool"]==t0
refusals=0
def call(action,*,req_over=None,grant_over=None,bound_over=None,receipt=None):
    step={"READ":"READ","CHANGE":"TOOL_CHANGE",
          "RECORD":"RECORD","ROLLBACK":"ROLLBACK"}[action]
    req=request(action,**(req_over or {}))
    g=grant(step,**(grant_over or {}))
    b=bound(**(bound_over or {}))
    if req["attempt_ref"] != subject["attempt_ref"]:
        # Explicit CI issuer grants a separate exact attempt. Do NOT rebind
        # other mutated subject fields, such as an unapproved route.
        g["attempt_ref"]=req["attempt_ref"]
        b["read_grant"]["attempt_ref"]=req["attempt_ref"]
    return receiver.receive_step(req,g,b,port,receipt=receipt)
def check(ref,stage,label=None,**kwargs):
    global refusals
    result=call(ref,**kwargs)
    assert result["stage"]==stage,(ref,stage,label,result)
    assert result["admission"]=="NOT_ADMITTED"
    assert result["production_effect"]=="FORBIDDEN"
    assert result["target_ready"] is False and result["merge_ready"] is False
    if stage=="REFUSED_PRE_EFFECT":
        refusals+=1
        print(f"REFUSED P2 {ref} {label or ''}: {stage}".replace("  "," "))
    return result
start_reads=port.reads
check("READ","REFUSED_PRE_EFFECT","revoked-read-grant",grant_over={"permit":False},
      bound_over={"desired":None,"current_q":None,"previous_state":"UNKNOWN"})
assert port.reads==start_reads and port.selects==0
got=check("READ","READ_OBSERVED",
          bound_over={"desired":None,"current_q":None,"previous_state":"UNKNOWN"})
assert got["observation"]["store_path"]==t1 and port.selects==0
# D at the receiver: a Target absent from the pinned host-binding, half of the T pair,
# another T store path and another B are refused before any select.
def d_variant(**change):
    bad=copy.deepcopy(binding)
    for key,value in change.items():
        if value is None:
            del bad[key]
        else:
            bad[key]=value
    bad["proposed_q"]=source.proposed_q(bad["target_ref"],bad["material"])
    return bad
nar1=nar_of(t1)
origin=binding["toolFrom"].rsplit("=",1)[0]+"="
other_b="sha256:"+"b"*64
for label,bad in (
    ("target-not-in-host-binding",d_variant(target_ref="rent/PC0000")),
    ("tool-without-toolFrom",d_variant(toolFrom=None)),
    ("toolFrom-without-tool",d_variant(tool=None)),
    ("other-T-store-path",d_variant(tool=t1,toolFrom=origin+nar1)),
    ("other-B",d_variant(image=other_b,identity=dict(binding["identity"],base=other_b))),
):
    check("CHANGE","REFUSED_PRE_EFFECT",label,bound_over={"binding":bad})
    assert port.selects==0 and port.records==0 and port.rollbacks==0
check("CHANGE","REFUSED_PRE_EFFECT","stage-grant-step",grant_over={"step":"RECORD"})
check("CHANGE","REFUSED_PRE_EFFECT","foreign-route",req_over={"route_ref":"ci-other-route"})
check("CHANGE","REFUSED_PRE_EFFECT","other-requested-store",req_over={"requested_store":t1})
# R B: q/material unchanged while both caller-owned desired and request
# point at t1 (the other VALID closure). This commit's built T0 is the D.
bad_d=bound()["desired"]
bad_d["store_path"]=t1
check("CHANGE","REFUSED_PRE_EFFECT","desired-and-request-other-T",req_over={"requested_store":t1},
      bound_over={"desired":bad_d})
assert port.selects==0 and port.records==0 and port.rollbacks==0
issued=check("CHANGE","TOOL_CHANGE_READBACK_CANDIDATE")["issued_receipt"]
assert issued and issued["selected"]==t0 and issued["preimage"]==t1
assert port.selects==1 and port.observe()["store_path"]==t0
check("CHANGE","REFUSED_PRE_EFFECT","same-T-no-second-write")  # same current D Tool, no second write
assert port.selects==1
check("RECORD","REFUSED_PRE_EFFECT","revoked-record-grant",grant_over={"permit":False},
      bound_over={"previous_state":"CONFIRMED","quiet":False,
                  "single_writer":False,"recovery":False},receipt=issued)
assert port.records==0
check("RECORD","REFUSED_PRE_EFFECT","copied-receipt",bound_over={"previous_state":"CONFIRMED"},
      receipt=copy.deepcopy(issued))
assert port.records==0
check("RECORD","RECORD_ONLY_CANDIDATE",
      bound_over={"previous_state":"CONFIRMED","quiet":False,
                  "single_writer":False,"recovery":False},receipt=issued)
assert port.records==1 and port.selects==1
check("RECORD","REFUSED_PRE_EFFECT","duplicate-record",
      bound_over={"previous_state":"CONFIRMED"},receipt=issued)
assert port.records==1
check("ROLLBACK","REFUSED_PRE_EFFECT","revoked-rollback-grant",grant_over={"permit":False},
      bound_over={"previous_state":"CONFIRMED"},receipt=issued)
assert port.rollbacks==0
check("ROLLBACK","ROLLBACK_READBACK_REQUIRED",
      bound_over={"previous_state":"CONFIRMED"},receipt=issued)
assert port.rollbacks==1 and port.observe()["store_path"]==t1
check("ROLLBACK","REFUSED_PRE_EFFECT","duplicate-rollback",
      bound_over={"previous_state":"CONFIRMED"},receipt=issued)
assert port.rollbacks==1
# R C: ROLLBACK must not erase the consumed-attempt tombstone. The same
# attempt, now with old T1 selected and previous_state reset, may NOT select.
check("CHANGE","REFUSED_PRE_EFFECT","consumed-attempt-after-rollback")
assert port.selects==1 and port.observe()["store_path"]==t1
# Simulate a real Nix write followed by lost acknowledgement: UNKNOWN, never
# retry an equivalent change in this disposable instance. CI cleanup is explicit.
port.fail_after_write=True
check("CHANGE","UNKNOWN_AFTER_SEND_NO_REPLAY",
      req_over={"attempt_ref":"ci-rent-source-2"})
assert port.selects==2 and port.observe()["store_path"]==t0
check("CHANGE","REFUSED_PRE_EFFECT","retry-after-UNKNOWN-write",
      req_over={"attempt_ref":"ci-rent-source-2"})
assert port.selects==2
docker("exec",container,"/bin/nix-env","--profile",
       "/nix/var/nix/profiles/rent-dev","--rollback") # CI teardown, NOT receiver retry
assert port.observe()["store_path"]==t1
# R C: when an invoked select fails before an actual Nix write, the OLD O
# remains visible but that same attempt must still never be replayed.
port.fail_after_write=False
port.fail_before_write=True
check("CHANGE","UNKNOWN_AFTER_SEND_NO_REPLAY",
      req_over={"attempt_ref":"ci-rent-source-3"})
assert port.selects==3 and port.observe()["store_path"]==t1
port.fail_before_write=False
check("CHANGE","REFUSED_PRE_EFFECT","retry-after-UNKNOWN-before-write",
      req_over={"attempt_ref":"ci-rent-source-3"})
assert port.selects==3 and port.observe()["store_path"]==t1
# R A: RECORD ACK loss can follow a real CI-only record side effect. The
# same attempt's second RECORD must not call transport.record again.
issued4=check("CHANGE","TOOL_CHANGE_READBACK_CANDIDATE",
              req_over={"attempt_ref":"ci-rent-source-4"})["issued_receipt"]
assert issued4["selected"]==t0 and port.selects==4
port.fail_record_ack=True
check("RECORD","UNKNOWN_AFTER_SEND_NO_REPLAY",
      req_over={"attempt_ref":"ci-rent-source-4"},
      bound_over={"previous_state":"CONFIRMED"},receipt=issued4)
assert port.records==2
port.fail_record_ack=False
check("RECORD","REFUSED_PRE_EFFECT","retry-after-UNKNOWN-record",
      req_over={"attempt_ref":"ci-rent-source-4"},
      bound_over={"previous_state":"CONFIRMED"},receipt=issued4)
assert port.records==2 and port.selects==4
docker("exec",container,"/bin/nix-env","--profile",
       "/nix/var/nix/profiles/rent-dev","--rollback") # CI teardown only
assert port.observe()["store_path"]==t1
# R2: a genuine receipt for a new CHANGE is not a license to replay ROLLBACK
# when the first rollback was invoked but its ACK disappeared BEFORE Nix wrote.
# The SAME real Docker/Nix container stays T0 after the injected exception.
issued5=check("CHANGE","TOOL_CHANGE_READBACK_CANDIDATE",
              req_over={"attempt_ref":"ci-rent-source-5"})["issued_receipt"]
assert issued5["preimage"]==t1 and issued5["selected"]==t0
assert port.selects==5 and port.observe()["store_path"]==t0
before_rollback=port.rollbacks
port.fail_rollback_before_write=True
check("ROLLBACK","UNKNOWN_AFTER_SEND_NO_REPLAY",
      req_over={"attempt_ref":"ci-rent-source-5"},
      bound_over={"previous_state":"CONFIRMED"},receipt=issued5)
assert port.rollbacks==before_rollback+1 and port.observe()["store_path"]==t0
port.fail_rollback_before_write=False
check("ROLLBACK","REFUSED_PRE_EFFECT","retry-after-UNKNOWN-rollback",
      req_over={"attempt_ref":"ci-rent-source-5"},
      bound_over={"previous_state":"CONFIRMED"},receipt=issued5)
assert port.rollbacks==before_rollback+1 and port.observe()["store_path"]==t0
# Independently permitted READ remains possible after UNKNOWN but does not
# settle the old rollback outcome or permit an equivalent retry.
read_after_unknown=check("READ","READ_OBSERVED",
      req_over={"attempt_ref":"ci-rent-source-5"},
      bound_over={"desired":None,"current_q":None,"previous_state":"UNKNOWN"})
assert read_after_unknown["observation"]["store_path"]==t0
assert port.rollbacks==before_rollback+1 and port.records==2 and port.selects==5
docker("exec",container,"/bin/nix-env","--profile",
       "/nix/var/nix/profiles/rent-dev","--rollback") # CI teardown only; not receiver recovery
assert port.observe()["store_path"]==t1
assert docker("inspect","-f","{{.Image}}",container)==image
assert docker("exec",container,"/bin/bash","-euc",
              "sha256sum /var/lib/rent/dev/codex/auth.json "
              "/var/lib/rent/dev/claude/ci-session-marker /work/repos/proof-marker")==state
print(f"PASS: same real OCI/Nix receiver READ->CHANGE->RECORD-only->ROLLBACK; {refusals} pre-effect "
      "refusals with zero transport effect, post-send CHANGE/RECORD/ROLLBACK UNKNOWN no replay, "
      "Base/state unchanged")
# P3: the CI-only minimal caller in THIS Python process against THIS SAME
# disposable receiver + Docker/Nix Port. Nothing is downloaded.
import runpy
runpy.run_path("oci/rent/caller-receiver-proof.py", run_name="__main__",
               init_globals={
                   "P2_ACTUAL": port, "P2_RECEIVER": receiver, "P2_BINDING": binding,
                   "P2_HOST_BINDINGS": host_bindings, "P2_NAR": nar_of, "P2_DOCKER": docker,
                   "P2_REQUEST": request, "P2_GRANT": grant, "P2_BOUND": bound,
                   "P2_CONTAINER": container, "P2_T0": t0, "P2_T1": t1,
                   "P2_Q": q, "P2_REV": rev, "P2_IMAGE": image, "P2_STATE": state,
               })
PY
# Negative O-only fixtures run with the synthetic OCI stopped; each damaged preimage is retained
# and each read must refuse without mutation. Repair is part of disposable test, not observer code.
docker stop -t 30 "$c" >/dev/null
profile_geometry() {
  docker run --rm --network none -v "$nixvol:/nix:ro" "$image" /bin/bash -euc '
    cd /nix
    stat -c "%n|%a|%u|%g" var var/nix var/nix/profiles
    find var/nix/profiles var/nix/gcroots -printf "%p|%y|%l|%m|%U|%G|%s|%T@\n" | LC_ALL=C sort
    sha256sum var/rent-nix var/nix/db/db.sqlite' | sha256sum
}
assert_unknown_read_only() {
  local expected=$1 before after rc=0 outcome
  before=$(profile_geometry)
  outcome=$(observe_ro 2>&1) || rc=$?
  [ "$rc" = 2 ] && [[ $outcome == "rent-selection: UNKNOWN ("* ]] ||
    fail "observer accepted $expected or returned unexpected result"
  after=$(profile_geometry)
  [ "$before" = "$after" ] || fail "observation mutated $expected profile or store metadata"
}
sel=$(docker run --rm --network none -v "$nixvol:/nix:ro" "$image" /bin/readlink /nix/var/nix/profiles/rent-dev)
[[ $sel =~ ^rent-dev-[0-9]+-link$ ]] || fail 'invalid fixture preimage selection'
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/ln -sfn /tmp/foreign /nix/var/nix/profiles/rent-dev
assert_unknown_read_only 'foreign selected link'
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/ln -sfn "$sel" /nix/var/nix/profiles/rent-dev
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/ln -s /nix/store/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-foreign /nix/var/nix/profiles/rent-dev-999-link
assert_unknown_read_only 'invalid extra generation'
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/rm /nix/var/nix/profiles/rent-dev-999-link
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/ln -s /tmp/unfinished /nix/var/nix/profiles/.rent-dev.pending
assert_unknown_read_only 'interrupted profile selector'
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/rm /nix/var/nix/profiles/.rent-dev.pending
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/rm /nix/var/nix/profiles/rent-dev
assert_unknown_read_only 'orphan generations'
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/ln -s "$sel" /nix/var/nix/profiles/rent-dev
test "$(observe_ro)" = "selection=SELECTED generation=$sel store=$t1 proof=geometry-only" ||
  fail 'valid selector was not restored in disposable fixture'

# The B-only profileCheck also requires all three parent directories to be root-owned and not
# group/other writable. The observer must never call this geometry SELECTED/ABSENT when B refuses.
# Changes below touch only the disposable, stopped CI volume; all observations mount /nix read-only.
assert_base_refuses_unsafe() {
  local label=$1 before
  before=$(profile_geometry)
  if seed > "$evidence/seed" 2>&1; then fail "B-only seed accepted $label"; fi
  grep -qF 'foreign, invalid or incompatible retained generation' "$evidence/seed" ||
    fail "B-only seed refused $label for the wrong reason"
  if docker run --rm "${mount_args[@]}" "$image" > "$evidence/seed" 2>&1; then
    fail "B-only start accepted $label"
  fi
  grep -qF 'rent-profile: foreign, invalid or incompatible retained generation' "$evidence/seed" ||
    fail "B-only start refused $label for the wrong reason"
  [ "$(profile_geometry)" = "$before" ] || fail "B-only refusal wrote metadata for $label"
}
for spec in "var/nix/profiles 777" "var/nix 775" "var 777"; do
  read -r relative unsafe_mode <<< "$spec"
  before_mode=$(docker run --rm --network none -v "$nixvol:/nix:ro" "$image"     /bin/stat -c %a "/nix/$relative")
  docker run --rm --network none -v "$nixvol:/nix" "$image"     /bin/chmod "$unsafe_mode" "/nix/$relative"
  assert_unknown_read_only "selected parent $relative mode $unsafe_mode"
  if [ "$relative" = var/nix/profiles ]; then
    assert_base_refuses_unsafe 'SELECTED with world-writable profiles'
  fi
  docker run --rm --network none -v "$nixvol:/nix" "$image"     /bin/chmod "$before_mode" "/nix/$relative"
  test "$(observe_ro)" = "selection=SELECTED generation=$sel store=$t1 proof=geometry-only" ||
    fail "restored selected parent $relative was not observed"
done

# ABSENT is not safe merely because the active selector is missing: even with every generation
# removed, an unsafe parent directory could let an untrusted user install a malicious selector.
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/bash -euc '
  d=/nix/var/nix/profiles
  test -L "$d/rent-dev" && rm -- "$d/rent-dev"
  for g in "$d"/rent-dev-*-link; do test -L "$g"; rm -- "$g"; done'
test "$(observe_ro)" = 'selection=ABSENT proof=geometry-only' ||
  fail 'fixture did not reach a valid ABSENT state before permission change'
before_mode=$(docker run --rm --network none -v "$nixvol:/nix:ro" "$image"   /bin/stat -c %a /nix/var/nix/profiles)
docker run --rm --network none -v "$nixvol:/nix" "$image" /bin/chmod 777 /nix/var/nix/profiles
assert_unknown_read_only 'ABSENT with world-writable profiles'
assert_base_refuses_unsafe 'ABSENT with world-writable profiles'
docker run --rm --network none -v "$nixvol:/nix" "$image"   /bin/chmod "$before_mode" /nix/var/nix/profiles
test "$(observe_ro)" = 'selection=ABSENT proof=geometry-only' ||
  fail 'valid ABSENT was not restored after the isolated permission fixture'
echo 'PASS: SOURCE-only native T0->T1, rollback/GC/recreate, read-only observation and unsafe parent modes refused for SELECTED/ABSENT'
