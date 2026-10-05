#!/usr/bin/env python3
"""Run apiwarden on the sample specs, to look at the UI or try a change.

    python scripts/demo.py                 # portal on :8080, mock API on :8000
    python scripts/demo.py --port 9090

Works from the source tree, no install needed. It serves a throwaway copy of
tests/fixtures/sample-api with live reload on, and `apiwarden mock` on the port
the sample spec lists as its server (localhost:8000), so Try it gets an answer
built from the specs' own examples. Add another address in the sidebar's server
field to point it elsewhere.

Press Enter in the terminal to edit the copy — it adds one operation to the
tasks API — and watch the page update itself and /changes log it. Ctrl-C stops;
nothing in the repo is touched, and the changelog is kept in the temp copy too.

Static files (JS, CSS) are read from disk, so a browser refresh picks those up.
Python changes need a restart.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
import threading
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

import yaml  # noqa: E402

from apiwarden.config import Config  # noqa: E402
from apiwarden.loader import load_registry  # noqa: E402
from apiwarden.mock import make_server  # noqa: E402
from apiwarden.router import build_portal  # noqa: E402
from apiwarden.server import serve  # noqa: E402

SAMPLE = REPO / "tests" / "fixtures" / "sample-api"


def _start_mock(registry, port: int) -> None:
    try:
        mock = make_server(registry, "127.0.0.1", port)
    except SystemExit as exc:
        print(f"  mock API not started on :{port} ({exc}); Try it will need a server you add yourself")
        return
    threading.Thread(target=mock.serve_forever, daemon=True).start()
    print(f"  mock API   http://127.0.0.1:{port}  (the specs' own examples; try ?__code=401)")


def _edit_loop(root: Path) -> None:
    """Each Enter adds one operation to the tasks spec."""
    spec_path = root / "apps" / "tasks" / "openapi.yaml"
    count = 0
    while True:
        try:
            input()
        except EOFError:
            return
        count += 1
        spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
        spec["paths"][f"/tasks/demo-{count}/"] = {
            "get": {
                "tags": ["Tasks"],
                "summary": f"Demo operation {count}.",
                "operationId": f"demoOperation{count}",
                "responses": {"200": {"description": "Fine."}},
            }
        }
        spec_path.write_text(yaml.safe_dump(spec, sort_keys=False, allow_unicode=True), encoding="utf-8")
        print(f"  added GET /tasks/demo-{count}/ — see the page and /changes  (Enter for another)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--port", type=int, default=8080, help="portal port (default 8080)")
    parser.add_argument("--mock-port", type=int, default=8000, help="mock API port (default 8000)")
    parser.add_argument("--no-mock", action="store_true", help="do not start the mock API")
    args = parser.parse_args()

    workdir = Path(tempfile.mkdtemp(prefix="apiwarden-demo-"))
    try:
        root = workdir / "sample-api"
        shutil.copytree(SAMPLE, root)
        portal = build_portal(
            Config(root=root, title="apiwarden demo", watch=True, history=str(workdir / "changes.json"))
        )

        print("\n  apiwarden demo — a throwaway copy of tests/fixtures/sample-api")
        if not args.no_mock:
            _start_mock(load_registry(root), args.mock_port)
        print("  Enter edits the tasks spec so you can watch it update; Ctrl-C stops.\n")
        threading.Thread(target=_edit_loop, args=(root,), daemon=True).start()
        serve(portal, "127.0.0.1", args.port)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    main()
