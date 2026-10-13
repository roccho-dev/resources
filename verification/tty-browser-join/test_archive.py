# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved-artifact regression fixtures; not VM or product acceptance evidence."""
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import evidence as e
from archive import verify_saved
import test_unit


class SavedEvidenceTests(unittest.TestCase):
    def setUp(self):
        fixture = test_unit.EvidenceTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root, self.rows, self.context = fixture.root, fixture.rows, fixture.context
        self.case = fixture.case

    def saved_fixture(self):
        rows = [r for r in self.rows if r["scope"] == "vm"]
        selection = self.root / "B-original-selection.jsonl"
        selection.write_bytes(b'{"SYNTHETIC_UNIT_ONLY":true}\n')
        self.case("typed-id")["artifacts"].append({"path": selection.name,
            "sha256": hashlib.sha256(selection.read_bytes()).hexdigest()})
        (self.root / "raws.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (self.root / "context.json").write_text(json.dumps(self.context))
        (self.root / "assessment.json").write_text(json.dumps(e.assess(self.context, rows, self.root)))
        (self.root / "inputs.json").write_text('{"SYNTHETIC_UNIT_ONLY":true}')
        saved = tempfile.TemporaryDirectory(prefix="c-saved-unit-")
        self.addCleanup(saved.cleanup)
        root = Path(saved.name)
        shutil.copytree(self.root, root, dirs_exist_ok=True)
        return root

    def test_saved_vm_receipts_keep_external_obligations(self):
        report = verify_saved(self.saved_fixture(), self.root)
        self.assertEqual(report["vmCases"], 16)
        self.assertEqual(len(report["missingAcceptance"]), 9)
        self.assertEqual(report["admission"], "NOT_PERFORMED")
        self.assertEqual(report["upstreamAgreement"], "NOT_INFERRED")

    def test_saved_original_selection_is_required_even_with_capture(self):
        saved = self.saved_fixture()
        (saved / "B-original-selection.jsonl").unlink()
        with self.assertRaisesRegex(ValueError, "saved-evidence-invalid"):
            verify_saved(saved, self.root)

    def test_saved_corrupted_original_selection_is_rejected(self):
        saved = self.saved_fixture()
        (saved / "B-original-selection.jsonl").write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, "saved-evidence-invalid"):
            verify_saved(saved, self.root)

    def test_saved_receipt_or_context_cannot_be_rebound(self):
        saved = self.saved_fixture()
        for name in ("context.json", "raws.jsonl", "assessment.json", "inputs.json"):
            with self.subTest(name=name):
                file = saved / name
                original = file.read_bytes()
                file.write_bytes(original + b' ')
                with self.assertRaisesRegex(ValueError, "saved-run-file-mismatch"):
                    verify_saved(saved, self.root)
                file.write_bytes(original)

    def test_saved_same_bytes_via_symlink_are_rejected(self):
        saved = self.saved_fixture()
        (saved / "raws.jsonl").unlink()
        (saved / "raws.jsonl").symlink_to(self.root / "raws.jsonl")
        with self.assertRaisesRegex(ValueError, "saved-run-file-mismatch"):
            verify_saved(saved, self.root)


if __name__ == "__main__":
    unittest.main()
