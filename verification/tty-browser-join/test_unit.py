# SPDX-License-Identifier: GPL-3.0-or-later
"""Synthetic predicate/fault tests and local fixture HTTP. Not VM/E2E evidence."""
import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

import evidence as e
import fixture

ROOT = Path(__file__).resolve().parent


class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="c-unit-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.context = {key: str(i) * 64 for i, key in enumerate(("code", "inputs", "environment"), 1)}
        self.artifact = self.root / "synthetic.log"
        self.artifact.write_bytes(b"SYNTHETIC UNIT INPUT, NOT PROOF")
        self.artifacts = [{"path": self.artifact.name, "sha256": hashlib.sha256(self.artifact.read_bytes()).hexdigest()}]
        self.before = {"target": "fixture-target", "field": "editor", "text": "", "browserPid": 7}
        self.rows = [self.record(case, spec) for case, spec in e.catalog()["cases"].items()]

    def record(self, case, spec):
        before = dict(self.before)
        facts = {"before": before, "after": {**before, "text": spec.get("suffix", "")},
            "preeditText": "", "input": "vm-keyboard"}
        kind = spec["kind"]
        if kind in ("reference", "review"):
            facts = {"positive": ["https://example.invalid/unit/positive"], "negative": ["https://example.invalid/unit/negative"]}
            if kind == "review":
                facts.update(writer="synthetic-writer", reviewer="synthetic-reviewer", unresolved=[])
        elif kind == "selection":
            offered = [fixture.candidate("A", "同じ表示"), fixture.candidate("B", "同じ表示")]
            facts = {"offered": offered, "selected": copy.deepcopy(offered[1]), "query": {"generation": 2, "raw": "u"},
                "selectedQuery": {"generation": 2, "raw": "u"}, "effectCount": 1, "capture": "B-original-selection"}
        elif kind == "resize":
            facts.update(sizeBefore=[24, 80], sizeChanged=[30, 90], sizeRestored=[24, 80])
        elif kind == "target-rejection":
            facts.update(attemptedTarget="different-target", refused=True)
        elif kind in ("cleanup", "disconnect", "reconnect"):
            facts.update(termiosBefore="a:b:c", termiosAfter="a:b:c", profileBefore="marker", profileAfter="marker", exitCode=0)
            if kind == "disconnect":
                facts.update(fault="tcp-disconnect", closedSockets="synthetic-unit-socket", exitCode=1)
            if kind == "reconnect":
                facts["viewerPids"] = [10, 20]
        row = {"case": case, "status": "PASS", "scope": spec["scope"], "context": dict(self.context),
            "facts": facts, "artifacts": [{"path": "capture-" + case + ".json", "sha256": "0" * 64}] + copy.deepcopy(self.artifacts)}
        self.capture(row)
        return row

    def capture(self, row):
        capture = {key: value for key, value in row.items() if key != "artifacts"}
        path = self.root / ("capture-" + row["case"] + ".json")
        path.write_text(json.dumps(capture, ensure_ascii=False))
        for item in row["artifacts"]:
            if item["path"] == path.name:
                item["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()

    def report(self, rows=None):
        rows = self.rows if rows is None else rows
        # Keep synthetic captures consistent, so semantic counterexamples test
        # predicates rather than merely detecting stale fixture hashes.
        for row in rows:
            if type(row) is dict and row.get("case") in e.catalog()["cases"]:
                self.capture(row)
        return e.assess(self.context, rows, self.root)

    def case(self, name):
        return next(row for row in self.rows if row["case"] == name)

    def test_complete_synthetic_data_is_consistent_not_admission(self):
        report = self.report()
        self.assertTrue(report["consistent"], report)
        self.assertEqual(report["gate"], "C_EVIDENCE_CONSISTENCY_ONLY")
        self.assertEqual(report["admission"], "NOT_PERFORMED")
        self.assertEqual(report["upstreamAgreement"], "NOT_INFERRED")

    def test_missing_any_one_case_is_rejected(self):
        for i, row in enumerate(self.rows):
            with self.subTest(case=row["case"]):
                self.assertFalse(self.report(self.rows[:i] + self.rows[i+1:])["consistent"])

    def test_duplicate_case_is_rejected(self):
        self.assertFalse(self.report(self.rows + [self.rows[0]])["consistent"])

    def test_missing_all_preserves_all_C_obligations(self):
        report = self.report([])
        self.assertEqual(len(report["criteria"]), 7)
        self.assertTrue(all(row["status"] == "NOT_PROVEN" for row in report["criteria"]))

    def test_skip_failure_or_partial_does_not_become_pass(self):
        for value in ("SKIP", "FAIL", "NOT_RUN", "PARTIAL", True):
            with self.subTest(value=value):
                rows = copy.deepcopy(self.rows); rows[0]["status"] = value
                self.assertFalse(self.report(rows)["consistent"])

    def test_ordinary_smoke_is_not_full_closure(self):
        self.assertFalse(self.report([self.case("ordinary")])["consistent"])

    def test_mismatched_code_inputs_or_environment_is_rejected(self):
        for key in self.context:
            with self.subTest(key=key):
                rows = copy.deepcopy(self.rows); rows[0]["context"][key] = "f" * 64
                self.assertFalse(self.report(rows)["consistent"])

    def test_expected_context_is_not_inferred_from_receipts(self):
        self.assertFalse(e.assess(None, self.rows, self.root)["consistent"])

    def test_fixture_or_vm_does_not_prove_real_provider_physical_or_review(self):
        for name in ("real-provider", "physical", "review"):
            with self.subTest(case=name):
                rows = copy.deepcopy(self.rows)
                next(r for r in rows if r["case"] == name)["scope"] = "vm"
                self.assertFalse(self.report(rows)["consistent"])

    def test_self_review_is_not_independent(self):
        self.case("review")["facts"]["reviewer"] = "synthetic-writer"
        self.assertFalse(self.report()["consistent"])

    def test_unresolved_review_blocks_consistency(self):
        self.case("review")["facts"]["unresolved"] = ["input identity missing"]
        self.assertFalse(self.report()["consistent"])

    def test_display_text_cannot_replace_original_id(self):
        facts = self.case("typed-id")["facts"]
        facts["selected"]["id"] = "display-inferred"
        self.assertFalse(self.report()["consistent"])

    def test_typed_meaning_and_evidence_must_survive_unchanged(self):
        for key in ("meaning", "evidence"):
            with self.subTest(key=key):
                rows = copy.deepcopy(self.rows)
                row = next(r for r in rows if r["case"] == "typed-id")
                row["facts"]["selected"][key] = "flattened"
                self.assertFalse(self.report(rows)["consistent"])

    def test_generation_and_raw_are_not_reconstructed_from_display(self):
        for key, value in (("raw", "different"), ("generation", 1)):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r["case"] == "typed-id")["facts"]["selectedQuery"][key] = value
            self.assertFalse(self.report(rows)["consistent"])

    def test_duplicate_effect_and_boolean_counter_are_rejected(self):
        for count in (0, 2, True):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r["case"] == "typed-id")["facts"]["effectCount"] = count
            self.assertFalse(self.report(rows)["consistent"])

    def test_boolean_and_integer_are_distinct_in_typed_payloads(self):
        facts = self.case("typed-id")["facts"]
        facts["offered"][1]["meaning"]["value"] = 1
        facts["selected"]["meaning"]["value"] = True
        self.assertFalse(self.report()["consistent"])

    def test_selected_generation_boolean_is_not_integer_one(self):
        facts = self.case("typed-id")["facts"]
        facts["query"]["generation"] = 1
        facts["selectedQuery"]["generation"] = True
        self.assertFalse(self.report()["consistent"])

    def test_facts_predicates_reject_absent_or_wrong_types_directly(self):
        for spec in e.catalog()["cases"].values():
            for value in (None, [], {}, "PASS", True):
                self.assertFalse(e.facts_valid(spec, value))

    def test_malformed_or_overlarge_record_collection_is_rejected(self):
        for value in (None, {}, True, [None] * 129):
            self.assertFalse(e.assess(self.context, value, self.root)["consistent"])

    def test_input_size_limit_applies_before_json_parsing(self):
        path = self.root / "large.json"
        path.write_bytes(b" " * (e.LIMIT + 1))
        with self.assertRaises(ValueError): e.read_json(path)

    def test_wrong_target_field_text_or_browser_lifetime_is_rejected(self):
        for key, value in (("target", "other"), ("field", "password"), ("text", "wrong"), ("browserPid", 9)):
            rows = copy.deepcopy(self.rows); rows[0]["facts"]["after"][key] = value
            self.assertFalse(self.report(rows)["consistent"])

    def test_preedit_leak_is_not_successful_confirmation(self):
        self.case("ordinary")["facts"]["preeditText"] = "日本語"
        self.assertFalse(self.report()["consistent"])

    def test_click_or_insertText_is_not_keyboard_input(self):
        self.case("ordinary")["facts"]["input"] = "Input.insertText"
        self.assertFalse(self.report()["consistent"])

    def test_resize_requires_actual_change_and_restoration(self):
        self.case("resize")["facts"]["sizeChanged"] = [24, 80]
        self.assertFalse(self.report()["consistent"])

    def test_terminal_and_profile_restoration_are_separate_checks(self):
        for key in ("termiosAfter", "profileAfter"):
            rows = copy.deepcopy(self.rows)
            next(r for r in rows if r["case"] == "cleanup")["facts"][key] = "changed"
            self.assertFalse(self.report(rows)["consistent"])

    def test_same_pid_is_not_viewer_reconnect(self):
        self.case("reconnect")["facts"]["viewerPids"] = [10, 10]
        self.assertFalse(self.report()["consistent"])

    def test_normal_quit_is_not_connection_loss(self):
        self.case("disconnect")["facts"].update(fault="ctrl-q", exitCode=0)
        self.assertFalse(self.report()["consistent"])

    def test_unknown_or_extra_fields_are_rejected(self):
        for mutation in ({"case": "unknown"}, {"accepted": True}):
            rows = copy.deepcopy(self.rows); rows[0].update(mutation)
            self.assertFalse(self.report(rows)["consistent"])

    def test_no_empty_negative_evidence(self):
        self.case("supplier-A")["facts"]["negative"] = []
        self.assertFalse(self.report()["consistent"])

    def test_missing_changed_empty_or_duplicate_artifact_is_rejected(self):
        for value in (b"changed", b""):
            self.artifact.write_bytes(value)
            self.assertFalse(self.report()["consistent"])
        self.artifact.unlink()
        self.assertFalse(self.report()["consistent"])

    def test_artifact_traversal_and_symlinks_are_rejected(self):
        for path in ("../escape", "/etc/passwd", "dir/../../escape", r"..\escape", "."):
            rows = copy.deepcopy(self.rows); rows[0]["artifacts"][0]["path"] = path
            self.assertFalse(self.report(rows)["consistent"])
        (self.root / "link.log").symlink_to(self.artifact)
        self.rows[0]["artifacts"][0]["path"] = "link.log"
        self.assertFalse(self.report()["consistent"])

    def test_receipt_cannot_point_at_unrelated_or_old_capture(self):
        self.rows[0]["facts"]["after"]["text"] = "forged"
        self.assertFalse(e.assess(self.context, self.rows, self.root)["consistent"])
        self.assertIn("missing-or-mismatched-capture", e.assess(self.context, self.rows, self.root)["cases"][0]["reasons"])

    def test_capture_comparison_preserves_nested_json_types(self):
        self.rows[0]["facts"]["measurement"] = 1
        self.capture(self.rows[0])
        self.rows[0]["facts"]["measurement"] = True
        report = e.assess(self.context, self.rows, self.root)
        self.assertIn("missing-or-mismatched-capture", report["cases"][0]["reasons"])

    def test_named_pipe_is_not_a_regular_evidence_file(self):
        import os
        path = self.root / "pipe.json"
        os.mkfifo(path)
        with self.assertRaises(ValueError): e.read_json(path)
        rows = copy.deepcopy(self.rows)
        rows[0]["artifacts"].append({"path": path.name, "sha256": "0" * 64})
        self.assertFalse(self.report(rows)["consistent"])

    def test_duplicate_json_and_nonfinite_are_rejected(self):
        for text in ('{"case":"a","case":"b"}', '{"x":NaN}', '{"x":Infinity}'):
            with self.assertRaises(ValueError): e.decode(text)

    def test_unreadable_cli_emits_failure_without_echoing_inputs(self):
        result = subprocess.run([sys.executable, str(ROOT / "evidence.py"), "--root", str(self.root),
            "--expected", str(self.root / "secret-context"), "--records", str(self.root / "secret-records")],
            capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 1)
        report = json.loads(result.stdout)
        self.assertFalse(report["consistent"])
        self.assertNotIn("secret", result.stdout)

    def test_does_not_mutate_evidence(self):
        before = copy.deepcopy(self.rows); self.report()
        self.assertEqual(self.rows, before)

    def test_all_legacy_requirements_have_explicit_remaining_owner(self):
        rules = e.catalog()
        self.assertEqual(len(rules["legacy"]), 12)
        self.assertTrue(all(value["HostRemainder"] for value in rules["legacy"].values()))


class FixtureTests(unittest.TestCase):
    def test_response_variants_are_distinct_faults(self):
        query = {"raw": "u", "generation": 2}
        for mode in fixture.MODES:
            with self.subTest(mode=mode):
                body = fixture.payload(query, mode)
                if mode == "invalid-json":
                    with self.assertRaises(ValueError): json.loads(body)
                    continue
                result = json.loads(body)
                self.assertEqual(result["generation"], 2)
                self.assertNotEqual(result["raw"], "u") if mode == "wrong-raw" else self.assertEqual(result["raw"], "u")
        self.assertEqual(json.loads(fixture.payload(query, "action"))["proposals"][0]["meaning"]["kind"], "action")
        self.assertEqual(json.loads(fixture.payload(query, "stale"))["proposals"][0]["representation"], "旧候補")
        self.assertEqual(json.loads(fixture.payload({**query, "raw": "ux"}, "stale"))["proposals"][0]["representation"], "新候補")

    def test_delayed_reply_needs_test_release_not_a_sleep_assumption(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory); (state / "mode").write_text("stale")
            instance = fixture.server(state)
            serving = threading.Thread(target=instance.serve_forever, daemon=True); serving.start()
            result = []
            def request():
                req = urllib.request.Request(f"http://127.0.0.1:{instance.server_port}/proposal",
                    data=json.dumps({"raw": "u", "generation": 1}).encode())
                with urllib.request.urlopen(req, timeout=3) as response: result.append(json.load(response))
            caller = threading.Thread(target=request, daemon=True); caller.start()
            try:
                import time
                deadline = time.monotonic() + 1
                while not (state / "held").exists() and time.monotonic() < deadline: time.sleep(.005)
                self.assertTrue((state / "held").exists())
                self.assertEqual(result, [])
                (state / "release").touch(); caller.join(2)
                self.assertEqual(result[0]["proposals"][0]["representation"], "旧候補")
            finally:
                (state / "release").touch(); caller.join(2)
                instance.shutdown(); instance.server_close(); serving.join(2)

    def test_bad_query_is_not_accepted(self):
        for query in ({}, [], {"raw": "u", "generation": True}, {"raw": "", "generation": 1}):
            with self.assertRaises(ValueError): fixture.payload(query, "typed")

    def test_real_loopback_http_is_fixture_only(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory); (state / "mode").write_text("typed")
            instance = fixture.server(state)
            thread = threading.Thread(target=instance.serve_forever, daemon=True); thread.start()
            try:
                query = {"raw": "u", "generation": 1}
                request = urllib.request.Request(f"http://127.0.0.1:{instance.server_port}/proposal",
                    data=json.dumps(query).encode(), headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=2) as response:
                    result = json.load(response)
                self.assertEqual(result["proposals"][1]["id"], "typed-B")
                self.assertEqual(json.loads((state / "requests.jsonl").read_text())["query"], query)
                self.assertEqual(len((state / "responses.jsonl").read_text().splitlines()), 1)
            finally:
                instance.shutdown(); instance.server_close(); thread.join(2)


if __name__ == "__main__":
    unittest.main()
