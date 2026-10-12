"""Exercise the actual two-case failure boundary, not simulated Browser acceptance."""
import ast
import copy
from pathlib import Path
import unittest


class FailureBoundaryTests(unittest.TestCase):
    def run_boundary(self, viewer=None, preview=None, diagnostic=None):
        source = ast.parse(Path(__file__).with_name("browser-host.py").read_text())
        declarations = [n for n in source.body if isinstance(n, ast.AnnAssign)
                        and isinstance(n.target, ast.Name) and n.target.id == "failures"]
        tries = [n for n in source.body if isinstance(n, ast.Try)]
        decisions = [n for n in source.body if isinstance(n, ast.If)
                     and isinstance(n.test, ast.Name) and n.test.id == "failures"]
        self.assertEqual((len(declarations), len(tries), len(decisions)), (1, 2, 1))
        parts = copy.deepcopy(declarations + tries + decisions)
        for part, call in zip(parts[1:3], ("viewer", "preview")):
            # Replace only the external test actions. Retain the real handlers/decision.
            part.body = ast.parse(f'check("{call}")').body
        self.assertIsInstance(parts[1].finalbody[0], ast.Try)
        parts[1].finalbody[0].body = ast.parse('check("diagnostic")').body
        self.visited = []
        failures = {"viewer": viewer, "preview": preview, "diagnostic": diagnostic}

        def check(name):
            self.visited.append(name)
            if failures[name] is not None:
                raise failures[name]

        module = ast.fix_missing_locations(ast.Module(body=parts, type_ignores=[]))
        exec(compile(module, "<actual-failure-boundary>", "exec"), {"check": check})

    def test_both_success(self):
        self.run_boundary()
        self.assertEqual(self.visited, ["viewer", "diagnostic", "preview"])

    def test_viewer_failure_kept_after_preview_runs(self):
        error = AssertionError("viewer-not-redrawn")
        with self.assertRaises(ExceptionGroup) as caught:
            self.run_boundary(viewer=error)
        self.assertEqual(caught.exception.exceptions, (error,))
        self.assertEqual(self.visited, ["viewer", "diagnostic", "preview"])

    def test_preview_failure_kept(self):
        error = RuntimeError("preview-not-reachable")
        with self.assertRaises(ExceptionGroup) as caught:
            self.run_boundary(preview=error)
        self.assertEqual(caught.exception.exceptions, (error,))

    def test_both_failures_kept_once(self):
        first, second = AssertionError("viewer"), RuntimeError("preview")
        with self.assertRaises(ExceptionGroup) as caught:
            self.run_boundary(viewer=first, preview=second)
        self.assertEqual(caught.exception.exceptions, (first, second))
        self.assertEqual(self.visited.count("viewer"), 1)
        self.assertEqual(self.visited.count("preview"), 1)

    def test_interruption_is_not_caught_and_continued(self):
        with self.assertRaises(KeyboardInterrupt):
            self.run_boundary(viewer=KeyboardInterrupt())
        self.assertEqual(self.visited, ["viewer", "diagnostic"])

    def test_diagnostic_failure_does_not_replace_viewer_failure(self):
        first, second = AssertionError("viewer"), RuntimeError("transport-lost")
        with self.assertRaises(ExceptionGroup) as caught:
            self.run_boundary(viewer=first, diagnostic=second)
        self.assertEqual(caught.exception.exceptions, (first, second))
        self.assertEqual(self.visited, ["viewer", "diagnostic", "preview"])


if __name__ == "__main__":
    unittest.main()
