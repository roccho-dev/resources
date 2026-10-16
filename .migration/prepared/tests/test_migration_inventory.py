import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import migration_inventory as sut


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.source = dict(kind="source", repository="owner/repo", branch="proposals",
                           commit="a" * 40, plan="https://example.invalid/plan", purpose="test")
        self.route = dict(kind="route", match="src/", destination="resources:src/", owner="fixture", wait=[])
        self.gap = dict(kind="gap", scope="consumers", status="UNVERIFIED", owner="fixture", reason="not observed")
        self.rows = [self.source, self.route, self.gap]
        self.entry = dict(path="src/a.py", mode="100644", blob="b" * 40)
        self.plan = self.root / "plan.jsonl"

    def load(self, rows=None):
        self.plan.write_text("".join(json.dumps(r) + "\n" for r in (self.rows if rows is None else rows)))
        return sut.load_plan(self.plan)

    def inventory(self, entries=None, head=None):
        return sut.inventory(*self.load(), [self.entry] if entries is None else entries, head or self.source["commit"])

    def test_valid_plan_and_false_completion(self):
        result = self.inventory()
        self.assertEqual(result[1]["destination_candidate"], "resources:src/a.py")
        self.assertEqual(result[1]["status"], "UNMIGRATED")
        self.assertFalse(result[-1]["migration_complete"])
        self.assertIn(self.gap, result)

    def test_missing_and_duplicate_source(self):
        for rows in (self.rows[1:], self.rows + [self.source]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.load(rows)

    def test_no_routes_or_gaps(self):
        for rows in ([self.source, self.gap], [self.source, self.route]):
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                self.load(rows)

    def test_duplicate_json_key(self):
        self.plan.write_text('{"kind":"source","kind":"route"}\n')
        with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
            sut.load_plan(self.plan)

    def test_unknown_record_or_field(self):
        for row in ({"kind": "accepted"}, {**self.route, "accepted": True}, []):
            with self.subTest(row=row), self.assertRaises(ValueError):
                self.load(self.rows + [row])

    def test_invalid_source_metadata(self):
        for field, value in (("commit", "latest"), ("repository", "owner/repo\nx=y"), ("branch", "--help")):
            rows = copy.deepcopy(self.rows)
            rows[0][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(rows)

    def test_duplicate_route(self):
        with self.assertRaisesRegex(ValueError, "duplicate route"):
            self.load(self.rows + [self.route])

    def test_unsafe_route(self):
        for match in ("../", "/src/", "src//", "src/./", "src/\n"):
            rows = copy.deepcopy(self.rows)
            rows[1]["match"] = match
            with self.subTest(match=match), self.assertRaises(ValueError):
                self.load(rows)

    def test_wait_and_owner_required(self):
        for field, value in (("wait", "done"), ("wait", [1]), ("owner", "")):
            rows = copy.deepcopy(self.rows)
            rows[1][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(rows)

    def test_cannot_accept_or_duplicate_gap(self):
        with self.assertRaises(ValueError):
            self.load(self.rows + [self.gap])
        self.gap["status"] = "PASS"
        with self.assertRaisesRegex(ValueError, "cannot accept"):
            self.load()

    def test_most_specific_rule_not_order(self):
        self.rows.append({**self.route, "match": "src/bindings/", "destination": "envs:unresolved/"})
        entry = {**self.entry, "path": "src/bindings/site.json"}
        self.assertEqual(self.inventory([entry])[1]["destination_candidate"], "envs:unresolved/site.json")
        self.rows.reverse()
        self.assertEqual(self.inventory([entry])[1]["destination_candidate"], "envs:unresolved/site.json")

    def test_unknown_or_duplicate_paths(self):
        for entries in ([{**self.entry, "path": "other/file"}], [self.entry, self.entry], []):
            with self.subTest(entries=entries), self.assertRaises(ValueError):
                self.inventory(entries)

    def test_stale_pin_refused(self):
        with self.assertRaisesRegex(ValueError, "STALE"):
            self.inventory(head="c" * 40)

    def test_tree_modes_and_names(self):
        raw = ("120000 blob " + "b" * 40 + "\tsrc/名前 with\nnewline\0").encode()
        self.assertEqual(sut.parse_tree(raw)[0]["mode"], "120000")
        self.assertIn("\n", sut.parse_tree(raw)[0]["path"])

    def test_bad_tree_submodule_and_truncation(self):
        good = ("100644 blob " + "b" * 40 + "\tsrc/a\0").encode()
        for raw in (b"", good[:-1], good + good, good.replace(b"100644 blob", b"160000 commit")):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                sut.parse_tree(raw)

    def test_workflow_count_is_derived(self):
        self.rows.append({**self.route, "match": ".github/workflows/", "destination": "resources:.github/workflows/"})
        result = self.inventory([self.entry, {**self.entry, "path": ".github/workflows/new.yml"}])
        self.assertEqual(result[-1]["workflows"], 1)
        self.assertEqual(result[-1]["paths"], 2)

    def test_metadata_cli_uses_validated_source(self):
        self.load()
        result = subprocess.run([sys.executable, str(Path(sut.__file__).resolve()), "metadata", str(self.plan)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "repository=owner/repo\ncommit=" + "a" * 40 + "\nbranch=proposals\n")

    def test_real_git_cli_and_no_overwrite(self):
        repo = self.root / "repo"
        repo.mkdir()
        env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, env=env).stdout
        git("init", "-q")
        (repo / "src").mkdir()
        (repo / "src/a.py").write_text("fixture\n")
        git("add", "src/a.py")
        git("-c", "user.name=fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture")
        self.source["commit"] = git("rev-parse", "HEAD").decode().strip()
        self.load()
        with self.assertRaisesRegex(ValueError, "checkout"):
            sut.read_tree(repo, "0" * 40)
        output = self.root / "inventory.jsonl"
        command = [sys.executable, str(Path(sut.__file__).resolve()), "inventory", str(self.plan),
                   "--checkout", str(repo), "--observed-head", self.source["commit"], "--output", str(output)]
        first = subprocess.run(command, capture_output=True, env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        saved = output.read_bytes()
        self.assertFalse(json.loads(saved.splitlines()[-1])["migration_complete"])
        second = subprocess.run(command, capture_output=True, env=env)
        self.assertNotEqual(second.returncode, 0)
        self.assertEqual(output.read_bytes(), saved)


if __name__ == "__main__":
    unittest.main()
