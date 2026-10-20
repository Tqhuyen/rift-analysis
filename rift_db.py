#!/usr/bin/env python3
"""Optional Supabase persistence for Rift Report.

Stores players, matches, and participants in three prefixed tables so the
dashboard survives cache loss and can merge exports from several machines.
Uses Supabase's PostgREST endpoint with the standard library (no SDK).

Configuration (environment or a local ``.env``):

    SUPABASE_URL=https://<project>.supabase.co
    SUPABASE_SERVICE_KEY=<service-role key>   # server-side only
    # SUPABASE_KEY=<anon key>                 # fallback, needs write policies

The service-role key must never reach the browser or the repository. The
dashboard server only reads it server-side.

CLI:
    python rift_db.py status
    python rift_db.py push
    python rift_db.py push --import exports/rift-friend.json
    python rift_db.py pull --out cache/db-stats.json
    python rift_db.py schema            # print the SQL to run once
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import lcu_stats

ROOT = Path(__file__).resolve().parent
ENV_FILE = ROOT / ".env"
SCHEMA_FILE = ROOT / "supabase" / "schema.sql"
IMPORTS_DIR = lcu_stats.IMPORTS_DIR

PLAYERS_TABLE = "rift_players"
MATCHES_TABLE = "rift_matches"
PARTS_TABLE = "rift_participants"
CHUNK = 400

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def _load_env_file() -> dict:
    values: dict[str, str] = {}
    if not ENV_FILE.exists():
        return values
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


_ENV = _load_env_file()


def _get(name: str) -> str | None:
    return os.environ.get(name) or _ENV.get(name)


def config() -> dict | None:
    url = (_get("SUPABASE_URL") or "").rstrip("/")
    key = _get("SUPABASE_SERVICE_KEY") or _get("SUPABASE_KEY")
    if not url or not key:
        return None
    return {"url": url, "key": key, "base": url + "/rest/v1"}


def configured() -> bool:
    return config() is not None


# --------------------------------------------------------------------------- #
# HTTP
# --------------------------------------------------------------------------- #
def _request(method: str, path: str, *, body=None, prefer: str | None = None,
             extra_headers: dict | None = None) -> tuple[int, bytes, dict]:
    cfg = config()
    if not cfg:
        raise RuntimeError(
            "Supabase is not configured. Set SUPABASE_URL and SUPABASE_SERVICE_KEY "
            "in .env or the environment."
        )
    headers = {
        "apikey": cfg["key"],
        "Authorization": f"Bearer {cfg['key']}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    if extra_headers:
        headers.update(extra_headers)

    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(cfg["base"] + path, data=data, headers=headers,
                                     method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:500]
        raise RuntimeError(f"Supabase {method} {path} -> HTTP {exc.code}: {detail}") from exc


def _select(table: str, query: str) -> list[dict]:
    status, raw, _ = _request("GET", f"/{table}?{query}")
    return json.loads(raw.decode("utf-8")) if raw else []


def _upsert(table: str, rows: list[dict], conflict: str) -> int:
    if not rows:
        return 0
    total = 0
    for start in range(0, len(rows), CHUNK):
        chunk = rows[start:start + CHUNK]
        _request(
            "POST",
            f"/{table}?on_conflict={conflict}",
            body=chunk,
            prefer="resolution=merge-duplicates,return=minimal",
        )
        total += len(chunk)
    return total


# --------------------------------------------------------------------------- #
# Mapping
# --------------------------------------------------------------------------- #
def _iso(ms) -> str:
    return datetime.fromtimestamp(int(ms) / 1000, tz=timezone.utc).isoformat()


def payload_to_rows(payload: dict) -> tuple[list[dict], list[dict], list[dict]]:
    players, matches, participants = [], [], []

    for player in payload.get("players", []):
        if not player.get("puuid"):
            continue
        players.append(
            {
                "puuid": player["puuid"],
                "name": player.get("name") or "Unknown",
                "tag": player.get("tag") or "",
                "role": player.get("role") or "",
                "c1": player.get("c1"),
                "c2": player.get("c2"),
            }
        )

    for match in payload.get("matches", []):
        game_id = match.get("gameId") or match.get("id")
        try:
            game_id = int(game_id)
        except (TypeError, ValueError):
            continue
        matches.append(
            {
                "game_id": game_id,
                "queue_id": int(match.get("queueId") or 2400),
                "played_at": _iso(match.get("timestamp") or 0),
                "duration": int(match.get("duration") or 0),
                "game_version": match.get("version") or "",
                "source": payload.get("source") or "lcu",
            }
        )
        for part in match.get("participants", []):
            if not part.get("puuid"):
                continue
            participants.append(
                {
                    "game_id": game_id,
                    "puuid": part["puuid"],
                    "champion": part.get("champion") or "",
                    "win": bool(part.get("win")),
                    "kills": int(part.get("kills") or 0),
                    "deaths": int(part.get("deaths") or 0),
                    "assists": int(part.get("assists") or 0),
                    "damage": int(part.get("damage") or 0),
                    "gold": int(part.get("gold") or 0),
                    "cs": int(part.get("cs") or 0),
                    "champ_level": int(part.get("champLevel") or 0),
                    "team_id": part.get("teamId"),
                    "augments": part.get("augments") or [],
                }
            )
    return players, matches, participants


def rows_to_payload(players: list[dict], matches: list[dict], participants: list[dict]) -> dict:
    roster = []
    for index, row in enumerate(sorted(players, key=lambda r: r.get("name") or "")):
        palette = lcu_stats.PALETTE[index % len(lcu_stats.PALETTE)]
        roster.append(
            {
                "id": f"player{index + 1}",
                "puuid": row["puuid"],
                "name": row.get("name") or "Unknown",
                "tag": row.get("tag") or "",
                "initials": lcu_stats.initials(row.get("name") or "?"),
                "role": row.get("role") or "",
                "c1": row.get("c1") or palette[0],
                "c2": row.get("c2") or palette[1],
            }
        )
    id_by_puuid = {p["puuid"]: p["id"] for p in roster}

    parts_by_game: dict[int, list[dict]] = {}
    for row in participants:
        puuid = row.get("puuid")
        if puuid not in id_by_puuid:
            continue
        parts_by_game.setdefault(int(row["game_id"]), []).append(
            {
                "playerId": id_by_puuid[puuid],
                "puuid": puuid,
                "champion": row.get("champion") or "",
                "win": bool(row.get("win")),
                "kills": int(row.get("kills") or 0),
                "deaths": int(row.get("deaths") or 0),
                "assists": int(row.get("assists") or 0),
                "damage": int(row.get("damage") or 0),
                "gold": int(row.get("gold") or 0),
                "cs": int(row.get("cs") or 0),
                "champLevel": int(row.get("champ_level") or 0),
                "teamId": row.get("team_id"),
                "augments": row.get("augments") or [],
            }
        )

    out_matches = []
    for row in matches:
        game_id = int(row["game_id"])
        parts = parts_by_game.get(game_id)
        if not parts:
            continue
        out_matches.append(
            {
                "id": str(game_id),
                "gameId": game_id,
                "queueId": int(row.get("queue_id") or 2400),
                "timestamp": int(
                    datetime.fromisoformat(row["played_at"].replace("Z", "+00:00")).timestamp()
                    * 1000
                ),
                "duration": int(row.get("duration") or 0),
                "version": row.get("game_version") or "",
                "participants": parts,
            }
        )
    out_matches.sort(key=lambda m: m["timestamp"], reverse=True)

    # Champion catalog: Data Dragon when available, otherwise derive keys.
    champs = lcu_stats.champion_map()
    champions = {}
    for champ in champs.values():
        key = champ["key"]
        champions[key] = {
            "key": key,
            "name": champ["name"],
            "title": champ.get("title", ""),
            "role": (champ.get("tags") or ["Fighter"])[0],
            "splash": f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{key}_0.jpg",
            "tile": f"https://ddragon.leagueoflegends.com/cdn/img/champion/tiles/{key}_0.jpg",
        }
    for match in out_matches:
        for part in match["participants"]:
            key = part["champion"]
            if key and key not in champions:
                champions[key] = {
                    "key": key,
                    "name": key,
                    "title": "",
                    "role": "Fighter",
                }

    return {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "supabase",
        "players": roster,
        "champions": champions,
        "matches": out_matches,
        "queues": {str(lcu_stats.MAYHEM_QUEUE): lcu_stats.QUEUE_NAMES[lcu_stats.MAYHEM_QUEUE]},
    }


# --------------------------------------------------------------------------- #
# Public operations
# --------------------------------------------------------------------------- #
def push_payload(payload: dict) -> dict:
    players, matches, participants = payload_to_rows(payload)
    if not any((players, matches, participants)):
        return {"players": 0, "matches": 0, "participants": 0}

    # Order matters: FK targets first.
    n_players = _upsert(PLAYERS_TABLE, players, "puuid")
    n_matches = _upsert(MATCHES_TABLE, matches, "game_id")
    n_parts = _upsert(PARTS_TABLE, participants, "game_id,puuid")
    return {"players": n_players, "matches": n_matches, "participants": n_parts}


def pull_payload() -> dict:
    players = _select(PLAYERS_TABLE, "select=*&order=name.asc")
    matches = _select(MATCHES_TABLE, "select=*&order=played_at.desc")
    participants = _select(PARTS_TABLE, "select=*")
    return rows_to_payload(players, matches, participants)


def status() -> dict:
    cfg = config()
    if not cfg:
        return {"configured": False}
    players = _select(PLAYERS_TABLE, "select=puuid&limit=1000")
    matches = _select(MATCHES_TABLE, "select=game_id,played_at&order=played_at.desc&limit=1000")
    parts = _request("GET", f"/{PARTS_TABLE}?select=game_id&limit=1",
                     extra_headers={"Prefer": "count=exact"})
    count_header = parts[2].get("Content-Range", "")
    total_parts = count_header.split("/")[-1] if "/" in count_header else "?"
    return {
        "configured": True,
        "project": cfg["url"],
        "players": len(players),
        "matches": len(matches),
        "participants": total_parts,
        "latestMatch": matches[0]["played_at"] if matches else None,
    }


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_local_payload() -> dict:
    matches = lcu_stats.load_cached_matches()
    champs = lcu_stats.champion_map()
    roster = lcu_stats.resolve_roster(matches, {})
    return lcu_stats.build_payload(roster, matches, champs, {})


def main() -> int:
    parser = argparse.ArgumentParser(description="Supabase storage for Rift Report")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="show table counts")
    push = sub.add_parser("push", help="upsert local cache/imports into Supabase")
    push.add_argument("--json", metavar="PATH", help="push this payload instead of the cache")
    push.add_argument("--import", dest="import_file", metavar="PATH",
                      help="copy an export bundle into imports/ first")
    pull = sub.add_parser("pull", help="download Supabase data as a dashboard payload")
    pull.add_argument("--out", metavar="PATH", help="write payload JSON here")
    sub.add_parser("schema", help="print the SQL schema")

    args = parser.parse_args()

    if args.command == "schema":
        print(SCHEMA_FILE.read_text(encoding="utf-8"))
        return 0

    if not configured():
        print("error: Supabase is not configured.")
        print("Set SUPABASE_URL and SUPABASE_SERVICE_KEY in .env "
              f"({ENV_FILE}) or the environment.")
        return 1

    try:
        if args.command == "status":
            print(json.dumps(status(), indent=2, ensure_ascii=False))
            return 0

        if args.command == "push":
            if args.import_file:
                source = Path(args.import_file)
                IMPORTS_DIR.mkdir(exist_ok=True)
                target = IMPORTS_DIR / source.name
                target.write_bytes(source.read_bytes())
                print(f"copied {source} -> {target}")

            if args.json:
                payload = json.loads(Path(args.json).read_text(encoding="utf-8"))
            else:
                payload = build_local_payload()
            counts = push_payload(payload)
            print(f"pushed {counts['players']} players, {counts['matches']} matches, "
                  f"{counts['participants']} participants")
            return 0

        if args.command == "pull":
            payload = pull_payload()
            text = json.dumps(payload, ensure_ascii=False, indent=1)
            if args.out:
                out = Path(args.out)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                print(f"wrote {out} ({len(payload['matches'])} matches, "
                      f"{len(payload['players'])} players)")
            else:
                print(text)
            return 0
    except Exception as exc:  # noqa: BLE001
        print(f"error: {exc}")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
