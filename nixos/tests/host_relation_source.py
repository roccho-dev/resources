#!/usr/bin/env python3
"""Unadmitted Host/Relation source semantics: finite, no Target or deployment.

Host IDs are external identities. SOURCE reuse, contains, manages and optional
wrap are independent. This never creates IDs, authority, effects, or real O.
"""
from __future__ import annotations

import copy
import re
import unittest


class RelationRefused(ValueError):
    pass


TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,119}\Z")
ALLOWED = {"contains", "manages"}


def require(ok, reason):
    if not ok:
        raise RelationRefused(reason)


def valid_token(text):
    return type(text) is str and TOKEN.fullmatch(text) is not None


def project(hosts, edges):
    """Pure proposed graph with per-session-instance uniqueness and acyclic containment.

    A source graph is not proof an instance exists, is running or can be managed.
    """
    require(type(hosts) is list and bool(hosts), "explicit Host catalog required")
    require(type(edges) is list, "relation list required")
    catalog = {}
    for h in hosts:
        require(type(h) is dict and set(h) == {"id", "implementation_ref"},
                "unknown Host catalog field")
        require(valid_token(h["id"]) and h["id"] not in catalog,
                "invalid or duplicate externally supplied Host identity")
        require(valid_token(h["implementation_ref"]),
                "Host implementation reference is not a source-owned Host ID")
        catalog[h["id"]] = h["implementation_ref"]

    seen = set()
    containing = {}
    for e in edges:
        require(type(e) is dict and set(e) == {"parent", "child", "kind", "scope", "wrap"},
                "relation has unsupported meaning/field")
        require(e["kind"] in ALLOWED and all(valid_token(e[k]) for k in
                ("parent", "child", "scope")), "unsupported directed relation")
        require(e["parent"] in catalog and e["child"] in catalog
                and e["parent"] != e["child"], "unknown Host or self-reference")
        require(e["wrap"] is None if e["kind"] == "manages"
                else e["wrap"] is None or valid_token(e["wrap"]),
                "wrap belongs only to containment, and is always optional")
        identity = (e["kind"], e["scope"], e["parent"], e["child"])
        require(identity not in seen, "duplicate relation assertion")
        seen.add(identity)
        if e["kind"] == "contains":
            parents = containing.setdefault(e["scope"], {}).setdefault(e["child"], set())
            parents.add(e["parent"])
            require(len(parents) == 1, "same scoped running instance has multiple parents")

    # Acyclic per actual scope, not across independent time instances.
    for scope, parents in containing.items():
        graph = {}
        for child, parent in parents.items():
            graph.setdefault(next(iter(parent)), set()).add(child)
        visiting, done = set(), set()

        def visit(node):
            require(node not in visiting, "cyclic containment")
            if node in done:
                return
            visiting.add(node)
            for child in graph.get(node, ()):
                visit(child)
            visiting.remove(node)
            done.add(node)
        for node in catalog:
            visit(node)

    return {
        "kind": "resources.syntheticHostRelationProjection.v0",
        "host_ids": sorted(catalog), "relations": copy.deepcopy(edges),
        "admission": "NOT_ADMITTED", "observed_running": "UNPROVEN",
        "target_authority": "NOT_GRANTED", "effect": "FORBIDDEN",
    }


def fixture():
    hosts = [
        {"id": "host-A", "implementation_ref": "repo:source-v1"},
        {"id": "host-B", "implementation_ref": "repo:source-v1"},
        {"id": "host-C", "implementation_ref": "repo:source-v2"},
        {"id": "host-D", "implementation_ref": "repo:source-v1"},
    ]
    edges = [
        {"parent": "host-A", "child": "host-B", "kind": "contains",
         "scope": "session-1", "wrap": "VM"},
        {"parent": "host-B", "child": "host-C", "kind": "contains",
         "scope": "session-1", "wrap": "OCI"},
        {"parent": "host-D", "child": "host-C", "kind": "manages",
         "scope": "session-1", "wrap": None},
    ]
    return hosts, edges


class ProposedRelationCases(unittest.TestCase):
    def refuse(self, hosts, edges):
        with self.assertRaises(RelationRefused):
            project(hosts, edges)

    def test_external_host_identity_is_not_minted_from_repo_os_image_or_wrap(self):
        hosts, edges = fixture()
        result = project(hosts, edges)
        self.assertEqual(result["host_ids"], sorted(h["id"] for h in hosts))
        self.assertEqual(result["admission"], "NOT_ADMITTED")
        self.assertEqual(result["effect"], "FORBIDDEN")
        self.assertEqual(result["target_authority"], "NOT_GRANTED")
        self.assertEqual(result["observed_running"], "UNPROVEN")
        self.assertEqual(hosts[0]["implementation_ref"], hosts[1]["implementation_ref"])
        self.assertNotIn("status", result)
        self.assertNotIn("started", result)

    def test_contains_and_manages_do_not_imply_each_other_or_authority(self):
        hosts, edges = fixture()
        result = project(hosts, edges)
        self.assertEqual(len(result["relations"]), 3)
        self.assertNotIn("credential", result)
        self.assertNotIn("authorized", result)
        # Multiple managers are okay; this never creates another contains parent.
        edges.append({"parent": "host-A", "child": "host-C", "kind": "manages",
                      "scope": "session-1", "wrap": None})
        self.assertEqual(len(project(hosts, edges)["relations"]), 4)

    def test_oci_optional_and_other_wrap_does_not_change_host_identity(self):
        hosts, edges = fixture()
        baseline = project(hosts, edges)["host_ids"]
        for wrap in (None, "OCI", "VM", "other-wrap"):
            case = copy.deepcopy(edges)
            case[0]["wrap"] = wrap
            self.assertEqual(project(hosts, case)["host_ids"], baseline)

    def test_containment_cycles_self_and_multi_parent_refused_same_scope(self):
        hosts, edges = fixture()
        for extra in (
            {"parent": "host-B", "child": "host-B", "kind": "contains",
             "scope": "session-1", "wrap": None},
            {"parent": "host-C", "child": "host-A", "kind": "contains",
             "scope": "session-1", "wrap": None},
            {"parent": "host-D", "child": "host-B", "kind": "contains",
             "scope": "session-1", "wrap": "OCI"},
        ):
            self.refuse(hosts, edges + [extra])

    def test_different_scope_can_reuse_same_host_implementation_and_parent(self):
        hosts, edges = fixture()
        edges.append({"parent": "host-D", "child": "host-B", "kind": "contains",
                      "scope": "session-2", "wrap": None})
        self.assertEqual(len(project(hosts, edges)["relations"]), 4)

    def test_absent_host_and_unknown_relation_meaning_refuse(self):
        hosts, edges = fixture()
        for change in (
            lambda e: e.update(child="missing-host"),
            lambda e: e.update(parent="missing-host"),
            lambda e: e.update(kind="runs"),
            lambda e: e.update(parent=e["child"]),
            lambda e: e.update(secret="private"),
            lambda e: e.update(wrap="TOOL_CHANGE"),
        ):
            h, es = fixture()
            change(es[0])
            # "TOOL_CHANGE" is a valid *wrap label* only; not an authority:
            if es[0]["wrap"] == "TOOL_CHANGE":
                self.assertEqual(project(h, es)["effect"], "FORBIDDEN")
            else:
                self.refuse(h, es)

    def test_duplicate_rows_and_invalid_manager_wrap_refused(self):
        hosts, edges = fixture()
        self.refuse(hosts + [copy.deepcopy(hosts[0])], edges)
        self.refuse(hosts, edges + [copy.deepcopy(edges[0])])
        bad = copy.deepcopy(edges)
        bad[-1]["wrap"] = "OCI"
        self.refuse(hosts, bad)

    def test_source_only_graph_no_mutation_and_no_owner_right(self):
        hosts, edges = fixture()
        before = copy.deepcopy((hosts, edges))
        self.assertEqual(project(hosts, edges)["effect"], "FORBIDDEN")
        self.assertEqual((hosts, edges), before)
        self.assertEqual(project(hosts, [])["relations"], [])


if __name__ == "__main__":
    unittest.main()
