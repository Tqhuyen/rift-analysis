#!/usr/bin/env python3
r"""Snapshot the current dashboard payload so no match falls out of the LCU window.

The League client only keeps the last ~21 games. ``lcu_stats.py`` already caches
raw details permanently, but a periodic snapshot adds a versioned, display-ready
copy you can diff, archive, or import elsewhere.

Run manually:
    python snapshot.py

Run on a schedule (recommended every 30 minutes while you play):
    powershell -ExecutionPolicy Bypass -File scripts\install-snapshot-task.ps1

Exits quietly with code 0 when the League client is not running, so it is safe
for Task Scheduler.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import lcu_stats

ROOT = Path(__file__).resolve().parent
SNAPSHOT_DIR = ROOT / "snapshots"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def prune(keep: int) -> int:
    if keep <= 0 or not SNAPSHOT_DIR.exists():
        return 0
    files = sorted(SNAPSHOT_DIR.glob("rift-*.json"))
    removed = 0
    for path in files[:-keep]:
        try:
            path.unlink()
            removed += 1
        except OSError:
            pass
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description="Snapshot LCU Mayhem stats")
    parser.add_argument("--keep", type=int, default=500,
                        help="keep only the newest N snapshots (0 = unlimited)")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    try:
        payload, _me = lcu_stats.sync(pages=3, verbose=False)
    except lcu_stats.LcuUnavailable as exc:
        if not args.quiet:
            print(f"LCU unavailable, snapshot skipped: {exc}")
        return 0

    matches = payload.get("matches") or []
    if not matches:
        if not args.quiet:
            print("No Mayhem matches found, snapshot skipped")
        return 0

    SNAPSHOT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = SNAPSHOT_DIR / f"rift-{stamp}.json"

    archive = {
        "type": "rift-snapshot",
        "schema": 1,
        "takenAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": payload.get("source") or "lcu",
        "players": payload.get("players") or [],
        "matches": matches,
        "queues": payload.get("queues") or {},
    }

    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(archive, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    removed = prune(args.keep)

    if not args.quiet:
        newest = max((m.get("timestamp") or 0) for m in matches)
        when = datetime.fromtimestamp(newest / 1000).strftime("%Y-%m-%d %H:%M")
        print(f"snapshot {path.name}: {len(matches)} matches, newest {when}"
              + (f", pruned {removed}" if removed else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
