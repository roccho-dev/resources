#!/usr/bin/env python3
"""CI-only PROPOSED D/q preflight for existing rent B-only native-proof.sh.

Data only. Does not run nix-env, read a Target, grant access, or issue a receipt.
The shell SOURCE SUT must perform actual Docker/Nix observations and re-check.

D is CI-only and built from two sources: the Target is one file of the envs
host-binding pinned by this flake's host-bindings input (its role and site), and
B (image) and T (tool, narHash in toolFrom) are this commit's own rent builds.
No envs Draft proposal, F1 fixture or Relation projector is read.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

# The material: an ancestor commit of this branch that already defines the output, never this commit itself.
PIN = "601b275785bf8361248da90f1ae5383989b208a9"
PRODUCER = "roccho-dev/resources"
OUTPUT = "packages.x86_64-linux.rent-tool-profile"
KIND = "resources.ciRentBoundSource.v0"
STORE = re.compile(r"/nix/store/[0-9a-z]{32}-[^/\s]+\Z")
NAR = re.compile(r"sha256:[0-9a-z]{52}\Z")
IMAGE = re.compile(r"sha256:[0-9a-f]{64}\Z")
TARGET = re.compile(r"(rent)/([A-Za-z0-9][A-Za-z0-9-]*)\Z")
PROFILE = "/nix/var/nix/profiles/rent-dev"
FIELDS = {
    "kind", "admission", "target_ref", "host_ref", "unit_ref", "scope",
    "selector", "desired_output", "image", "proposed_q", "material", "identity",
}
PAIR = {"tool", "toolFrom"}
EXPECTED = {
    "tool": "ci:rent-tool-T0", "launch": "ci:rent-start-S0",
    "config_binding": "ci:rent-binding-C0", "state_contract": "ci:rent-state-K0",
}


def refuse(message):
    raise ValueError(message)


def material():
    return {"repository": PRODUCER, "source_commit": PIN, "flake_output": OUTPUT}


def proposed_q(target_ref, mat):
    canon = json.dumps({"target_ref": target_ref, "material": mat},
                       sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canon.encode()).hexdigest()


def host_binding(target_ref, host_bindings):
    """The Target must be one file of the pinned envs host-binding with that role and site."""
    found = TARGET.fullmatch(target_ref) if type(target_ref) is str else None
    if found is None:
        refuse("Target is not a rent host-binding path")
    try:
        value = json.loads((Path(host_bindings) / f"{target_ref}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        refuse("Target is not in the pinned host-binding")
    if type(value) is not dict or value.get("role") != found.group(1) or value.get("site") != found.group(2):
        refuse("host-binding role/site differ from the Target")
    return value


def build(host_bindings, target_ref, image, tool, nar):
    """CI only: the D this proof binds, from the pinned host-binding Target and this commit's B and T."""
    host_binding(target_ref, host_bindings)
    mat = material()
    return {
        "kind": KIND, "admission": "NOT_ADMITTED", "target_ref": target_ref,
        "host_ref": "ci-host-rent-1", "unit_ref": "ci-rent-oci-unit-1", "scope": "ci-session-1",
        "selector": PROFILE, "desired_output": "rent-tool-profile",
        "image": image, "tool": tool, "toolFrom": f"{PRODUCER}@{PIN}#{OUTPUT}; narHash={nar}",
        "proposed_q": proposed_q(target_ref, mat), "material": mat,
        "identity": {"base": image, **EXPECTED},
    }


def check_source(binding, host_bindings):
    """Every SOURCE field of D, or a refusal. Returns the narHash D names for its T."""
    if type(binding) is not dict or set(binding) - PAIR != FIELDS:
        refuse("binding has unrecognized or missing SOURCE fields")
    if set(binding) & PAIR != PAIR:
        refuse("tool and toolFrom are selected together")
    if (binding["kind"] != KIND or binding["admission"] != "NOT_ADMITTED"
            or binding["selector"] != PROFILE
            or binding["desired_output"] != "rent-tool-profile"):
        refuse("binding attempted adoption or foreign selector")
    host_binding(binding["target_ref"], host_bindings)
    if binding["material"] != material():
        refuse("Tool material is not this repository's pinned producer")
    if binding["proposed_q"] != proposed_q(binding["target_ref"], binding["material"]):
        refuse("q does not hash this Target and material")
    if type(binding["image"]) is not str or IMAGE.fullmatch(binding["image"]) is None:
        refuse("B is not one exact image")
    tool, origin = binding["tool"], binding["toolFrom"]
    if type(tool) is not str or STORE.fullmatch(tool) is None or type(origin) is not str:
        refuse("T is not one exact store path")
    prefix = f"{PRODUCER}@{PIN}#{OUTPUT}; narHash="
    nar = origin[len(prefix):] if origin.startswith(prefix) else ""
    if NAR.fullmatch(nar) is None:
        refuse("toolFrom does not name this material and one narHash")
    if (binding["identity"] != {"base": binding["image"], **EXPECTED}
            or binding["unit_ref"] != "ci-rent-oci-unit-1"):
        refuse("I(D) differs from the bound B and SOURCE launch/config/state")
    for key in ("host_ref", "scope"):
        if type(binding[key]) is not str or not binding[key].startswith("ci-"):
            refuse("only deliberately synthetic Host/scope test bindings are supported")
    return nar


def read_only(observation):
    """A read is distinct from admission, previous E and change permission."""
    if observation == "selection=ABSENT proof=geometry-only":
        selection = "ABSENT"
    elif re.fullmatch(
        r"selection=SELECTED generation=rent-dev-[1-9][0-9]*-link "
        r"store=/nix/store/[0-9a-z]{32}-[^/\s]+ proof=geometry-only",
        observation,
    ):
        selection = "SELECTED"
    else:
        refuse("read observation is UNKNOWN or malformed")
    return {"kind": "ci-rent-bound-read.v0", "selection": selection,
            "admission": "NOT_ADMITTED", "effect": "FORBIDDEN",
            "target_noop": "UNPROVEN"}


def preflight(binding, host_bindings, *, candidate, expected_store, nar_hash, observation, q,
              host_ref, scope, previous, base, launch, config_binding, state_contract):
    nar = check_source(binding, host_bindings)
    if q != binding["proposed_q"]:
        refuse("wrong q")
    if (type(candidate) is not str or STORE.fullmatch(candidate) is None
            or candidate != expected_store or candidate != binding["tool"]):
        refuse("candidate is not the D Tool store path")
    if nar_hash != nar:
        refuse("candidate narHash differs from the D Tool")
    if host_ref != binding["host_ref"] or scope != binding["scope"]:
        refuse("wrong explicit scoped Host/Unit")
    if (base != binding["image"] or launch != EXPECTED["launch"]
            or config_binding != EXPECTED["config_binding"]
            or state_contract != EXPECTED["state_contract"]):
        refuse("I(D) and actual SOURCE B/launch/config/state facts differ")
    if previous != "NONE":
        refuse("prior effect unresolved: only independent READ is permitted")
    read = read_only(observation)
    if read["selection"] != "ABSENT":
        refuse("same-bound initial selection is no longer ABSENT; no blind retry")
    return {
        "kind": "ci-rent-bound-change-candidate.v0",
        "stage": "SYNTHETIC_PROPOSED_DQ_PREFLIGHT_ONLY",
        "target_ref": binding["target_ref"], "host_ref": host_ref,
        "unit_ref": binding["unit_ref"], "scope": scope,
        "proposed_q": binding["proposed_q"], "candidate_store": candidate,
        "admission": "NOT_ADMITTED", "accepted_q": None,
        "target_noop": "UNPROVEN", "effect": "FORBIDDEN",
        "target_ready": False, "merge_ready": False,
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("binding", type=Path)
    p.add_argument("--mode", choices=("read", "preflight", "build"), required=True)
    p.add_argument("--observation")
    p.add_argument("--host-bindings")
    p.add_argument("--target")
    p.add_argument("--image")
    p.add_argument("--tool")
    p.add_argument("--candidate")
    p.add_argument("--expected-store")
    p.add_argument("--nar-hash")
    p.add_argument("--q")
    p.add_argument("--host-ref")
    p.add_argument("--scope")
    p.add_argument("--previous", default="NONE")
    p.add_argument("--base")
    p.add_argument("--launch")
    p.add_argument("--config-binding")
    p.add_argument("--state-contract")
    args = p.parse_args()
    try:
        if args.mode == "read":
            result = read_only(args.observation)
        elif args.mode == "build":
            result = build(args.host_bindings, args.target, args.image, args.tool, args.nar_hash)
            check_source(result, args.host_bindings)
            args.binding.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        else:
            source = json.loads(args.binding.read_text(encoding="utf-8"))
            result = preflight(source, args.host_bindings, candidate=args.candidate,
                               expected_store=args.expected_store,
                               nar_hash=args.nar_hash,
                               observation=args.observation, q=args.q,
                               host_ref=args.host_ref, scope=args.scope,
                               previous=args.previous, base=args.base,
                               launch=args.launch,
                               config_binding=args.config_binding,
                               state_contract=args.state_contract)
    except (ValueError, OSError, KeyError, TypeError) as err:
        print("SOURCE_PROPOSED_BINDING_REFUSED: " + str(err), file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
