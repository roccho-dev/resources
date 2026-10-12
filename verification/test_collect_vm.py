"""Synthetic partial log tests, not Host product acceptance."""
import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from collect_vm import collect, main, observed

SHA = "a" * 40

def line(name, **fields):
    item = {"test": name, "status": "PASS", "preapply": "NOT_PROVEN", "scope": "vm partial"}
    item.update(fields)
    return "browser-host-session> " + json.dumps(item) + "\n"


class CollectorTests(unittest.TestCase):
    def test_empty_is_not_proof(self):
        rows, gaps = collect(b"", SHA, "success")
        self.assertEqual(len(rows), 12)
        self.assertEqual(len(gaps), 12)
        self.assertTrue(all(x["status"] == x["full_acceptance"] == "NOT_PROVEN" for x in rows))

    def test_known_subset_is_still_not_full(self):
        raw = (line("vm-session-smoke") + line("real-bcon-wheel") +
               line("viewer-ctrl-q-outcome", exit="0", stderr="") +
               line("viewer-failed-attach-negative-control", exit="1",
                    stderr="connection, terminal or frame rejected") +
               line("real-bcon-viewer") + line("remote-localhost-preview")).encode()
        rows, _ = collect(raw, SHA, "success")
        self.assertEqual([r["id"] for r in rows if r["status"] == "PARTIAL_OBSERVED"],
                         ["E01", "E02", "E03", "E04", "E07", "E08"])
        self.assertTrue(all(r["full_acceptance"] == "NOT_PROVEN" and
                            r["hardware_apply"] == "NOT_PROVEN" for r in rows))

    def test_previous_partial_survives_later_vm_failure(self):
        rows, _ = collect(line("vm-session-smoke").encode(), SHA, "failure")
        self.assertEqual([r["id"] for r in rows if r["status"] == "PARTIAL_OBSERVED"], ["E01", "E04"])
        self.assertTrue(all(r["vm_outcome"] == "failure" for r in rows))

    def test_duplicate_and_failed_observation(self):
        raw = (line("vm-session-smoke") + line("vm-session-smoke") +
               line("real-bcon-wheel", status="FAIL") + line("real-bcon-viewer")).encode()
        rows, _ = collect(raw, SHA, "success")
        self.assertEqual(rows[0]["status"], "NOT_PROVEN")
        self.assertEqual(rows[1]["status"], "NOT_PROVEN")

    def test_bad_ctrl_q_and_early_exit_cannot_pass(self):
        raw = (line("viewer-ctrl-q-outcome", exit="1", stderr="failure") +
               line("viewer-failed-attach-negative-control", exit="1",
                    stderr="connection, terminal or frame rejected") +
               line("real-bcon-viewer")).encode()
        rows, _ = collect(raw, SHA, "success")
        self.assertEqual(rows[6]["status"], "NOT_PROVEN")

    def test_untrusted_noise_is_not_accepted_or_echoed(self):
        raw = b'malformed {"test": nan\nsecret-xyz\n' + line("vm-session-smoke").encode()
        rows, _ = collect(raw, SHA, "success")
        self.assertEqual(rows[0]["status"], "PARTIAL_OBSERVED")
        self.assertNotIn("secret-xyz", json.dumps(rows))

    def test_source_and_outcome_boundaries(self):
        for bad in ("", "a"*39, "z"*40, "A"*40):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                collect(b"", bad, "success")
        with self.assertRaises(ValueError):
            collect(b"", SHA, "PASS")

    def test_missing_log_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = ["--log", str(root/"missing"), "--source-sha", SHA,
                    "--vm-outcome", "failure", "--output", str(root/"out")]
            self.assertEqual(main(args), 2)
            self.assertFalse((root/"out").exists())

    def test_report_is_written_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/"log").write_text(line("vm-session-smoke"))
            args = ["--log", str(root/"log"), "--source-sha", SHA,
                    "--vm-outcome", "failure", "--output", str(root/"out")]
            self.assertEqual(main(args), 0)
            before = (root/"out"/"raws.jsonl").read_bytes()
            self.assertEqual(len(before.splitlines()), 12)
            self.assertEqual(main(args), 2)
            self.assertEqual((root/"out"/"raws.jsonl").read_bytes(), before)

    def no_observations(self, raw, outcome="success"):
        rows, gaps = collect(raw, SHA, outcome)
        self.assertTrue(all(r["status"] == "NOT_PROVEN" for r in rows))
        self.assertEqual(rows, gaps)
        return rows

    def test_echo_and_timestamped_logs_are_not_the_raw_nix_log(self):
        record = line("vm-session-smoke").split("> ", 1)[1].strip()
        for prefix in ("echo ", "guest # ", "2026-10-12T01:00:00Z ", "> "):
            with self.subTest(prefix=prefix):
                self.no_observations((prefix + record).encode())

    def test_supported_raw_nix_envelopes(self):
        record = line("vm-session-smoke").split("> ", 1)[1].strip()
        for prefix in ("", " ", "browser-host-session> ", "vm-test-run-browser-host-session> "):
            with self.subTest(prefix=prefix):
                rows, _ = collect((prefix + record + "  \n").encode(), SHA, "success")
                self.assertEqual(rows[0]["status"], "PARTIAL_OBSERVED")

    def test_json_key_order_is_not_a_gate(self):
        event = {"scope": "vm partial", "preapply": "NOT_PROVEN", "status": "PASS", "test": "vm-session-smoke"}
        rows, _ = collect(json.dumps(event).encode(), SHA, "success")
        self.assertEqual(rows[0]["status"], "PARTIAL_OBSERVED")

    def test_unknown_or_unexecuted_outcome_cannot_reuse_log(self):
        for outcome in ("skipped", "cancelled", "unknown"):
            with self.subTest(outcome=outcome):
                self.no_observations(line("vm-session-smoke").encode(), outcome)

    def test_duplicate_json_keys_do_not_erase_failure(self):
        record = line("vm-session-smoke").replace('"status": "PASS"', '"status": "FAIL", "status": "PASS"')
        self.no_observations(record.encode())

    def test_corruption_does_not_hide_after_good_record(self):
        valid = line("vm-session-smoke").encode()
        for suffix in (b'{"test":"vm-session-smoke"', b'{"test": []}', b'{"test": null}', b'{"test": {}}'):
            with self.subTest(suffix=suffix):
                self.no_observations(valid + suffix)

    def test_trailing_garbage_is_not_a_record(self):
        valid = line("vm-session-smoke").strip()
        for suffix in (" trailing", " {}", "[]", " NaN"):
            with self.subTest(suffix=suffix):
                self.no_observations((valid + suffix).encode())

    def test_invalid_utf8_is_not_replaced_with_success(self):
        self.no_observations(line("vm-session-smoke").encode() + b"\xff")

    def test_non_json_numbers_are_rejected(self):
        for number in ("NaN", "Infinity", "-Infinity"):
            raw = line("vm-session-smoke").rstrip().removesuffix("}") + ', "n": ' + number + '}\n'
            with self.subTest(number=number):
                self.no_observations(raw.encode())

    def test_blank_scope_cannot_pass(self):
        for scope in ("", " ", "\t", None, [], {}, True):
            with self.subTest(scope=scope):
                self.no_observations(line("vm-session-smoke", scope=scope).encode())

    def test_terminal_record_cannot_override_explicit_failure(self):
        for name, fields in (("viewer-ctrl-q-outcome", {"exit": "0", "stderr": ""}),
                             ("viewer-failed-attach-negative-control", {"exit": "1", "stderr": "connection, terminal or frame rejected"})):
            with self.subTest(name=name):
                self.assertFalse(observed({"test": name, "status": "FAIL", **fields}))
                self.assertTrue(observed({"test": name, **fields}))

    def test_observed_rejects_wrong_id_types(self):
        for key in (None, [], {}, True, 1):
            with self.subTest(key=key):
                self.assertFalse(observed({"test": key}))

    def test_nested_evidence_is_not_an_observation(self):
        raw = json.dumps({"diagnostic": json.loads(line("vm-session-smoke").split("> ", 1)[1])})
        self.no_observations(raw.encode())

    def test_oversized_log_rejected_by_pure_function(self):
        with self.assertRaises(ValueError):
            collect(b" " * (10 * 1024 * 1024 + 1), SHA, "success")

    def test_unknown_test_is_not_a_known_case(self):
        self.no_observations(line("new-unaccepted-test").encode())

    def test_repeated_records_never_last_write_win(self):
        raw = (line("vm-session-smoke") * 1000).encode()
        self.no_observations(raw)

    def test_bad_source_types_are_value_errors(self):
        for source in (None, [], {}, True, 1):
            with self.subTest(source=source), self.assertRaises(ValueError):
                collect(b"", source, "success")

    def test_rejection_is_retained_without_input_contents(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "private-marker-do-not-echo"
            (root / "log").write_text(line("vm-session-smoke").strip() + " " + secret)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                result = main(["--log", str(root / "log"), "--source-sha", SHA,
                               "--vm-outcome", "success", "--output", str(root / "out")])
            self.assertEqual(result, 2)
            report = (root / "out/raws.jsonl").read_text()
            self.assertNotIn(secret, report + out.getvalue())
            rows = [json.loads(r) for r in report.splitlines()]
            self.assertEqual(len(rows), 12)
            self.assertTrue(all(r["status"] == "NOT_PROVEN" for r in rows))

    def test_read_is_bounded_before_allocation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calls = []
            class Input(io.BytesIO):
                def read(self, size=-1):
                    calls.append(size)
                    return super().read(size)
            with patch.object(Path, "open", return_value=Input(b"")):
                # Stop before output writing; only the input read is under test.
                with patch.object(Path, "mkdir", side_effect=OSError()):
                    main(["--log", str(root / "log"), "--source-sha", SHA,
                          "--vm-outcome", "failure", "--output", str(root / "out")])
            self.assertEqual(calls, [10 * 1024 * 1024 + 1])

    def test_exception_does_not_expose_paths(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output), patch.object(Path, "open", side_effect=OSError("private-path-marker")):
            self.assertEqual(main(["--log", "private-path-marker", "--source-sha", SHA,
                                   "--vm-outcome", "failure", "--output", "never-created"]), 2)
        self.assertNotIn("private-path-marker", output.getvalue())


if __name__ == "__main__":
    unittest.main()
