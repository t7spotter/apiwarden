"""The automatic changelog.

Specs are edited on disk and reloaded, the way the watcher does it, so these
tests exercise the same path a reader of /changes goes through.
"""

from __future__ import annotations

import json
import subprocess

import pytest
import yaml

from apiwarden import history
from apiwarden.config import Config
from apiwarden.http import Request
from apiwarden.loader import load_registry
from apiwarden.mcp_http import handle_rpc
from apiwarden.router import Portal, build_portal, handle


def drop_first_path(spec_copy):
    """Remove one path, and every operation under it, from a spec file."""
    # The fullest spec, so it keeps at least one path and stays an API.
    documents = {path: yaml.safe_load(path.read_text()) for path in spec_copy.rglob("openapi.yaml")}
    target = max(documents, key=lambda path: len(documents[path].get("paths") or {}))
    document = documents[target]
    document["paths"].pop(next(iter(document["paths"])))
    target.write_text(yaml.safe_dump(document, sort_keys=False))
    return target


@pytest.fixture
def log_path(tmp_path):
    return tmp_path / "log" / "history.json"


def test_the_first_look_records_a_baseline_and_no_entry(spec_copy, log_path):
    changelog = history.History(log_path)
    assert changelog.record(load_registry(spec_copy)) is None
    assert changelog.entries() == []
    assert changelog.tracking_since
    assert log_path.exists()


def test_an_edit_becomes_a_timestamped_entry(spec_copy, log_path):
    changelog = history.History(log_path)
    changelog.record(load_registry(spec_copy))

    drop_first_path(spec_copy)
    entry = changelog.record(load_registry(spec_copy))

    assert entry is not None
    assert entry["counts"]["breaking"] >= 1
    assert entry["at"] > 0
    assert [e["to"] for e in changelog.entries()] == [entry["to"]]


def test_nothing_is_recorded_when_the_contract_is_unchanged(spec_copy, log_path):
    changelog = history.History(log_path)
    changelog.record(load_registry(spec_copy))

    # A description edit changes the bytes, and the revision, but no client cares.
    target = next(spec_copy.rglob("openapi.yaml"))
    target.write_text(target.read_text() + "\n# a comment\n")
    assert changelog.record(load_registry(spec_copy)) is None
    assert changelog.entries() == []


def test_quick_successive_edits_fold_into_one_entry(spec_copy, log_path):
    changelog = history.History(log_path)
    changelog.record(load_registry(spec_copy))

    drop_first_path(spec_copy)
    changelog.record(load_registry(spec_copy))
    drop_first_path(spec_copy)
    changelog.record(load_registry(spec_copy))

    entries = changelog.entries()
    assert len(entries) == 1
    assert sum(c["kind"] == "operation-removed" for c in entries[0]["changes"]) == 2


def test_an_edit_undone_inside_the_window_leaves_no_trace(spec_copy, log_path):
    changelog = history.History(log_path)
    changelog.record(load_registry(spec_copy))

    originals = {path: path.read_text() for path in spec_copy.rglob("openapi.yaml")}
    target = drop_first_path(spec_copy)
    changelog.record(load_registry(spec_copy))
    target.write_text(originals[target])
    changelog.record(load_registry(spec_copy))

    assert changelog.entries() == []


def test_edits_far_apart_are_separate_entries(spec_copy, log_path, monkeypatch):
    changelog = history.History(log_path)
    changelog.record(load_registry(spec_copy))

    clock = [1_000_000.0]
    monkeypatch.setattr(history.time, "time", lambda: clock[0])
    drop_first_path(spec_copy)
    changelog.record(load_registry(spec_copy))
    clock[0] += history.MERGE_WINDOW + 1
    drop_first_path(spec_copy)
    changelog.record(load_registry(spec_copy))

    assert len(changelog.entries()) == 2


def test_the_log_survives_a_restart(spec_copy, log_path):
    history.History(log_path).record(load_registry(spec_copy))
    drop_first_path(spec_copy)

    # A fresh process sees the specs changed while it was down.
    restarted = history.History(log_path)
    assert restarted.record(load_registry(spec_copy)) is not None
    assert len(history.History(log_path).entries()) == 1


def test_two_processes_do_not_record_the_same_change_twice(spec_copy, log_path):
    first, second = history.History(log_path), history.History(log_path)
    first.record(load_registry(spec_copy))
    second.entries()

    drop_first_path(spec_copy)
    registry = load_registry(spec_copy)
    first.record(registry)
    assert second.record(registry) is None
    assert len(second.entries()) == 1


def test_an_unwritable_location_falls_back_to_memory(spec_copy, tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("")
    changelog = history.History(blocker / "history.json")

    changelog.record(load_registry(spec_copy))
    drop_first_path(spec_copy)
    assert changelog.record(load_registry(spec_copy)) is not None
    assert len(changelog.entries()) == 1


def test_the_log_is_capped(spec_copy, log_path, monkeypatch):
    monkeypatch.setattr(history, "ENTRY_LIMIT", 1)
    clock = [1_000_000.0]
    monkeypatch.setattr(history.time, "time", lambda: clock[0])

    changelog = history.History(log_path)
    changelog.record(load_registry(spec_copy))
    for _ in range(2):
        clock[0] += history.MERGE_WINDOW + 1
        drop_first_path(spec_copy)
        changelog.record(load_registry(spec_copy))

    assert len(changelog.entries()) == 1


def test_an_empty_log_is_seeded_from_git(spec_copy, log_path):
    run = lambda *args: subprocess.run(["git", "-C", str(spec_copy), *args], capture_output=True, check=True)
    run("init", "-q")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "T")
    run("add", "-A")
    run("commit", "-qm", "first")
    drop_first_path(spec_copy)
    run("commit", "-qam", "drop an endpoint")

    entries = history.History(log_path)
    entries.record(load_registry(spec_copy))
    [entry] = entries.entries()
    assert entry["commit"]["subject"] == "drop an endpoint"
    assert entry["counts"]["breaking"] >= 1


def test_default_path_is_per_root_and_outside_the_specs(sample_root, tmp_path):
    path = history.default_path(sample_root)
    assert sample_root.resolve() not in path.parents
    assert path != history.default_path(tmp_path)


# ---------------------------------------------------------------- surfaces


def test_changes_page_lists_recorded_entries(spec_copy):
    portal = build_portal(Config(root=spec_copy), watch=False)
    drop_first_path(spec_copy)
    portal.registry = load_registry(spec_copy)

    markup = handle(Request("GET", "/changes"), portal).body.decode()
    assert "Endpoint removed" in markup
    assert "<time" in markup
    assert "?op=" in markup

    payload = json.loads(handle(Request("GET", "/changes.json"), portal).body)
    assert len(payload["entries"]) == 1


def test_the_watcher_records_as_it_reloads(spec_copy):
    portal = build_portal(Config(root=spec_copy), watch=True)
    try:
        drop_first_path(spec_copy)
        import time

        deadline = time.monotonic() + 5
        while not portal.changelog.entries() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert portal.changelog.entries()
    finally:
        portal.watcher.stop()


def test_configured_history_path_is_used(spec_copy, log_path):
    build_portal(Config(root=spec_copy, history=str(log_path)), watch=False)
    assert log_path.exists()


def test_list_changes_without_since_returns_the_changelog(spec_copy):
    config = Config(root=spec_copy)
    build_portal(config, watch=False)
    drop_first_path(spec_copy)

    reply = handle_rpc(
        {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
         "params": {"name": "list_changes", "arguments": {}}},
        load_registry(spec_copy), config,
    )
    payload = json.loads(reply["result"]["content"][0]["text"])
    assert len(payload["entries"]) == 1


def test_a_portal_built_by_hand_keeps_its_log_in_memory(portal):
    assert portal.changelog.path is None
    assert handle(Request("GET", "/changes"), portal).status == 200


# ---------------------------------------------------------------- per-operation history


def _entry(at, *changes):
    from apiwarden import diff

    return {
        "at": at,
        "counts": diff.summarize([diff.Change(*c) for c in changes]),
        "apis": sorted({c[1] for c in changes}),
        "changes": [dict(level=c[0], app=c[1], operation=c[2], kind=c[3], detail=c[4]) for c in changes],
    }


def test_filter_entries_keeps_only_matching_changes_and_recounts():
    entries = [
        _entry(3, ("additive", "tasks", "GET /a/", "operation-added", "new"), ("breaking", "users", "GET /b/", "operation-removed", "gone")),
        _entry(2, ("info", "tasks", "GET /c/", "summary-changed", "x")),
        _entry(1, ("breaking", "tasks", "GET /a/", "field-added", "request.x (required)")),
    ]

    only_a = history.filter_entries(entries, app="tasks", operation="GET /a/")
    assert [e["at"] for e in only_a] == [3, 1]  # newest first, as given; the entry about /c/ drops out
    assert [c["operation"] for c in only_a[0]["changes"]] == ["GET /a/"]
    assert only_a[0]["counts"] == {"breaking": 0, "additive": 1, "info": 0}  # recounted, not copied
    assert only_a[0]["apis"] == ["tasks"]

    whole_api = history.filter_entries(entries, app="users")
    assert [e["at"] for e in whole_api] == [3]
    assert history.filter_entries(entries, app="tasks", operation="GET /nowhere/") == []
    # The input is not modified.
    assert len(entries[0]["changes"]) == 2


def test_history_page_is_scoped_to_one_operation(spec_copy):
    portal = build_portal(Config(root=spec_copy), watch=False)
    drop_first_path(spec_copy)
    portal.registry = load_registry(spec_copy)

    everything = json.loads(handle(Request("GET", "/changes.json"), portal).body)
    removed = [c for c in everything["entries"][0]["changes"] if c["kind"] == "operation-removed"]
    assert len(removed) >= 2, "the sample path removed should carry at least two operations"
    target = removed[0]

    query = {"app": target["app"], "op": target["operation"]}
    scoped = json.loads(handle(Request("GET", "/changes.json", query=query), portal).body)
    assert scoped["filter"] == {"app": target["app"], "operation": target["operation"]}
    changes = scoped["entries"][0]["changes"]
    assert [c["operation"] for c in changes] == [target["operation"]]

    markup = handle(Request("GET", "/changes", query=query), portal).body.decode()
    assert "History of" in markup and target["operation"] in markup
    assert "data-filtered" in markup
    assert "Compare against a specific version" not in markup  # that form belongs to the full page
    assert "class=\"change-history\"" not in markup


def test_full_history_links_each_operation_to_its_history(spec_copy):
    portal = build_portal(Config(root=spec_copy), watch=False)
    drop_first_path(spec_copy)
    portal.registry = load_registry(spec_copy)

    markup = handle(Request("GET", "/changes"), portal).body.decode()
    assert 'class="change-history"' in markup
    assert "?app=" in markup and "&amp;op=" in markup
    assert "data-filtered" not in markup


def test_history_of_an_untouched_operation_says_so(portal):
    markup = handle(Request("GET", "/changes", query={"app": "tasks", "op": "GET /tasks/"}), portal).body.decode()
    assert "No recorded changes to this operation" in markup
