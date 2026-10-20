#!/usr/bin/env python3
"""Collect ARAM: Mayhem (queue 2400) stats from the League Client (LCU).

Read-only: only GET requests against 127.0.0.1. The lockfile password is never
printed or logged.

Usage:
    python lcu_stats.py                 # sync + print summary table
    python lcu_stats.py --json out.json # write the web payload
    python lcu_stats.py --selftest      # offline aggregation test

The LCU only exposes roughly the last 20 games per account, so every run
permanently caches full match details in ``cache/lcu/<gameId>.json``. Stats are
aggregated from the whole cache, which means the dataset grows over time and can
also absorb per-friend exports dropped into the same folder.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CACHE_DIR = ROOT / "cache" / "lcu"
IMPORTS_DIR = ROOT / "imports"
DRAGON_CACHE = ROOT / "cache" / "ddragon"
ROSTER_FILE = ROOT / "players.txt"
MAYHEM_QUEUE = 2400

QUEUE_NAMES = {
    2400: "ARAM: Mayhem",
    450: "ARAM",
    400: "Normal Draft",
    420: "Ranked Solo/Duo",
    430: "Normal Blind",
    440: "Ranked Flex",
    3140: "Practice Tool",
}

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COMMON_LOCKFILES = [
    r"C:\Riot Games\League of Legends\lockfile",
    r"C:\Program Files\Riot Games\League of Legends\lockfile",
    r"D:\Riot Games\League of Legends\lockfile",
    r"E:\Riot Games\League of Legends\lockfile",
]

# Deterministic accent colours for player cards.
PALETTE = [
    ("#8B5CF6", "#22D3EE"),
    ("#F59E0B", "#EF4444"),
    ("#10B981", "#3B82F6"),
    ("#EC4899", "#8B5CF6"),
    ("#06B6D4", "#A3E635"),
    ("#F97316", "#FACC15"),
]


class LcuUnavailable(RuntimeError):
    pass


# --------------------------------------------------------------------------- #
# Lockfile / HTTP
# --------------------------------------------------------------------------- #
def find_lockfile() -> Path | None:
    env = os.environ.get("LEAGUE_LOCKFILE")
    if env and Path(env).is_file():
        return Path(env)

    for candidate in COMMON_LOCKFILES:
        path = Path(candidate)
        if path.is_file():
            return path

    try:
        import subprocess

        out = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance Win32_Process -Filter \"name='LeagueClientUx.exe'\" "
                "| Select-Object -ExpandProperty ExecutablePath",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        ).stdout
        for line in out.splitlines():
            exe = Path(line.strip())
            if exe.name.lower() == "leagueclientux.exe":
                lockfile = exe.parent / "lockfile"
                if lockfile.is_file():
                    return lockfile
    except Exception:
        pass

    return None


def read_lockfile(path: Path) -> dict:
    parts = path.read_text(encoding="utf-8").strip().split(":")
    if len(parts) < 5:
        raise LcuUnavailable("Unexpected lockfile format")
    return {
        "process": parts[0],
        "pid": parts[1],
        "port": int(parts[2]),
        "password": parts[3],
        "protocol": ":".join(parts[4:]),
    }


class LcuClient:
    def __init__(self, lock: dict):
        self.lock = lock
        self.port = lock["port"]
        self.protocol = lock["protocol"]
        self.base = f"{self.protocol}://127.0.0.1:{self.port}"
        token = base64.b64encode(f"riot:{lock['password']}".encode()).decode()
        self._auth = f"Basic {token}"
        self._ctx = ssl._create_unverified_context()

    def get(self, path: str, timeout: int = 20):
        request = urllib.request.Request(
            self.base + path,
            headers={"Authorization": self._auth, "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, context=self._ctx, timeout=timeout) as response:
            raw = response.read()
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))

    # -- domain helpers ---------------------------------------------------- #
    def current_summoner(self) -> dict:
        return self.get("/lol-summoner/v1/current-summoner") or {}

    def recent_matches(self, pages: int = 3) -> list[dict]:
        """Return recent match summaries.

        Some client builds ignore begIndex/endIndex and always return the same
        recent window; de-duplicating by gameId keeps this safe either way.
        """
        seen: dict[str, dict] = {}
        for page in range(pages):
            start = page * 20
            try:
                data = self.get(
                    "/lol-match-history/v1/products/lol/current-summoner/matches"
                    f"?begIndex={start}&endIndex={start + 20}"
                )
            except Exception:
                break
            batch = ((data or {}).get("games") or {}).get("games") or []
            for game in batch:
                seen.setdefault(str(game.get("gameId")), game)
            if len(batch) < 20:
                break
        return list(seen.values())

    def match_detail(self, game_id) -> dict | None:
        try:
            return self.get(f"/lol-match-history/v1/games/{game_id}")
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise


# --------------------------------------------------------------------------- #
# Cache
# --------------------------------------------------------------------------- #
def atomic_write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def cache_path(game_id) -> Path:
    return CACHE_DIR / f"{game_id}.json"


def load_cached_matches() -> list[dict]:
    """Load immutable match details from the local cache plus imported exports.

    ``cache/lcu`` is written by this collector. ``imports/*.json`` holds
    per-friend exports produced by ``lcu_export.py`` on another client. Matches
    are de-duplicated by gameId; the local cache wins on conflict.
    """
    by_id: dict[str, dict] = {}

    for directory in (IMPORTS_DIR, CACHE_DIR):
        if not directory.exists():
            continue
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            for detail in _details_from_document(data):
                game_id = detail.get("gameId")
                if game_id is None:
                    continue
                key = str(game_id)
                if key not in by_id or directory == CACHE_DIR:
                    by_id[key] = detail
    return list(by_id.values())


def _details_from_document(data) -> list[dict]:
    """Accept a raw detail, a list of details, or an export bundle."""
    if isinstance(data, list):
        return [d for d in data if isinstance(d, dict)]
    if not isinstance(data, dict):
        return []
    if isinstance(data.get("matches"), list):
        return [d for d in data["matches"] if isinstance(d, dict)]
    if data.get("gameId") is not None and data.get("participants"):
        return [data]
    return []


def load_import_rosters() -> list[dict]:
    """Roster hints embedded in export bundles (name/tag/puuid)."""
    entries: list[dict] = []
    if not IMPORTS_DIR.exists():
        return entries
    for path in IMPORTS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict):
            continue
        for entry in data.get("roster") or []:
            if isinstance(entry, dict) and entry.get("puuid"):
                entries.append(
                    {
                        "puuid": entry["puuid"],
                        "name": entry.get("name"),
                        "tag": entry.get("tag") or "",
                    }
                )
    return entries


# --------------------------------------------------------------------------- #
# Data Dragon champion map
# --------------------------------------------------------------------------- #
def champion_map(version: str | None = None) -> dict[int, dict]:
    """Return {championId: {key, name, title, ...}} using Data Dragon."""
    DRAGON_CACHE.mkdir(parents=True, exist_ok=True)
    mapping_file = DRAGON_CACHE / "id_to_champion.json"
    ttl = 7 * 24 * 3600

    if mapping_file.exists() and time.time() - mapping_file.stat().st_mtime < ttl:
        try:
            raw = json.loads(mapping_file.read_text(encoding="utf-8"))
            return {int(k): v for k, v in raw.items()}
        except Exception:
            pass

    try:
        if not version:
            with urllib.request.urlopen(
                "https://ddragon.leagueoflegends.com/api/versions.json", timeout=20
            ) as response:
                versions = json.loads(response.read().decode("utf-8"))
            version = versions[0]
        url = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))["data"]
        mapping = {
            int(champ["key"]): {
                "key": champ["id"],
                "name": champ["name"],
                "title": champ["title"],
                "tags": champ.get("tags", []),
                "version": version,
            }
            for champ in data.values()
        }
        atomic_write_json(mapping_file, {str(k): v for k, v in mapping.items()})
        return mapping
    except Exception as exc:
        if mapping_file.exists():
            try:
                raw = json.loads(mapping_file.read_text(encoding="utf-8"))
                return {int(k): v for k, v in raw.items()}
            except Exception:
                pass
        print(f"warning: champion map unavailable ({exc}); using numeric ids")
        return {}


# --------------------------------------------------------------------------- #
# Roster
# --------------------------------------------------------------------------- #
def load_roster() -> list[dict]:
    """Read players.txt: one entry per line, ``GameName#TAG`` or a puuid.

    Blank lines and ``#`` comments are ignored. Returns entries with
    ``name``/``tag``/``puuid`` where available.
    """
    if not ROSTER_FILE.exists():
        return []
    roster = []
    for line in ROSTER_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "#" in line and len(line.split("#", 1)[0]) > 0 and len(line.split("#", 1)[1]) > 0:
            name, tag = line.split("#", 1)
            roster.append({"name": name.strip(), "tag": tag.strip(), "puuid": None})
        elif len(line) > 20 and "-" in line:
            roster.append({"name": None, "tag": None, "puuid": line})
        else:
            roster.append({"name": line, "tag": "", "puuid": None})
    return roster


def player_identity(detail: dict) -> dict[int, dict]:
    """participantId -> player identity for one match detail."""
    out = {}
    for entry in detail.get("participantIdentities") or []:
        player = entry.get("player") or {}
        out[entry.get("participantId")] = {
            "puuid": player.get("puuid"),
            "name": player.get("gameName") or player.get("summonerName") or "",
            "tag": player.get("tagLine") or "",
            "icon": player.get("profileIcon"),
        }
    return out


def discover_group(matches: list[dict], me_puuid: str | None, min_shared: int = 2) -> list[dict]:
    """Find teammates who repeatedly play with the logged-in account.

    Used when players.txt is missing. Only same-team participants count, so
    opponents are never pulled into the group.
    """
    counts: dict[str, int] = defaultdict(int)
    identities: dict[str, dict] = {}
    for detail in matches:
        ids = player_identity(detail)
        participants = detail.get("participants") or []
        me = None
        for p in participants:
            ident = ids.get(p.get("participantId"), {})
            if me_puuid and ident.get("puuid") == me_puuid:
                me = p
                break
        if not me:
            continue
        for p in participants:
            ident = ids.get(p.get("participantId"), {})
            puuid = ident.get("puuid")
            if not puuid or puuid == me_puuid:
                continue
            if p.get("teamId") == me.get("teamId"):
                counts[puuid] += 1
                identities[puuid] = ident

    group = []
    for puuid, count in counts.items():
        if count >= min_shared:
            ident = identities[puuid]
            group.append(
                {
                    "name": ident.get("name"),
                    "tag": ident.get("tag"),
                    "puuid": puuid,
                    "sharedGames": count,
                }
            )
    group.sort(key=lambda item: -item["sharedGames"])
    return group


def resolve_roster(matches: list[dict], me: dict) -> list[dict]:
    """Merge players.txt, export-bundle rosters, and auto-discovery.

    Always includes the logged-in user.
    """
    entries = load_roster()
    by_puuid: dict[str, dict] = {}

    for entry in entries:
        if entry.get("puuid"):
            by_puuid[entry["puuid"]] = dict(entry)
        else:
            entry["_pending"] = True
            by_puuid[f"pending:{entry['name']}#{entry['tag']}"] = entry

    # Roster hints carried by per-friend exports.
    for entry in load_import_rosters():
        puuid = entry["puuid"]
        if puuid not in by_puuid:
            by_puuid[puuid] = {
                "puuid": puuid,
                "name": entry.get("name"),
                "tag": entry.get("tag") or "",
            }

    # Resolve pending Riot IDs against identities seen in cached matches.
    for detail in matches:
        for ident in player_identity(detail).values():
            key = f"pending:{ident['name']}#{ident['tag']}"
            if key in by_puuid:
                entry = by_puuid.pop(key)
                entry.pop("_pending", None)
                entry["puuid"] = ident["puuid"]
                entry["name"] = ident["name"]
                entry["tag"] = ident["tag"]
                by_puuid[ident["puuid"]] = entry

    has_named = any(not key.startswith("pending:") for key in by_puuid)
    if not has_named:
        for item in discover_group(matches, me.get("puuid")):
            by_puuid[item["puuid"]] = item

    me_puuid = me.get("puuid")
    if me_puuid and me_puuid not in by_puuid:
        by_puuid[me_puuid] = {
            "name": me.get("gameName") or me.get("displayName") or "Me",
            "tag": me.get("tagLine") or "",
            "puuid": me_puuid,
        }
    elif me_puuid:
        # Prefer the freshest Riot ID from the client.
        by_puuid[me_puuid]["name"] = me.get("gameName") or by_puuid[me_puuid].get("name")
        by_puuid[me_puuid]["tag"] = me.get("tagLine") or by_puuid[me_puuid].get("tag")

    # Drop unresolved pending entries (friend never seen in cache yet).
    roster = [v for k, v in by_puuid.items() if not k.startswith("pending:")]

    # Current user first, then discovery order.
    roster.sort(key=lambda p: (p.get("puuid") != me_puuid, -p.get("sharedGames", 0)))
    for index, player in enumerate(roster):
        player["id"] = f"player{index + 1}"
        player["initials"] = initials(player.get("name") or "?")
        c1, c2 = PALETTE[index % len(PALETTE)]
        player["c1"] = c1
        player["c2"] = c2
        player["role"] = player.get("role") or ""
    return roster


def initials(name: str) -> str:
    parts = [p for p in name.replace("_", " ").split() if p]
    if not parts:
        return "??"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def to_web_match(detail: dict, roster_by_puuid: dict[str, dict], champs: dict[int, dict]) -> dict | None:
    if detail.get("queueId") != MAYHEM_QUEUE:
        return None
    ids = player_identity(detail)
    participants = []
    for p in detail.get("participants") or []:
        ident = ids.get(p.get("participantId"), {})
        player = roster_by_puuid.get(ident.get("puuid"))
        if not player:
            continue
        stats = p.get("stats") or {}
        champ_id = p.get("championId")
        champ = champs.get(champ_id) or {}
        participants.append(
            {
                "playerId": player["id"],
                "puuid": ident.get("puuid"),
                "summonerName": f"{ident.get('name')}#{ident.get('tag')}".strip("#"),
                "champion": champ.get("key") or f"Champion{champ_id}",
                "championName": champ.get("name") or f"Champion {champ_id}",
                "win": bool(stats.get("win")),
                "kills": int(stats.get("kills") or 0),
                "deaths": int(stats.get("deaths") or 0),
                "assists": int(stats.get("assists") or 0),
                "damage": int(stats.get("totalDamageDealtToChampions") or 0),
                "gold": int(stats.get("goldEarned") or 0),
                "cs": int(stats.get("totalMinionsKilled") or 0)
                + int(stats.get("neutralMinionsKilled") or 0),
                "champLevel": int(stats.get("champLevel") or 0),
                "items": [stats.get(f"item{i}") or 0 for i in range(7)],
                "teamId": p.get("teamId"),
                "augments": [
                    stats.get(f"playerAugment{i}") for i in range(1, 7)
                    if stats.get(f"playerAugment{i}")
                ],
            }
        )
    if not participants:
        return None
    return {
        "id": str(detail.get("gameId")),
        "gameId": detail.get("gameId"),
        "queueId": detail.get("queueId"),
        "timestamp": int(detail.get("gameCreation") or 0),
        "duration": int(detail.get("gameDuration") or 0),
        "version": detail.get("gameVersion"),
        "participants": participants,
    }


def build_payload(roster: list[dict], matches: list[dict], champs: dict[int, dict], me: dict) -> dict:
    roster_by_puuid = {p["puuid"]: p for p in roster if p.get("puuid")}
    web_matches = []
    for detail in matches:
        match = to_web_match(detail, roster_by_puuid, champs)
        if match:
            web_matches.append(match)
    web_matches.sort(key=lambda m: m["timestamp"], reverse=True)

    champion_entries = {}
    for champ in champs.values():
        key = champ["key"]
        champion_entries[key] = {
            "key": key,
            "name": champ["name"],
            "title": champ.get("title", ""),
            "role": (champ.get("tags") or ["Fighter"])[0],
            "splash": f"https://ddragon.leagueoflegends.com/cdn/img/champion/splash/{key}_0.jpg",
            "tile": f"https://ddragon.leagueoflegends.com/cdn/img/champion/tiles/{key}_0.jpg",
        }

    players = []
    for player in roster:
        players.append(
            {
                "id": player["id"],
                "puuid": player.get("puuid"),
                "name": player.get("name") or "Unknown",
                "tag": player.get("tag") or "",
                "initials": player.get("initials") or initials(player.get("name") or "?"),
                "role": player.get("role") or "",
                "c1": player.get("c1"),
                "c2": player.get("c2"),
            }
        )

    return {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "source": "lcu",
        "region": me.get("platformId") or "VN2",
        "players": players,
        "champions": champion_entries,
        "matches": web_matches,
        "queues": {str(MAYHEM_QUEUE): QUEUE_NAMES[MAYHEM_QUEUE]},
    }


def summarize(payload: dict) -> None:
    players = {p["id"]: p for p in payload["players"]}
    totals = defaultdict(lambda: {"games": 0, "wins": 0, "kills": 0, "deaths": 0,
                                  "assists": 0, "damage": 0, "seconds": 0})
    for match in payload["matches"]:
        for p in match["participants"]:
            row = totals[p["playerId"]]
            row["games"] += 1
            row["wins"] += 1 if p["win"] else 0
            row["kills"] += p["kills"]
            row["deaths"] += p["deaths"]
            row["assists"] += p["assists"]
            row["damage"] += p["damage"]
            row["seconds"] += match["duration"]

    print(f"\n{len(payload['matches'])} Mayhem matches, {len(players)} players")
    print(f"{'player':<22}{'G':>4}{'W':>4}{'WR':>7}{'KDA':>7}{'DPM':>8}{'AVG DMG':>10}")
    for pid, row in sorted(totals.items(), key=lambda kv: -kv[1]["games"]):
        name = f"{players[pid]['name']}#{players[pid]['tag']}"
        kda = (row["kills"] + row["assists"]) / max(row["deaths"], 1)
        dpm = row["damage"] / (row["seconds"] / 60) if row["seconds"] else 0
        avg = row["damage"] / row["games"] if row["games"] else 0
        wr = 100 * row["wins"] / row["games"] if row["games"] else 0
        print(f"{name[:21]:<22}{row['games']:>4}{row['wins']:>4}{wr:>6.1f}%{kda:>7.2f}{dpm:>8.0f}{avg:>10.0f}")


# --------------------------------------------------------------------------- #
# Sync
# --------------------------------------------------------------------------- #
def sync(pages: int = 3, verbose: bool = True) -> tuple[dict, dict]:
    lockfile = find_lockfile()
    if not lockfile:
        raise LcuUnavailable(
            "LCU lockfile not found. Open the League client and log in first."
        )
    client = LcuClient(read_lockfile(lockfile))
    me = client.current_summoner()
    if not me:
        raise LcuUnavailable("LCU did not return a current summoner (not logged in?)")

    if verbose:
        print(f"logged in as {me.get('gameName')}#{me.get('tagLine')}")

    summaries = client.recent_matches(pages=pages)
    mayhem = [s for s in summaries if s.get("queueId") == MAYHEM_QUEUE]
    if verbose:
        print(f"history: {len(summaries)} games, {len(mayhem)} Mayhem")

    new = 0
    for summary in mayhem:
        game_id = summary.get("gameId")
        if cache_path(game_id).exists():
            continue
        detail = client.match_detail(game_id)
        if detail:
            atomic_write_json(cache_path(game_id), detail)
            new += 1
    if verbose:
        print(f"new match details cached: {new}")

    matches = load_cached_matches()
    champs = champion_map()
    roster = resolve_roster(matches, me)
    payload = build_payload(roster, matches, champs, me)
    return payload, me


def selftest() -> int:
    """Offline test of aggregation with synthetic match details."""
    champs = {145: {"key": "Kaisa", "name": "Kai'Sa", "title": "Daughter of the Void",
                    "tags": ["Marksman"]}}
    roster = [
        {"id": "player1", "name": "Alpha", "tag": "0001", "puuid": "p1", "initials": "A"},
        {"id": "player2", "name": "Beta", "tag": "0002", "puuid": "p2", "initials": "B"},
    ]
    detail = {
        "gameId": 1, "queueId": 2400, "gameCreation": 1760000000000,
        "gameDuration": 1200, "gameVersion": "16.20",
        "participantIdentities": [
            {"participantId": 1, "player": {"puuid": "p1", "gameName": "Alpha", "tagLine": "0001"}},
            {"participantId": 2, "player": {"puuid": "p2", "gameName": "Beta", "tagLine": "0002"}},
            {"participantId": 3, "player": {"puuid": "px", "gameName": "Enemy", "tagLine": "x"}},
        ],
        "participants": [
            {"participantId": 1, "teamId": 100, "championId": 145,
             "stats": {"win": True, "kills": 10, "deaths": 2, "assists": 5,
                       "totalDamageDealtToChampions": 30000, "goldEarned": 12000,
                       "totalMinionsKilled": 40, "champLevel": 18}},
            {"participantId": 2, "teamId": 100, "championId": 145,
             "stats": {"win": True, "kills": 4, "deaths": 5, "assists": 20,
                       "totalDamageDealtToChampions": 20000}},
            {"participantId": 3, "teamId": 200, "championId": 999,
             "stats": {"win": False, "kills": 0, "deaths": 10, "assists": 1}},
        ],
    }
    match = to_web_match(detail, {p["puuid"]: p for p in roster}, champs)
    assert match and len(match["participants"]) == 2, "roster filter failed"
    assert match["participants"][0]["champion"] == "Kaisa", "champion map failed"
    assert match["duration"] == 1200, "duration failed"

    payload = build_payload(roster, [detail, detail], champs, {"puuid": "p1"})
    assert len(payload["matches"]) == 2, "payload match list failed"
    assert payload["players"][0]["initials"] == "A"
    summarize(payload)
    print("\nselftest OK")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="LCU ARAM: Mayhem stats collector")
    parser.add_argument("--json", metavar="PATH", help="write web payload JSON here")
    parser.add_argument("--pages", type=int, default=3, help="history pages to scan")
    parser.add_argument("--selftest", action="store_true", help="offline aggregation test")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    if args.selftest:
        return selftest()

    try:
        payload, _me = sync(pages=args.pages, verbose=not args.quiet)
    except LcuUnavailable as exc:
        print(f"error: {exc}")
        return 1

    summarize(payload)
    if args.json:
        path = Path(args.json)
        atomic_write_json(path, payload)
        print(f"\nwrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
