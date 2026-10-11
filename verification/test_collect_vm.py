"""Synthetic partial log tests, not Host product acceptance."""
import json
import tempfile
import unittest
from pathlib import Path
from collect_vm import collect, main

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

if __name__ == "__main__":
    unittest.main()
