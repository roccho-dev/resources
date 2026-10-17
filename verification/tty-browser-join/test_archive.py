# SPDX-License-Identifier: GPL-3.0-or-later
"""Saved-artifact regression fixtures; not VM or product acceptance evidence."""
import hashlib
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import evidence as e
from archive import verify_saved, verify_context
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
        pins = e.read_json(Path(__file__).with_name("pins.json"))
        observed = {"pins": {name: {"rev": pin["rev"], "narHash": pin["narHash"],
            "drvPath": "/nix/store/unit-" + name + ".drv", "outputPath": "/nix/store/unit-" + name}
            for name, pin in pins.items()}, "meta": {"code": self.context["code"], "system": "x86_64-linux"}}
        observed["executables"] = "".join("a" * 64 + "  /nix/store/unit-" + name + "/bin/" + exe + "\n"
            for name, exe in (("A", "cdp-tty"), ("B", "meltype-tty"), ("terminal", "bcon")))
        environment = {"meta": observed["meta"], "kernel": "Linux synthetic-unit\n", "system": "unit-only\n"}
        self.context.update(inputs=e.digest({"pins": observed["pins"], "executables": observed["executables"]}),
            environment=e.digest(environment))
        for row in rows:
            row["context"] = self.context
            capture = self.root / ("capture-" + row["case"] + ".json")
            capture.write_text(json.dumps({k: v for k, v in row.items() if k != "artifacts"}))
            for ref in row["artifacts"]:
                if ref["path"] == capture.name:
                    ref["sha256"] = hashlib.sha256(capture.read_bytes()).hexdigest()
        (self.root / "raws.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
        (self.root / "context.json").write_text(json.dumps(self.context))
        (self.root / "assessment.json").write_text(json.dumps(e.assess(self.context, rows, self.root)))
        (self.root / "inputs.json").write_text(json.dumps(observed))
        (self.root / "environment.json").write_text(json.dumps(environment))
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

    def test_raw_environment_recomputes_without_acceptance(self):
        report = verify_saved(self.saved_fixture(), self.root)["material"]
        self.assertTrue(report["contextRecomputed"])
        self.assertEqual(report["physicalEquivalence"], "NOT_PROVEN")
        self.assertEqual(report["supplierAgreement"], "NOT_INFERRED")

    def test_wrong_kernel_or_environment_is_not_rebound(self):
        root = self.saved_fixture()
        env = e.read_json(root / "environment.json")
        env["kernel"] = "Linux different-unit\n"
        (root / "environment.json").write_text(json.dumps(env))
        with self.assertRaisesRegex(ValueError, "saved-context-not-reproducible"):
            verify_context(root, e.read_json(Path(__file__).with_name("pins.json")))

    def test_missing_environment_is_rejected(self):
        root = self.saved_fixture()
        (root / "environment.json").unlink()
        with self.assertRaisesRegex(ValueError, "saved-run-file-mismatch"):
            verify_saved(root, self.root)

    def test_wrong_source_pin_or_nar_is_rejected(self):
        root = self.saved_fixture()
        pins = e.read_json(Path(__file__).with_name("pins.json"))
        for name in ("A", "B", "terminal"):
            for key, value in (("rev", "0" * 40), ("narHash", "sha256-" + "A" * 43 + "=")):
                with self.subTest(name=name, key=key):
                    bad = copy.deepcopy(pins)
                    bad[name][key] = value
                    with self.assertRaisesRegex(ValueError, "saved-supplier-identity-mismatch"):
                        verify_context(root, bad)

    def test_valid_rehash_does_not_hide_wrong_binary_path(self):
        root = self.saved_fixture()
        observed = e.read_json(root / "inputs.json")
        observed["executables"] = observed["executables"].replace("/unit-A/", "/foreign-A/")
        # actual paths include store prefix; change the output's identity.
        observed["executables"] = observed["executables"].replace("store/unit-A/", "store/foreign-A/")
        context = e.read_json(root / "context.json")
        context["inputs"] = e.digest({"pins": observed["pins"], "executables": observed["executables"]})
        (root / "inputs.json").write_text(json.dumps(observed))
        (root / "context.json").write_text(json.dumps(context))
        with self.assertRaisesRegex(ValueError, "saved-executable-output-mismatch"):
            verify_context(root, e.read_json(Path(__file__).with_name("pins.json")))

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
        for name in ("context.json", "raws.jsonl", "assessment.json", "inputs.json", "environment.json"):
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
