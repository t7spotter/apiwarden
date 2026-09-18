#!/usr/bin/env python3
"""Download the renderer bundle into src/apiwarden/static/vendor/.

Run once after cloning; the result is committed so the wheel is self-contained
and the portal works with no network access.

    python scripts/vendor_assets.py
"""

from __future__ import annotations

import sys
import urllib.request
from pathlib import Path

RAPIDOC_VERSION = "9.3.8"
RAPIDOC_URL = f"https://cdn.jsdelivr.net/npm/rapidoc@{RAPIDOC_VERSION}/dist/rapidoc-min.js"

VENDOR_DIR = Path(__file__).resolve().parent.parent / "src" / "apiwarden" / "static" / "vendor"


def strip_source_map(payload: bytes) -> bytes:
    lines = payload.rstrip(b"\n").split(b"\n")
    if lines[-1].startswith(b"//# sourceMappingURL="):
        lines.pop()
    return b"\n".join(lines) + b"\n"


def main() -> int:
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    target = VENDOR_DIR / "rapidoc.js"

    print(f"downloading {RAPIDOC_URL}")
    with urllib.request.urlopen(RAPIDOC_URL, timeout=60) as response:
        payload = response.read()

    if len(payload) < 100_000:
        print(f"error: unexpectedly small download ({len(payload)} bytes)", file=sys.stderr)
        return 1

    # The bundle ends by naming rapidoc-min.js.map, which we don't ship.
    # Manifest storages (WhiteNoise, ManifestStaticFilesStorage) rewrite that
    # reference at collectstatic and fail the host project's build on it.
    payload = strip_source_map(payload)

    target.write_bytes(payload)
    (VENDOR_DIR / "VERSION").write_text(f"rapidoc@{RAPIDOC_VERSION}\n", encoding="utf-8")
    print(f"wrote {target} ({len(payload) / 1_048_576:.1f} MB)")

    stale = VENDOR_DIR / "scalar.js"
    if stale.exists():
        stale.unlink()
        print(f"removed {stale}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
