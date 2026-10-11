"""Synthetic tests of the guard, never Host acceptance evidence."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from acceptance import CONTEXT, REQUIRED, evaluate, load, main


class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.context = {key: "a" * size for key, size in CONTEXT.items()}
        self.rows = [{"id": key, "status": "PASS", "scope": "full",
                      "context": copy.deepcopy(self.context),
                      "positive": ["synthetic-positive-" + key],
                      "negative": ["synthetic-negative-" + key]} for key in REQUIRED]

    def rejected(self, rows=None, context=None):
        result = evaluate(self.context if context is None else context,
                          self.rows if rows is None else rows)
        self.assertFalse(result["consistent"])
        return result

    def test_complete_synthetic_shape_only(self):
        result = evaluate(self.context, self.rows)
        self.assertTrue(result["consistent"])
        self.assertEqual(result["scope"], "receipt-consistency-only")
        self.assertNotIn("done", result)
        self.assertEqual(len(result["records"]), 12)

    def test_no_mutation_and_order_independent(self):
        before = copy.deepcopy((self.context, self.rows))
        self.assertEqual(evaluate(self.context, self.rows),
                         evaluate(self.context, list(reversed(self.rows))))
        self.assertEqual((self.context, self.rows), before)

    def test_empty_has_twelve_missing(self):
        result = self.rejected([])
        self.assertEqual([r["reasons"] for r in result["records"]], [["missing"]] * 12)

    def test_each_missing_requirement(self):
        for index in range(12):
            with self.subTest(index=index):
                self.rejected(self.rows[:index] + self.rows[index + 1:])

    def test_duplicate_cannot_last_write_win(self):
        self.rejected(self.rows + [self.rows[0]])
        bad = copy.deepcopy(self.rows[0])
        bad["status"] = "FAIL"
        self.rejected([bad] + self.rows)
        self.rejected(self.rows + [bad])

    def test_unknown_and_nonobject(self):
        for row in (None, [], 1, "PASS", {"id": "E13"}, {"id": []}):
            with self.subTest(row=row):
                self.rejected(self.rows + [row])

    def test_nonlist(self):
        for value in ({}, "PASS", 12, False):
            with self.subTest(value=value):
                self.rejected(value)
        self.assertFalse(evaluate(self.context, None)["consistent"])

    def test_every_nonpass_status(self):
        for status in ("FAIL", "SKIP", "NOT_RUN", "NOT_PROVEN", "PARTIAL", "pass", True, 1, None):
            with self.subTest(status=status):
                rows = copy.deepcopy(self.rows)
                rows[0]["status"] = status
                self.rejected(rows)

    def test_scope_cannot_promote_smoke(self):
        for scope in ("partial", "vm-smoke", "", True, None):
            rows = copy.deepcopy(self.rows)
            rows[0]["scope"] = scope
            self.rejected(rows)

    def test_both_evidence_sides_required(self):
        for side in ("positive", "negative"):
            for value in ([], "PASS", [""], [" "], [None], [1], [{}], ["same", "same"]):
                with self.subTest(side=side, value=value):
                    rows = copy.deepcopy(self.rows)
                    rows[0][side] = value
                    self.rejected(rows)

    def test_missing_receipt_field(self):
        for key in self.rows[0]:
            rows = copy.deepcopy(self.rows)
            del rows[0][key]
            self.rejected(rows)

    def test_extra_receipt_field(self):
        rows = copy.deepcopy(self.rows)
        rows[0]["accepted"] = True
        self.rejected(rows)

    def test_each_context_mismatch(self):
        for key, size in CONTEXT.items():
            rows = copy.deepcopy(self.rows)
            rows[0]["context"][key] = "b" * size
            self.rejected(rows)

    def test_invalid_expected_context(self):
        for value in (None, {}, [], "same"):
            self.assertFalse(evaluate(value, self.rows)["consistent"])
        for key in CONTEXT:
            value = self.context.copy()
            del value[key]
            self.rejected(context=value)
        extra = dict(self.context, extra="unbound")
        self.rejected(context=extra)

    def test_invalid_receipt_context(self):
        for value in (None, {}, [], "same"):
            rows = copy.deepcopy(self.rows)
            rows[0]["context"] = value
            self.rejected(rows)

    def test_hash_shapes(self):
        for key, size in CONTEXT.items():
            for value in ("a" * (size - 1), "a" * (size + 1), "z" * size, "A" * size, None, 0):
                with self.subTest(key=key, value=value):
                    expected = self.context.copy()
                    expected[key] = value
                    self.rejected(context=expected)

    def test_strict_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input"
            for text in ('{"id":"E01","id":"E02"}', '{"a":{"x":1,"x":2}}',
                         'NaN', 'Infinity', '-Infinity', '{', '[] trailing'):
                with self.subTest(text=text):
                    path.write_text(text)
                    with self.assertRaises(ValueError):
                        load(path)

    def test_size_and_encoding_limits(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "input"
            for raw in (b" " * (1024 * 1024 + 1), b"\xff"):
                path.write_bytes(raw)
                with self.assertRaises(ValueError):
                    load(path)

    def test_cli_missing_files_produces_real_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = subprocess.run([sys.executable, str(Path(__file__).with_name("acceptance.py")),
                "--context", str(root / "context"), "--receipts", str(root / "receipts"),
                "--output", str(root / "out")], capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 1, result.stderr)
            self.assertEqual(json.loads(result.stdout)["scope"], "receipt-consistency-only")
            records = load(root / "out/raws.jsonl", lines=True)
            failures = load(root / "out/disruptives.jsonl", lines=True)
            self.assertEqual(records, failures)
            self.assertEqual(len(records), 13)

    def test_cli_synthetic_success_write_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "context").write_text(json.dumps(self.context))
            (root / "receipts").write_text("\n".join(json.dumps(row) for row in self.rows))
            args = ["--context", str(root / "context"), "--receipts", str(root / "receipts"),
                    "--output", str(root / "out")]
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 0)
                before = (root / "out/raws.jsonl").read_bytes()
                self.assertEqual(main(args), 2)
                self.assertEqual((root / "out/raws.jsonl").read_bytes(), before)
            self.assertEqual((root / "out/disruptives.jsonl").read_bytes(), b"")

    def test_invalid_input_is_not_echoed_to_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            secret = "fixture-private-marker-never-echo"
            (root / "context").write_text(json.dumps(self.context))
            (root / "receipts").write_text(secret)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(["--context", str(root / "context"),
                    "--receipts", str(root / "receipts"), "--output", str(root / "out")]), 1)
            self.assertNotIn(secret, (root / "out/raws.jsonl").read_text())


if __name__ == "__main__":
    unittest.main()
