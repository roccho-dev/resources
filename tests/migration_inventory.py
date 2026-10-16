"""#25 L-source only: immutable Git metadata -> proposed path inventory, never acceptance."""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


SHA = re.compile(r"[0-9a-f]{40}\Z")
FIELDS = {
    "source": {"kind", "repository", "branch", "commit", "plan", "purpose"},
    "route": {"kind", "match", "destination", "owner", "wait"},
    "gap": {"kind", "scope", "status", "owner", "reason"},
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, f"duplicate JSON key: {key}")
        result[key] = value
    return result


def load_plan(path):
    rows = [json.loads(line, object_pairs_hook=unique_object)
            for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    for row in rows:
        require(isinstance(row, dict), "expected an object per line")
        kind = row.get("kind")
        require(isinstance(kind, str) and kind in FIELDS, "unknown record kind")
        require(set(row) == FIELDS[kind], f"unexpected fields: {kind}")
        for key, value in row.items():
            if key != "wait":
                require(isinstance(value, str) and bool(value.strip()), f"empty/non-text field: {key}")
    sources = [r for r in rows if r["kind"] == "source"]
    routes = [r for r in rows if r["kind"] == "route"]
    gaps = [r for r in rows if r["kind"] == "gap"]
    require(len(sources) == 1 and routes and gaps, "need one source, routes and explicit gaps")
    source = sources[0]
    require(SHA.fullmatch(source["commit"]), "invalid source commit")
    require(re.fullmatch(r"[A-Za-z0-9_-][A-Za-z0-9_.-]*/[A-Za-z0-9_-][A-Za-z0-9_.-]*", source["repository"]), "invalid repository")
    require(re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_/-]*", source["branch"]), "invalid branch")
    require(not source["branch"].endswith("/") and "//" not in source["branch"], "invalid branch")
    require(len({r["match"] for r in routes}) == len(routes), "duplicate route")
    for route in routes:
        match = route["match"].removesuffix("/")
        require(match and all(p not in {"", ".", ".."} for p in match.split("/")), "unsafe route")
        require(not any(ord(c) < 32 for c in match), "control character in route")
        require(isinstance(route["wait"], list) and all(isinstance(x, str) and x for x in route["wait"]), "invalid wait list")
    require(len({g["scope"] for g in gaps}) == len(gaps), "duplicate gap")
    require(all(g["status"] == "UNVERIFIED" for g in gaps), "this tool cannot accept a gap")
    return source, routes, gaps


def parse_tree(raw):
    require(raw and raw.endswith(b"\0"), "empty or truncated Git tree")
    rows = []
    seen = set()
    for record in raw[:-1].split(b"\0"):
        metadata, path = record.split(b"\t", 1)
        mode, kind, oid = metadata.decode("ascii").split(" ")
        path = path.decode("utf-8")
        require(kind == "blob" and mode in {"100644", "100755", "120000"}, "unhandled Git entry (including submodule)")
        require(SHA.fullmatch(oid) and path and path not in seen, "invalid or duplicate Git path")
        seen.add(path)
        rows.append({"path": path, "mode": mode, "blob": oid})
    return rows


def read_tree(checkout, commit):
    def git(*args):
        return subprocess.run(["git", "--no-optional-locks", "-C", str(checkout), *args],
                              check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30).stdout
    require(git("rev-parse", "--verify", "HEAD").decode().strip() == commit, "checkout does not match pinned source")
    return parse_tree(git("ls-tree", "-r", "-z", "--full-tree", commit))


def inventory(source, routes, gaps, entries, observed_head):
    require(SHA.fullmatch(observed_head) and observed_head == source["commit"], "STALE: observed branch differs from source pin")
    require(entries and len({e["path"] for e in entries}) == len(entries), "empty or duplicate entries")
    result = [{**source, "observed_head": observed_head, "scope": "source-paths-only"}]
    for entry in sorted(entries, key=lambda e: e["path"]):
        path = entry["path"]
        candidates = [r for r in routes if path == r["match"] or
                      (r["match"].endswith("/") and path.startswith(r["match"]))]
        require(candidates, f"unmapped path: {path}")
        # A nested binding rule overrides its broader directory, never input order.
        route = max(candidates, key=lambda r: len(r["match"]))
        result.append({"kind": "path", **entry,
                       "destination_candidate": route["destination"] + path[len(route["match"]):],
                       "owner": route["owner"], "wait": route["wait"], "status": "UNMIGRATED"})
    result.extend(gaps)
    result.append({"kind": "summary", "path_coverage": "PASS", "paths": len(entries),
                   "workflows": sum(e["path"].startswith(".github/workflows/") and
                                    e["path"].endswith((".yml", ".yaml")) for e in entries),
                   "unverified_categories": [g["scope"] for g in gaps], "migration_complete": False})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["metadata", "inventory"])
    parser.add_argument("plan", type=Path)
    parser.add_argument("--checkout", type=Path)
    parser.add_argument("--observed-head")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        source, routes, gaps = load_plan(args.plan)
        if args.mode == "metadata":
            for key in ("repository", "commit", "branch"):
                print(f"{key}={source[key]}")
            return
        require(args.checkout and args.observed_head and args.output, "inventory needs checkout, observed-head and output")
        rows = inventory(source, routes, gaps, read_tree(args.checkout, source["commit"]), args.observed_head)
        payload = "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows)
        # Validate everything before creating one new output; never overwrite prior evidence.
        with args.output.open("x", encoding="utf-8") as out:
            out.write(payload)
        print(json.dumps(rows[-1], ensure_ascii=False))
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        print(f"RED: {error}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
