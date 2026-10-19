#!/usr/bin/env python3
"""P3: a CI-only minimal caller -> Windows P2 receiver -> ONE disposable OCI/Nix Port.

Invoked only by oci/rent/native-proof.sh in a disposable SOURCE CI container.
CI ONLY: the caller below exists only inside this proof. It is not a production
caller, an envs entry, a Target route, an admitted D, a grant store or a receipt
ledger; where stage grants and receipts live is decided at the real Target stage.
It keeps only the READ/CHANGE/RECORD/ROLLBACK stage decisions this proof needs and
has no Relation. D is the pinned envs host-binding Target with this commit's B and
T (proposed-binding-proof.py check_source); nothing is downloaded from envs.
"""
from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

STEPS = {"READ": "READ", "CHANGE": "TOOL_CHANGE", "RECORD": "RECORD", "ROLLBACK": "ROLLBACK"}
SUBJECT = ("target_ref", "host_ref", "unit_ref", "scope",
           "route_ref", "actor_ref", "work_ref", "attempt_ref")
REQUEST_KEYS = {"kind", "action", *SUBJECT, "proposed_q", "requested_store"}
AUTH_KEYS = {"kind", *SUBJECT, "read", "change", "record", "rollback",
             "quiet", "single_writer", "recovery", "route"}
GRANT_KEYS = {"kind", *SUBJECT, "step", "permit", "issuer_fixture"}
DESIRED_KEYS = {"kind", "admission", "target_ref", "proposed_q", "material",
                "revision", "store_path"}
O_KEYS = {"kind", "target_ref", "host_ref", "unit_ref", "scope", "state",
          "store_path", "identity", "fresh", "closure_valid"}

_spec = importlib.util.spec_from_file_location(
    "rent_ci_bound_source", Path("oci/rent/proposed-binding-proof.py"))
assert _spec is not None and _spec.loader is not None
source = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(source)


def require(ok, why):
    if not ok:
        raise ValueError(why)


def exact(value, keys, why):
    require(type(value) is dict and set(value) == keys, why)
    return value


def verdict(stage, *, observation=None, receipt=None):
    return {"kind": "resources.ciMinimalCallerVerdict.v0", "stage": stage,
            "observation": observation, "issued_receipt": receipt,
            "admission": "NOT_ADMITTED", "accepted_q": None,
            "target_noop": "UNPROVEN", "effect": "FORBIDDEN",
            "target_ready": False, "merge_ready": False}


def granted(grant, request, step):
    g = exact(grant, GRANT_KEYS, "stage grant shape")
    require(g["kind"] == "envs.syntheticStageGrant.v0" and g["step"] == step
            and type(g["permit"]) is bool and g["permit"] is True
            and g["issuer_fixture"] == "ci-independent-source-issuer"
            and all(g[k] == request[k] for k in SUBJECT),
            "missing or foreign stage-specific permit")


def observed(value, request):
    o = exact(value, O_KEYS, "observation shape")
    require(o["kind"] == "envs.syntheticPortObservation.v0"
            and all(o[k] == request[k] for k in ("target_ref", "host_ref", "unit_ref", "scope"))
            and o["state"] in ("ABSENT", "SELECTED", "UNKNOWN")
            and type(o["fresh"]) is bool and type(o["closure_valid"]) is bool,
            "observation does not match the explicit Target/Unit")
    if o["state"] == "SELECTED":
        require(type(o["store_path"]) is str and source.STORE.fullmatch(o["store_path"]) is not None
                and type(o["identity"]) is dict, "selected Target has malformed material or identity")
    else:
        require(o["store_path"] is None, "absent or unknown Tool asserted material")
    if type(o["identity"]) is dict:
        require(o["identity"].get("target_ref") == request["target_ref"]
                and o["identity"].get("unit_ref") == request["unit_ref"],
                "observation not for the exact Target/Unit")
    return o


def source_step(request, *, binding, host_bindings, nar_of, authority, read_grant,
                stage_grant, current_q, desired, previous, port, receipt=None):
    """CI-only minimal caller: one stage against the explicitly injected disposable Port."""
    try:
        nar = source.check_source(binding, host_bindings)
        req = exact(request, REQUEST_KEYS, "request shape")
        require(req["kind"] == "envs.syntheticHostSourceRequest.v0" and req["action"] in STEPS,
                "unsupported action")
        require(all(req[k] == binding[k] for k in ("target_ref", "host_ref", "unit_ref", "scope"))
                and req["proposed_q"] == binding["proposed_q"],
                "foreign Host/Target/Unit/scope or q")
        for k in ("actor_ref", "work_ref", "attempt_ref", "route_ref"):
            require(type(req[k]) is str and req[k].startswith("ci-") and 4 <= len(req[k]) <= 100,
                    "subject and route must be explicit ci-only identities")
        if req["action"] == "READ":
            require(req["requested_store"] is None, "READ includes mutation material")
        else:
            require(req["requested_store"] == binding["tool"], "mutation material is not the D Tool")
            require(nar_of(binding["tool"]) == nar, "D Tool narHash differs from its realised closure")
        auth = exact(authority, AUTH_KEYS, "scoped authority shape")
        require(auth["kind"] == "envs.syntheticScopedAuthority.v0"
                and all(auth[k] == req[k] for k in SUBJECT)
                and all(type(auth[k]) is bool for k in ("read", "change", "record", "rollback",
                                                         "quiet", "single_writer", "recovery", "route")),
                "scoped authority absent or foreign")
        require(getattr(port, "kind", None) == "envs.syntheticDisposableTargetPort.v0"
                and getattr(port, "fixture_only", None) is True
                and all(callable(getattr(port, f, None)) for f in ("observe", "select", "record", "rollback")),
                "no explicitly injected disposable Target port")
        require(auth["read"] and auth["route"], "no scoped READ or route")
        granted(read_grant, req, "READ")
        action = req["action"]
        if action == "READ":
            # READ needs no D, old q, change rights or resolution of a prior UNKNOWN.
            return verdict("SYNTHETIC_READ_OBSERVED", observation=observed(port.observe(), req))
        granted(stage_grant, req, STEPS[action])
        if action == "CHANGE":
            require(auth["change"] and auth["quiet"] and auth["single_writer"] and auth["recovery"],
                    "TOOL_CHANGE-specific permit incomplete")
        elif action == "RECORD":
            require(auth["record"], "RECORD-specific permit absent")
        else:
            require(auth["rollback"] and auth["quiet"] and auth["single_writer"] and auth["recovery"],
                    "ROLLBACK-specific permit incomplete")
        d = exact(desired, DESIRED_KEYS, "synthetic D shape")
        require(d["kind"] == "envs.syntheticDesired.v0" and d["admission"] == "SYNTHETIC_ADMITTED"
                and type(current_q) is str
                and d["target_ref"] == binding["target_ref"]
                and d["proposed_q"] == binding["proposed_q"]
                and d["material"] == binding["material"]
                and d["revision"] == "ci-" + binding["proposed_q"][7:23]
                and current_q == d["revision"]
                and req["requested_store"] == d["store_path"],
                "missing or superseded synthetic D/current q")
        require(type(previous) is dict and previous.get("target_ref") == binding["target_ref"]
                and previous.get("kind") == "envs.syntheticEffect.v0",
                "previous effect is not an exact SOURCE fact")
        require(previous.get("state") == ("NONE" if action == "CHANGE" else "CONFIRMED"),
                "old effect unknown or not yet confirmed")
        want = {"target_ref": binding["target_ref"], "unit_ref": binding["unit_ref"], **binding["identity"]}
        obs = observed(port.observe(), req)
        require(obs["state"] != "UNKNOWN" and obs["fresh"] and obs["closure_valid"],
                "fresh bounded O is unavailable")
        if action == "CHANGE":
            require(type(obs["identity"]) is dict
                    and {k: v for k, v in obs["identity"].items() if k != "tool"}
                    == {k: v for k, v in want.items() if k != "tool"}
                    and obs["store_path"] != req["requested_store"],
                    "not a current q Tool-only change")
            try:
                issued = port.select(req["requested_store"], req["attempt_ref"], d["revision"])
            except Exception:
                return verdict("SYNTHETIC_EFFECT_UNKNOWN_NO_REPLAY")
            if (type(issued) is not dict or issued.get("attempt") != req["attempt_ref"]
                    or issued.get("selected") != req["requested_store"]
                    or issued.get("effect") != "SYNTHETIC_ONLY"
                    or issued.get("preimage") != obs["store_path"]):
                return verdict("SYNTHETIC_EFFECT_UNKNOWN_NO_REPLAY")
            try:
                final = observed(port.observe(), req)
            except Exception:
                return verdict("SYNTHETIC_READBACK_UNKNOWN_NO_REPLAY", receipt=issued)
            if (final["state"] != "SELECTED" or final["store_path"] != req["requested_store"]
                    or final["identity"] != want or not final["fresh"] or not final["closure_valid"]):
                return verdict("SYNTHETIC_READBACK_UNKNOWN_NO_REPLAY", receipt=issued)
            return verdict("SYNTHETIC_READBACK_CANDIDATE_NOT_SUCCESS", observation=final, receipt=issued)
        require(obs["store_path"] == req["requested_store"] and obs["identity"] == want,
                "not the exact confirmed Tool readback")
        require(type(receipt) is dict and receipt.get("attempt") == req["attempt_ref"]
                and receipt.get("selected") == req["requested_store"]
                and receipt.get("effect") == "SYNTHETIC_ONLY",
                "missing exact test receipt")
        try:
            if action == "RECORD":
                output = port.record(receipt, d["revision"])
            else:
                output = port.rollback(receipt, req["attempt_ref"], d)
        except ValueError:
            # Port contract: ValueError is a verified pre-write refusal. It grants no retry.
            return verdict("REFUSED_PORT_PRECONDITION")
        except Exception:
            return verdict("SYNTHETIC_EFFECT_UNKNOWN_NO_REPLAY")
        if output not in ("SYNTHETIC_RECORD_ONLY", "SYNTHETIC_ROLLBACK_NOT_NEW_D_SUCCESS"):
            return verdict("SYNTHETIC_EFFECT_UNKNOWN_NO_REPLAY")
        return verdict("SYNTHETIC_RECORD_ONLY_CANDIDATE" if action == "RECORD"
                       else "SYNTHETIC_ROLLBACK_READBACK_REQUIRED")
    except (ValueError, TypeError, KeyError, AttributeError):
        return verdict("REFUSED_SOURCE_OR_AUTHORITY")


def proof():
    # All references below must be passed from the EXISTING P2 here-doc,
    # not a second Docker instance or independent fake Port.
    actual = P2_ACTUAL
    receiver = P2_RECEIVER
    binding = P2_BINDING
    host_bindings = P2_HOST_BINDINGS
    nar_of = P2_NAR
    docker = P2_DOCKER
    request = P2_REQUEST
    grant = P2_GRANT
    bound = P2_BOUND
    container, t0, t1 = P2_CONTAINER, P2_T0, P2_T1
    q, rev = P2_Q, P2_REV
    same_image, state_before = P2_IMAGE, P2_STATE
    assert actual.fixture_only is True
    assert actual.kind == "windows.syntheticDisposableNixTransport.v0"
    assert binding["proposed_q"] == q
    assert binding["target_ref"] == "rent/PC7337" and binding["tool"] == t0
    assert binding["image"] == same_image
    source.check_source(binding, host_bindings)
    assert actual.observe()["store_path"] == t1
    assert docker("inspect", "-f", "{{.Image}}", container) == same_image

    ref = {k: binding[k] for k in ("target_ref", "host_ref", "unit_ref", "scope")}
    subject = dict(ref, actor_ref="ci-fixed-W", work_ref="ci-p3-same-nix-work",
                   attempt_ref="ci-p3-1", route_ref="ci-only-route")

    def g(subject, step):
        return {"kind": "envs.syntheticStageGrant.v0", **subject,
                "step": step, "permit": True,
                "issuer_fixture": "ci-independent-source-issuer"}

    def previous(state):
        return {"kind": "envs.syntheticEffect.v0",
                "target_ref": ref["target_ref"], "state": state,
                "revision": rev if state == "CONFIRMED" else None,
                "store_path": t0 if state == "CONFIRMED" else None}

    class SamePortBridge:
        kind = "envs.syntheticDisposableTargetPort.v0"
        fixture_only = True

        def __init__(self):
            # Preserve identity: this is the SAME actual P2 Docker/Nix Port.
            self.actual = actual
            self.receiver = receiver
            self.route_calls = {"READ": 0, "CHANGE": 0, "RECORD": 0, "ROLLBACK": 0}
            self.attempt = "ci-p3-1"

        def receive(self, step, *, receipt=None, store=None):
            action = step
            req = request(action, actor_ref=subject["actor_ref"],
                          work_ref=subject["work_ref"],
                          route_ref=subject["route_ref"],
                          attempt_ref=self.attempt,
                          requested_store=None if action == "READ" else t0)
            if store is not None:
                req["requested_store"] = store
            rgrant = grant("READ", actor_ref=req["actor_ref"],
                           work_ref=req["work_ref"], route_ref=req["route_ref"],
                           attempt_ref=req["attempt_ref"])
            sgrant = grant({"READ": "READ", "CHANGE": "TOOL_CHANGE",
                            "RECORD": "RECORD", "ROLLBACK": "ROLLBACK"}[action],
                           actor_ref=req["actor_ref"], work_ref=req["work_ref"],
                           route_ref=req["route_ref"], attempt_ref=req["attempt_ref"])
            b = bound(read_grant=rgrant,
                      previous_state="CONFIRMED" if action in ("RECORD", "ROLLBACK") else "NONE")
            self.route_calls[action] += 1
            return self.receiver.receive_step(req, sgrant, b, self.actual, receipt=receipt)

        def observe(self):
            outcome = self.receive("READ")
            if outcome["stage"] not in ("READ_OBSERVED", "READ_UNKNOWN"):
                raise ValueError("P2 receiver refused current P3 readonly observation")
            observed_o = outcome["observation"]
            ident = copy.deepcopy(observed_o["identity"])
            if ident is not None:
                ident.update(target_ref=ref["target_ref"], unit_ref=ref["unit_ref"])
            return {"kind": "envs.syntheticPortObservation.v0", **ref,
                    "state": observed_o["state"], "store_path": observed_o["store_path"],
                    "identity": ident, "fresh": observed_o["fresh"],
                    "closure_valid": observed_o["closure_valid"]}

        def select(self, store, attempt, revision):
            assert revision == rev and store == t0
            self.attempt = attempt
            result = self.receive("CHANGE", store=store)
            if result["stage"] != "TOOL_CHANGE_READBACK_CANDIDATE":
                raise RuntimeError("P2 receiver change not proven: " + result["stage"])
            return result["issued_receipt"]

        def record(self, receipt, revision):
            assert revision == rev
            self.attempt = receipt["attempt"]
            result = self.receive("RECORD", receipt=receipt)
            if result["stage"] != "RECORD_ONLY_CANDIDATE":
                raise ValueError("P2 receiver record was refused: " + result["stage"])
            return "SYNTHETIC_RECORD_ONLY"

        def rollback(self, receipt, attempt, desired):
            assert desired["revision"] == rev
            self.attempt = attempt
            result = self.receive("ROLLBACK", receipt=receipt)
            if result["stage"] != "ROLLBACK_READBACK_REQUIRED":
                raise ValueError("P2 receiver rollback was refused: " + result["stage"])
            return "SYNTHETIC_ROLLBACK_NOT_NEW_D_SUCCESS"

    bridge = SamePortBridge()
    # The caller demands this explicit CI-only synthetic admission shape; it is
    # never an accepted D, Target permit, or P2 receiver D.
    desired = {"kind": "envs.syntheticDesired.v0",
               "admission": "SYNTHETIC_ADMITTED",
               "target_ref": ref["target_ref"], "proposed_q": q,
               "material": copy.deepcopy(binding["material"]),
               "revision": rev, "store_path": t0}
    access = {"kind": "envs.syntheticScopedAuthority.v0", **subject,
              "read": True, "change": True, "record": True,
              "rollback": True, "quiet": True, "single_writer": True,
              "recovery": True, "route": True}

    def call(action, *, attempt="ci-p3-1", authority_override=None,
             stage_override=None, read_override=None,
             desired_override="CURRENT", prior="NONE", receipt=None,
             request_override=None, binding_override=None):
        reqsubject = dict(subject, attempt_ref=attempt)
        bridge.attempt = attempt
        req = {"kind": "envs.syntheticHostSourceRequest.v0", **reqsubject,
               "action": action, "proposed_q": q,
               "requested_store": None if action == "READ" else t0}
        # Finite caller-request tampering ONLY; the P2 receiver, real Nix Port,
        # grants and q stay fixed.
        if request_override is not None:
            assert set(request_override) <= {
                "target_ref", "host_ref", "unit_ref", "proposed_q",
                "requested_store", "attempt_ref",
            }
            req.update(request_override)
        auth = dict(access, attempt_ref=attempt)
        if authority_override is not None:
            auth.update(authority_override)
        rg = g(reqsubject, "READ")
        if read_override is not None:
            rg.update(read_override)
        sg = g(reqsubject, STEPS[action])
        if stage_override is not None:
            sg.update(stage_override)
        return source_step(
            req, binding=copy.deepcopy(binding if binding_override is None else binding_override),
            host_bindings=host_bindings, nar_of=nar_of, authority=auth,
            read_grant=rg, stage_grant=None if action == "READ" else sg,
            current_q=rev,
            desired=(copy.deepcopy(desired) if desired_override == "CURRENT"
                     else desired_override),
            previous=previous(prior), port=bridge, receipt=receipt,
        )

    def inert(outcome):
        assert outcome["effect"] == "FORBIDDEN"
        assert outcome["admission"] == "NOT_ADMITTED"
        assert outcome["accepted_q"] is None
        assert outcome["target_ready"] is False and outcome["merge_ready"] is False

    # The original P2 CI has T1 selected. P3 operates on THIS same real Port.
    original_snapshot = docker("exec", container, "/bin/bash", "-euc",
                               "sha256sum /var/lib/rent/dev/codex/auth.json "
                               "/var/lib/rent/dev/claude/ci-session-marker "
                               "/work/repos/proof-marker")
    original_counts = (actual.selects, actual.records, actual.rollbacks)

    def real_port_snapshot():
        # Only disposable CI Nix, image and opaque auth/work hashes.
        return (
            actual.observe()["store_path"],
            docker("inspect", "-f", "{{.Image}}", container),
            docker("exec", container, "/bin/bash", "-euc",
                   "sha256sum /var/lib/rent/dev/codex/auth.json "
                   "/var/lib/rent/dev/claude/ci-session-marker "
                   "/work/repos/proof-marker"),
        )

    refusals = 0

    def assert_real_refusal(action, *, label, expected="REFUSED_SOURCE_OR_AUTHORITY",
                            before_read=False, **overrides):
        nonlocal refusals
        baseline = real_port_snapshot()
        before = (actual.reads, actual.selects,
                  actual.records, actual.rollbacks)
        outcome = call(action, **overrides)
        assert outcome["stage"] == expected, (label, outcome)
        inert(outcome)
        assert (actual.selects, actual.records, actual.rollbacks) == before[1:]
        if before_read:
            # Foreign D, identity, material, attempt or revoked grant must fail
            # BEFORE the sole real receiver's observation.
            assert actual.reads == before[0], label
        else:
            # Copied-receipt and B checks may perform independent READ-only O.
            assert actual.reads >= before[0]
        assert real_port_snapshot() == baseline
        refusals += 1
        print(f"REFUSED P3 {action} {label}: {outcome['stage']}")
        return outcome

    start_reads = actual.reads
    refused = call("READ", read_override={"permit": False},
                   desired_override=None, prior="UNKNOWN")
    assert refused["stage"] == "REFUSED_SOURCE_OR_AUTHORITY"
    inert(refused)
    assert actual.reads == start_reads
    refusals += 1
    print("REFUSED P3 READ revoked-read-grant: REFUSED_SOURCE_OR_AUTHORITY")
    read = call("READ", desired_override=None, prior="UNKNOWN",
                authority_override={"change": False, "quiet": False,
                                    "single_writer": False, "recovery": False})
    assert read["stage"] == "SYNTHETIC_READ_OBSERVED"
    assert read["observation"]["store_path"] == t1
    inert(read)

    # D from the pinned host-binding and this commit's B/T: a Target absent from
    # the host-binding, half of the T pair, another T (store path or narHash) and
    # another B are refused, and none of them selects.
    def variant(**change):
        bad = copy.deepcopy(binding)
        for key, value in change.items():
            if value is None:
                del bad[key]
            else:
                bad[key] = value
        bad["proposed_q"] = source.proposed_q(bad["target_ref"], bad["material"])
        return bad

    nar_t0, nar_t1 = nar_of(t0), nar_of(t1)
    origin = binding["toolFrom"][: -len(nar_t0)]
    other_b = "sha256:" + "b" * 64
    assert other_b != same_image and nar_t0 != nar_t1
    foreign = variant(target_ref="rent/PC0000")
    for label, bad, before_read in (
        ("target-not-in-host-binding", foreign, True),
        ("tool-without-toolFrom", variant(toolFrom=None), True),
        ("toolFrom-without-tool", variant(tool=None), True),
        ("other-T-store-path", variant(tool=t1, toolFrom=origin + nar_t1), True),
        ("other-T-narHash", variant(toolFrom=origin + nar_t1), True),
        ("other-B", variant(image=other_b, identity=dict(binding["identity"], base=other_b)), False),
    ):
        # The request names the bad D's own Target and q, so only the D defect decides.
        assert_real_refusal("CHANGE", label=label, before_read=before_read, binding_override=bad,
                            request_override={"target_ref": bad["target_ref"],
                                              "proposed_q": bad["proposed_q"]}
                            if label == "target-not-in-host-binding" else None)
    assert (actual.selects, actual.records, actual.rollbacks) == original_counts

    for override in ({"permit": False}, {"permit": None},
                     {"step": "RECORD"},
                     {"route_ref": "ci-invalid-route"}):
        assert_real_refusal("CHANGE", label="stage-grant " + repr(override),
                            stage_override=override, before_read=True)
    bad_q = "sha256:" + "0" * 64
    assert bad_q != q
    for bad_request in (
        {"target_ref": "rent/PC0001"},
        {"host_ref": "ci-foreign-host"},
        {"unit_ref": "ci-foreign-unit"},
        {"proposed_q": bad_q},
        {"requested_store": "/nix/store/" + "c" * 32 + "-foreign-tool"},
        {"attempt_ref": "ci-old-attempt"},
    ):
        assert_real_refusal("CHANGE", label="request " + repr(bad_request),
                            request_override=bad_request, before_read=True)
    assert (actual.selects, actual.records, actual.rollbacks) == original_counts
    # The original P1 shape omission on the SAME real Port: a D without its admission.
    malformed_d = copy.deepcopy(desired)
    del malformed_d["admission"]
    assert_real_refusal("CHANGE", label="desired-without-admission", desired_override=malformed_d)
    assert (actual.selects, actual.records, actual.rollbacks) == original_counts
    # Then the correctly shaped CI-only D through the minimal caller -> sole P2
    # receiver -> identical real OCI/Nix Port.
    effect = call("CHANGE")
    assert effect["stage"] == "SYNTHETIC_READBACK_CANDIDATE_NOT_SUCCESS", effect
    issued = effect["issued_receipt"]
    assert issued is actual._receiver_issued["ci-p3-1"][0]
    assert issued["preimage"] == t1 and issued["selected"] == t0
    assert actual.observe()["store_path"] == t0 and actual.selects == original_counts[0] + 1
    inert(effect)

    previous_confirmed = "CONFIRMED"
    assert_real_refusal("RECORD", label="copied-receipt", expected="REFUSED_PORT_PRECONDITION",
                        prior=previous_confirmed,
                        receipt=copy.deepcopy(issued))
    no_record = call("RECORD", prior=previous_confirmed, receipt=issued,
                     authority_override={"record": False})
    assert no_record["stage"] == "REFUSED_SOURCE_OR_AUTHORITY"
    refusals += 1
    print("REFUSED P3 RECORD no-record-authority: REFUSED_SOURCE_OR_AUTHORITY")
    counts_before_record = (actual.selects, actual.records, actual.rollbacks)
    recorded = call("RECORD", prior=previous_confirmed, receipt=issued,
                    authority_override={"change": False, "quiet": False,
                                        "single_writer": False, "recovery": False})
    assert recorded["stage"] == "SYNTHETIC_RECORD_ONLY_CANDIDATE", recorded
    assert (actual.selects, actual.records, actual.rollbacks) == (
        counts_before_record[0], counts_before_record[1] + 1, counts_before_record[2])
    inert(recorded)
    old = call("RECORD", prior=previous_confirmed, receipt=issued)
    assert old["stage"] == "REFUSED_PORT_PRECONDITION"
    assert actual.records == counts_before_record[1] + 1
    refusals += 1
    print("REFUSED P3 RECORD duplicate-record: REFUSED_PORT_PRECONDITION")
    assert_real_refusal("ROLLBACK", label="copied-receipt", expected="REFUSED_PORT_PRECONDITION",
                        prior=previous_confirmed,
                        receipt=copy.deepcopy(issued))
    denied = call("ROLLBACK", prior=previous_confirmed, receipt=issued,
                  authority_override={"rollback": False})
    assert denied["stage"] == "REFUSED_SOURCE_OR_AUTHORITY"
    refusals += 1
    print("REFUSED P3 ROLLBACK no-rollback-authority: REFUSED_SOURCE_OR_AUTHORITY")
    roll_before = actual.rollbacks
    rolled = call("ROLLBACK", prior=previous_confirmed, receipt=issued,
                  authority_override={"change": False})
    assert rolled["stage"] == "SYNTHETIC_ROLLBACK_READBACK_REQUIRED", rolled
    assert actual.rollbacks == roll_before + 1 and actual.observe()["store_path"] == t1
    inert(rolled)
    duplicate = call("ROLLBACK", prior=previous_confirmed, receipt=issued)
    assert duplicate["stage"] in ("REFUSED_SOURCE_OR_AUTHORITY",
                                  "REFUSED_PORT_PRECONDITION")
    assert actual.rollbacks == roll_before + 1
    refusals += 1
    print("REFUSED P3 ROLLBACK duplicate-rollback: " + duplicate["stage"])

    # The latest separate attempt loses its real Nix-change ACK.
    actual.fail_after_write = True
    before = actual.selects
    lost = call("CHANGE", attempt="ci-p3-2")
    assert lost["stage"] == "SYNTHETIC_EFFECT_UNKNOWN_NO_REPLAY", lost
    assert actual.selects == before + 1 and actual.observe()["store_path"] == t0
    actual.fail_after_write = False
    retry = call("CHANGE", attempt="ci-p3-2")
    assert retry["stage"] in ("REFUSED_SOURCE_OR_AUTHORITY",
                              "SYNTHETIC_EFFECT_UNKNOWN_NO_REPLAY")
    assert actual.selects == before + 1
    refusals += 1
    print("REFUSED P3 CHANGE retry-after-UNKNOWN: " + retry["stage"])
    reread = call("READ", attempt="ci-p3-2", prior="UNKNOWN",
                  desired_override=None)
    assert reread["stage"] == "SYNTHETIC_READ_OBSERVED"
    assert reread["observation"]["store_path"] == t0
    # CI-only teardown: never a receiver/caller recovery attempt.
    docker("exec", container, "/bin/nix-env", "--profile",
           "/nix/var/nix/profiles/rent-dev", "--rollback")
    assert actual.observe()["store_path"] == t1
    assert docker("inspect", "-f", "{{.Image}}", container) == same_image
    assert docker("exec", container, "/bin/bash", "-euc",
                  "sha256sum /var/lib/rent/dev/codex/auth.json "
                  "/var/lib/rent/dev/claude/ci-session-marker "
                  "/work/repos/proof-marker") == original_snapshot
    assert original_snapshot == state_before
    print(f"PASS: CI-only minimal caller -> sole P2 receive_step -> SAME Docker/Nix Port; "
          f"READ/CHANGE/RECORD/ROLLBACK, D from the pinned host-binding with this commit's B/T, "
          f"{refusals} refusals, post-send UNKNOWN no replay, state/image retained")


if __name__ == "__main__":
    proof()
