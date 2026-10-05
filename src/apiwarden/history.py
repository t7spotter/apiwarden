"""A changelog the portal keeps by itself.

Whenever the specs change — an edit the watcher picks up, or a deploy noticed
at startup — the new contract is compared against the last one seen and the
difference is written down with a timestamp. Nobody has to name a tag or keep
a snapshot file around: open /changes and the history is already there.

On the very first run there is nothing to compare against yet, so when the
specs live in a git checkout the recent commits that touched them are read
once to seed the log. Without git the log simply starts from that moment.

The log is one JSON file. It is re-read before every write, so several worker
processes sharing it do not record the same change twice.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

from . import diff
from .config import Config
from .loader import Registry

# Oldest entries are dropped past this many.
ENTRY_LIMIT = 200
# Saves this close together fold into one entry, so an afternoon spent editing
# a spec reads as one change rather than forty — and an edit that is undone
# before the window closes disappears from the log entirely.
MERGE_WINDOW = 15 * 60
# How many commits to read when seeding the log from git.
SEED_COMMITS = 10


def open_for(config: Config) -> History:
    return History(Path(config.history) if config.history else default_path(config.root))


def default_path(root: Path) -> Path:
    """Where the log lives when `history` is not configured.

    The user's cache directory rather than the spec directory: the specs are
    often read-only (a container image, a checkout owned by someone else), and
    a docs tool should not drop files into a project unasked.
    """
    base = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache")
    resolved = Path(root).resolve()
    key = hashlib.sha256(str(resolved).encode("utf-8")).hexdigest()[:12]
    return base / "apiwarden" / f"{resolved.name or 'root'}-{key}" / "history.json"


class History:
    def __init__(self, path: Path | None) -> None:
        # None keeps the log in memory only.
        self.path = Path(path) if path else None
        self._lock = threading.Lock()
        self._state: dict[str, Any] = _empty()
        self._stamp: tuple[int, int] | None = None
        self._writable = True

    # ------------------------------------------------------------ reading

    def entries(self, limit: int | None = None) -> list[dict[str, Any]]:
        """Recorded changes, newest first."""
        with self._lock:
            self._load()
            newest = list(reversed(self._state["entries"]))
        return newest[:limit] if limit else newest

    @property
    def tracking_since(self) -> float | None:
        with self._lock:
            self._load()
            return self._state.get("since")

    # ------------------------------------------------------------ recording

    def record(self, registry: Registry) -> dict[str, Any] | None:
        """Note the current state of the specs; returns the entry it touched."""
        with self._lock:
            self._load()
            baseline = self._state["baseline"]
            # Cheap check first: snapshotting every spec is not free, and this
            # runs on every visit to the changes page.
            if baseline is not None and baseline.get("revision") == registry.revision:
                return None

            current = diff.snapshot(registry)
            now = time.time()

            if baseline is None:
                self._state["since"] = now
                baseline = self._seed_from_git(registry)
                if baseline is None:
                    self._state["baseline"] = current
                    self._save()
                    return None

            entry = self._advance(baseline, current, now)
            self._state["baseline"] = current
            del self._state["entries"][:-ENTRY_LIMIT]
            self._save()
            return entry

    def _advance(self, baseline: dict, current: dict, now: float) -> dict[str, Any] | None:
        entries = self._state["entries"]
        last = entries[-1] if entries else None
        start = self._state.get("open_from")

        if last and start and "commit" not in last and now - last["at"] < MERGE_WINDOW:
            # Still the same editing session: measure from where it began.
            entries.pop()
            changes = diff.compare(start, current)
            if not changes:
                return None
            entry = _entry(start, current, changes, now)
            entries.append(entry)
            return entry

        changes = diff.compare(baseline, current)
        if not changes:
            return None
        self._state["open_from"] = baseline
        entry = _entry(baseline, current, changes, now)
        entries.append(entry)
        return entry

    def _seed_from_git(self, registry: Registry) -> dict[str, Any] | None:
        """Fill an empty log from recent commits; returns the newest snapshot."""
        try:
            log = diff._git(
                registry.root, "log", f"-{SEED_COMMITS + 1}",
                "--format=%H%x1f%ct%x1f%an%x1f%s", "--", ".",
            )
        except diff.DiffUnavailable:
            return None

        commits = [line.split("\x1f", 3) for line in log.splitlines() if line.count("\x1f") == 3]
        snapshots = []
        for sha, stamp, author, subject in reversed(commits):
            try:
                past = diff.snapshot(diff._registry_at_revision(registry, sha))
            except diff.DiffUnavailable:
                continue
            snapshots.append(({"sha": sha, "author": author, "subject": subject}, float(stamp), past))

        for (_, _, older), (commit, stamp, newer) in zip(snapshots, snapshots[1:]):
            changes = diff.compare(older, newer)
            if changes:
                self._state["entries"].append({**_entry(older, newer, changes, stamp), "commit": commit})

        return snapshots[-1][2] if snapshots else None

    # ------------------------------------------------------------ storage

    def _load(self) -> None:
        if self.path is None:
            return
        try:
            stat = self.path.stat()
        except OSError:
            return
        stamp = (stat.st_mtime_ns, stat.st_size)
        if stamp == self._stamp:
            return
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # unreadable: keep what is in memory, and overwrite it on the next save
        if isinstance(loaded, dict) and isinstance(loaded.get("entries"), list):
            self._state = {**_empty(), **loaded}
            self._stamp = stamp

    def _save(self) -> None:
        if self.path is None or not self._writable:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            # Write-then-rename, so a reader never sees half a file.
            handle, temp = tempfile.mkstemp(dir=self.path.parent, prefix=".history-", suffix=".json")
            with os.fdopen(handle, "w", encoding="utf-8") as out:
                json.dump(self._state, out, separators=(",", ":"))
            os.replace(temp, self.path)
            stat = self.path.stat()
            self._stamp = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            # Somewhere unwritable: carry on in memory rather than fail requests.
            self._writable = False


def _empty() -> dict[str, Any]:
    return {"since": None, "baseline": None, "open_from": None, "entries": []}


def _entry(before: dict, after: dict, changes: list[diff.Change], at: float) -> dict[str, Any]:
    return {
        "at": at,
        "from": before.get("revision"),
        "to": after.get("revision"),
        "counts": diff.summarize(changes),
        "apis": sorted({change.app for change in changes}),
        "changes": diff.as_dicts(changes),
    }
