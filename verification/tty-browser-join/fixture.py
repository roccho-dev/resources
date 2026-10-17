# SPDX-License-Identifier: GPL-3.0-or-later
"""Isolated C-test Proposal HTTP fixture. Never a Shared Provider substitute.

Mode files change fixture responses, not product inputs. Only VM keyboard input
reaches B/A. The server binds loopback, accepts bounded queries, and does no I/O
outside its explicit test-state directory. No model, credentials or proxy.
"""
from __future__ import annotations

import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import time

MODES = {"typed", "stale", "invalid-json", "duplicate-id", "action", "control-text", "wrong-raw"}


def valid_query(value):
    return (type(value) is dict and set(value) == {"generation", "raw"}
        and type(value["generation"]) is int and value["generation"] > 0
        and type(value["raw"]) is str and 0 < len(value["raw"]) <= 4096)


def candidate(ident, text):
    return {"id": ident, "representation": text,
        "meaning": {"kind": "text", "value": ident}, "evidence": ["C-local-fixture", ident]}


def payload(query, mode):
    if not valid_query(query) or mode not in MODES:
        raise ValueError("invalid-fixture-query-or-mode")
    result = {**query, "proposals": [candidate("typed-A", "甲候補"), candidate("typed-B", "乙候補")]}
    if mode == "invalid-json":
        return b"{invalid"
    if mode == "stale":
        text = "旧候補" if query["raw"] == "u" else "新候補"
        result["proposals"] = [candidate("stale-" + str(query["generation"]), text)]
    elif mode == "duplicate-id":
        result["proposals"][1]["id"] = result["proposals"][0]["id"]
    elif mode == "action":
        result["proposals"] = [{**candidate("action", "not-text"), "meaning": {"kind": "action"}}]
    elif mode == "control-text":
        result["proposals"] = [candidate("control", "must-not\nexecute")]
    elif mode == "wrong-raw":
        result["raw"] = query["raw"] + "-wrong"
    return json.dumps(result, ensure_ascii=False, allow_nan=False).encode()


def server(state: Path, port=0):
    state.mkdir(parents=True, exist_ok=True)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            self.connection.settimeout(2)
            try:
                if self.path != "/proposal":
                    raise ValueError("wrong-path")
                count = getattr(self.server, "query_count", 0) + 1
                self.server.query_count = count
                length = int(self.headers.get("Content-Length", "-1"))
                if not 0 < length <= 16384 or count > 128:
                    raise ValueError("query-limit")
                query = json.loads(self.rfile.read(length))
                mode = (state / "mode").read_text().strip()
                body = payload(query, mode)
                with (state / "requests.jsonl").open("a") as log:
                    log.write(json.dumps({"mode": mode, "query": query}, ensure_ascii=False) + "\n")
                if mode == "stale" and query["raw"] == "u":
                    (state / "held").touch()
                    until = time.monotonic() + 2
                    while not (state / "release").exists() and time.monotonic() < until:
                        time.sleep(.005)
                    if not (state / "release").exists():
                        raise ValueError("fixture-release-missing")
                with (state / "responses.jsonl").open("a") as log:
                    log.write(json.dumps({"mode": mode, "query": query,
                        "sha256": hashlib.sha256(body).hexdigest(), "body": body.decode("utf-8")}, ensure_ascii=False) + "\n")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            except (OSError, ValueError):
                try:
                    self.send_error(400, "C fixture request rejected")
                except (BrokenPipeError, ConnectionResetError):
                    pass

    return HTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    with server(args.state_dir, args.port) as instance:
        (args.state_dir / "ready").touch()
        instance.serve_forever()


if __name__ == "__main__":
    main()
