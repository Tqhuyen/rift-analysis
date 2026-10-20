#!/usr/bin/env python3
"""Export this client's ARAM: Mayhem games as a portable JSON bundle.

Run this on each friend's PC while their League client is open. Send the
resulting file to the person running the dashboard and drop it into ``imports/``
(or push it to Supabase). The bundle contains only post-game Mayhem data from
the logged-in account — no lockfile, password, or API key.

Usage:
    python lcu_export.py
    python lcu_export.py --out exports/rift-friend.json
    python lcu_export.py --pages 5
    python lcu_export.py --from-cache          # no client needed

The dashboard merges every ``imports/*.json`` by ``gameId`` automatically.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import lcu_stats

ROOT = Path(__file__).resolve().parent
EXPORT_DIR = ROOT / "exports"
MAYHEM = lcu_stats.MAYHEM_QUEUE

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def collect(me: dict, details: list[dict], notes: str) -> dict:
    """Build an export bundle.

    Only the exporter and any locally configured ``players.txt`` identities are
    written to ``roster`` — never random opponents or teammates.
    """
    known = {
        (entry.get("name") or "", entry.get("tag") or "")
        for entry in lcu_stats.load_roster()
        if entry.get("name")
    }

    roster = []

    def add_identity(ident: dict) -> None:
        if not ident.get("puuid"):
            return
        if any(item["puuid"] == ident["puuid"] for item in roster):
            return
        roster.append(
            {
                "puuid": ident["puuid"],
                "name": ident.get("name") or "",
                "tag": ident.get("tag") or "",
            }
        )

    for detail in details:
        for ident in lcu_stats.player_identity(detail).values():
            if (ident.get("name") or "", ident.get("tag") or "") in known:
                add_identity(ident)

    if me.get("puuid"):
        add_identity(
            {
                "puuid": me["puuid"],
                "name": me.get("gameName") or me.get("displayName") or "",
                "tag": me.get("tagLine") or "",
            }
        )

    return {
        "type": "rift-export",
        "schema": 1,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "note": notes,
        "exporter": {
            "puuid": me.get("puuid"),
            "name": me.get("gameName") or me.get("displayName") or "",
            "tag": me.get("tagLine") or "",
        },
        "roster": roster,
        "matches": details,
    }


def from_cache() -> tuple[dict, list[dict]]:
    # Cached details are raw; filter to Mayhem and drop duplicates.
    details = [d for d in lcu_stats.load_cached_matches() if d.get("queueId") == MAYHEM]
    return {}, details


def main() -> int:
    parser = argparse.ArgumentParser(description="Export LCU Mayhem games to JSON")
    parser.add_argument("--out", metavar="PATH", help="output file")
    parser.add_argument("--pages", type=int, default=3, help="history pages to scan")
    parser.add_argument("--from-cache", action="store_true", help="export cache only")
    args = parser.parse_args()

    if args.from_cache:
        me, details = from_cache()
        if not details:
            print("cache/lcu is empty; run lcu_stats.py first")
            return 1
        note = "exported from local cache"
        me_name = "cache"
    else:
        lockfile = lcu_stats.find_lockfile()
        if not lockfile:
            print("LCU lockfile not found. Open the League client first, or use --from-cache.")
            return 1
        client = lcu_stats.LcuClient(lcu_stats.read_lockfile(lockfile))
        me = client.current_summoner()
        if not me:
            print("LCU did not return a summoner (logged in?).")
            return 1

        summaries = client.recent_matches(pages=args.pages)
        mayhem = [s for s in summaries if s.get("queueId") == MAYHEM]
        details = []
        for summary in mayhem:
            detail = client.match_detail(summary.get("gameId"))
            if detail:
                details.append(detail)
        note = "exported from League client"
        me_name = (me.get("gameName") or "player").replace(" ", "-").lower()
        print(f"{me.get('gameName')}#{me.get('tagLine')}: {len(details)} Mayhem games")

    bundle = collect(me, details, note)

    EXPORT_DIR.mkdir(exist_ok=True)
    if args.out:
        out = Path(args.out)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M")
        out = EXPORT_DIR / f"rift-export-{me_name}-{stamp}.json"

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(bundle, ensure_ascii=False, indent=1), encoding="utf-8")
    size_mb = out.stat().st_size / 1e6
    print(f"wrote {out} ({size_mb:.2f} MB, {len(details)} matches, {len(bundle['roster'])} identities)")
    print("next: drop it into imports/ on the dashboard machine, or run:")
    print(f"  python rift_db.py push --import \"{out}\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
