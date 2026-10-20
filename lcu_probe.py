#!/usr/bin/env python3
"""Probe the League Client Update (LCU) API and dump real JSON shapes.

Read-only: only GET requests. Never prints the lockfile password or the
Authorization header.

Usage:
    python lcu_probe.py
    python lcu_probe.py --pages 5
    python lcu_probe.py --game-id 1234567890
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

DEBUG_DIR = Path(__file__).resolve().parent / "lcu_debug"

# Console may default to cp1252 on Windows; Riot IDs can contain non-ASCII.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

COMMON_PATHS = [
    r"C:\Riot Games\League of Legends\lockfile",
    r"C:\Program Files\Riot Games\League of Legends\lockfile",
    r"D:\Riot Games\League of Legends\lockfile",
    r"E:\Riot Games\League of Legends\lockfile",
]


def find_lockfile() -> Path | None:
    env = os.environ.get("LEAGUE_LOCKFILE")
    if env and Path(env).is_file():
        return Path(env)

    for candidate in COMMON_PATHS:
        path = Path(candidate)
        if path.is_file():
            return path

    # Fallback: find LeagueClientUx.exe via the process list and look next to it.
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
    # <process>:<pid>:<port>:<password>:<protocol>
    parts = path.read_text(encoding="utf-8").strip().split(":")
    if len(parts) < 5:
        raise ValueError("Unexpected lockfile format")
    return {
        "process": parts[0],
        "pid": parts[1],
        "port": parts[2],
        "password": parts[3],
        "protocol": ":".join(parts[4:]),
    }


class LcuClient:
    def __init__(self, lock: dict):
        self.port = lock["port"]
        self.protocol = lock["protocol"]
        self.base = f"{self.protocol}://127.0.0.1:{self.port}"
        token = base64.b64encode(f"riot:{lock['password']}".encode()).decode()
        self._auth = f"Basic {token}"
        self._ctx = ssl._create_unverified_context()

    def get(self, path: str):
        request = urllib.request.Request(
            self.base + path,
            headers={"Authorization": self._auth, "Accept": "application/json"},
        )
        with urllib.request.urlopen(request, context=self._ctx, timeout=20) as response:
            raw = response.read()
        if not raw:
            return None
        return json.loads(raw.decode("utf-8"))


def save(name: str, payload) -> Path:
    DEBUG_DIR.mkdir(exist_ok=True)
    path = DEBUG_DIR / name
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def keys_of(value) -> list[str]:
    return sorted(value.keys()) if isinstance(value, dict) else []


def main() -> int:
    parser = argparse.ArgumentParser(description="Probe LCU endpoints")
    parser.add_argument("--pages", type=int, default=2, help="match-history pages of 20")
    parser.add_argument("--game-id", type=str, default=None, help="inspect one game id")
    args = parser.parse_args()

    lockfile = find_lockfile()
    if not lockfile:
        print("LCU lockfile not found. Is the League client open and logged in?")
        return 1
    print(f"lockfile: {lockfile}")

    lock = read_lockfile(lockfile)
    print(f"port: {lock['port']}  protocol: {lock['protocol']}  pid: {lock['pid']}")
    client = LcuClient(lock)

    # 1. Current summoner
    try:
        summoner = client.get("/lol-summoner/v1/current-summoner")
    except urllib.error.HTTPError as exc:
        print(f"current-summoner failed: HTTP {exc.code}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"current-summoner failed: {exc}")
        return 1

    save("current-summoner.json", summoner)
    game_name = summoner.get("gameName") or summoner.get("displayName")
    tag_line = summoner.get("tagLine") or ""
    puuid = summoner.get("puuid")
    print(f"summoner: {game_name}#{tag_line}")
    print(f"puuid: {puuid}")
    print(f"summoner keys: {keys_of(summoner)}")

    # 2. Match history, paginated
    games: list[dict] = []
    for page in range(args.pages):
        start = page * 20
        path = (
            "/lol-match-history/v1/products/lol/current-summoner/matches"
            f"?begIndex={start}&endIndex={start + 20}"
        )
        try:
            data = client.get(path)
        except Exception as exc:  # noqa: BLE001
            print(f"match-history page {page} failed: {exc}")
            break
        if page == 0:
            save("match-history-page0.json", data)
            print(f"match-history top keys: {keys_of(data)}")
            if isinstance(data, dict) and isinstance(data.get("games"), dict):
                print(f"games keys: {keys_of(data['games'])}")
        batch = ((data or {}).get("games") or {}).get("games") or []
        games.extend(batch)
        print(f"page {page}: {len(batch)} games")
        if len(batch) < 20:
            break

    print(f"total games: {len(games)}")

    queue_counts: dict[int, int] = {}
    for game in games:
        qid = game.get("queueId")
        queue_counts[qid] = queue_counts.get(qid, 0) + 1
    print("queue ids: ", dict(sorted(queue_counts.items(), key=lambda kv: str(kv[0]))))
    print(f"queue 2400 present: {2400 in queue_counts}")
    if games:
        print(f"game summary keys: {keys_of(games[0])}")

    # 3. One match detail
    game_id = args.game_id
    if not game_id:
        mayhem = [g for g in games if g.get("queueId") == 2400]
        target = (mayhem or games or [{}])[0]
        game_id = target.get("gameId")
        if game_id is not None:
            print(
                f"sample summary: gameId={game_id} queueId={target.get('queueId')} "
                f"creation={target.get('gameCreation')} duration={target.get('gameDuration')}"
            )

    if game_id:
        try:
            detail = client.get(f"/lol-match-history/v1/games/{game_id}")
            save(f"game-{game_id}.json", detail)
            print(f"game detail keys: {keys_of(detail)}")
            participants = (detail or {}).get("participants") or []
            print(f"participants: {len(participants)}")
            if participants:
                p = participants[0]
                print(f"participant keys: {keys_of(p)}")
                print(f"participant stats keys: {keys_of(p.get('stats'))}")
        except Exception as exc:  # noqa: BLE001
            print(f"game detail failed: {exc}")

    # 4. Optional: friend puuid match history support
    print("\nraw samples written to:", DEBUG_DIR)
    return 0


if __name__ == "__main__":
    sys.exit(main())
