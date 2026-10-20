"""Offline tests for Supabase row mapping and export merging.

Run:  python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lcu_stats
import rift_db


def sample_payload():
    return {
        "source": "lcu",
        "players": [
            {"id": "player1", "puuid": "p1", "name": "Alpha", "tag": "0001",
             "role": "ADC", "c1": "#111111", "c2": "#222222"},
            {"id": "player2", "puuid": "p2", "name": "Beta", "tag": "0002",
             "role": "", "c1": "#333333", "c2": "#444444"},
        ],
        "matches": [
            {
                "id": "1001", "gameId": 1001, "queueId": 2400,
                "timestamp": 1760000000000, "duration": 1200, "version": "16.20",
                "participants": [
                    {"playerId": "player1", "puuid": "p1", "champion": "Kaisa",
                     "win": True, "kills": 10, "deaths": 2, "assists": 5,
                     "damage": 30000, "gold": 12000, "cs": 40, "champLevel": 18,
                     "teamId": 100, "augments": [1, 2]},
                    {"playerId": "player2", "puuid": "p2", "champion": "Ezreal",
                     "win": True, "kills": 4, "deaths": 5, "assists": 20,
                     "damage": 20000},
                ],
            }
        ],
    }


class PayloadToRowsTest(unittest.TestCase):
    def test_rows(self):
        players, matches, parts = rift_db.payload_to_rows(sample_payload())
        self.assertEqual(len(players), 2)
        self.assertEqual(matches[0]["game_id"], 1001)
        self.assertEqual(matches[0]["played_at"], "2025-10-09T08:53:20+00:00")
        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0]["augments"], [1, 2])
        self.assertEqual(parts[1]["cs"], 0)

    def test_skips_rows_without_puuid(self):
        payload = sample_payload()
        payload["matches"][0]["participants"] = [{"playerId": "player1", "champion": "Kaisa"}]
        _, matches, parts = rift_db.payload_to_rows(payload)
        self.assertEqual(len(matches), 1)
        self.assertEqual(parts, [])


class RowsToPayloadTest(unittest.TestCase):
    def setUp(self):
        self._orig = lcu_stats.champion_map
        lcu_stats.champion_map = lambda: {}

    def tearDown(self):
        lcu_stats.champion_map = self._orig

    def test_roundtrip(self):
        players, matches, parts = rift_db.payload_to_rows(sample_payload())
        payload = rift_db.rows_to_payload(players, matches, parts)
        self.assertEqual(len(payload["players"]), 2)
        self.assertEqual(len(payload["matches"]), 1)
        match = payload["matches"][0]
        self.assertEqual(match["gameId"], 1001)
        self.assertEqual(match["timestamp"], 1760000000000)
        self.assertEqual(len(match["participants"]), 2)
        self.assertEqual({p["champion"] for p in match["participants"]}, {"Kaisa", "Ezreal"})
        self.assertIn("Kaisa", payload["champions"])
        # Stable player ids are assigned from sorted names.
        self.assertEqual(payload["players"][0]["name"], "Alpha")

    def test_matches_without_roster_participants_are_dropped(self):
        players = [{"puuid": "p1", "name": "Alpha", "tag": "", "c1": None, "c2": None}]
        matches = [{"game_id": 1, "queue_id": 2400, "played_at": "2025-10-09T08:53:20+00:00",
                    "duration": 100, "game_version": ""}]
        payload = rift_db.rows_to_payload(players, matches, [])
        self.assertEqual(payload["matches"], [])
        self.assertEqual(len(payload["players"]), 1)


class ExportDocumentTest(unittest.TestCase):
    def test_accepts_bundle_list_and_raw(self):
        detail = {"gameId": 5, "participants": [{"puuid": "x"}]}
        self.assertEqual(len(lcu_stats._details_from_document(detail)), 1)
        self.assertEqual(len(lcu_stats._details_from_document([detail])), 1)
        self.assertEqual(
            len(lcu_stats._details_from_document({"type": "rift-export", "matches": [detail]})),
            1,
        )
        self.assertEqual(lcu_stats._details_from_document({"roster": []}), [])


class ImportMergeTest(unittest.TestCase):
    def test_imports_merge_by_game_id(self):
        original_imports = lcu_stats.IMPORTS_DIR
        original_cache = lcu_stats.CACHE_DIR
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            imports = root / "imports"
            imports.mkdir()
            lcu_stats.IMPORTS_DIR = imports
            lcu_stats.CACHE_DIR = root / "cache"
            try:
                (imports / "friend.json").write_text(json.dumps({
                    "type": "rift-export",
                    "roster": [{"puuid": "p9", "name": "Nine", "tag": "9999"}],
                    "matches": [
                        {"gameId": 1, "queueId": 2400, "participants": [{"puuid": "p9"}]},
                        {"gameId": 2, "queueId": 2400, "participants": [{"puuid": "p9"}]},
                    ],
                }), encoding="utf-8")
                details = lcu_stats.load_cached_matches()
                self.assertEqual({d["gameId"] for d in details}, {1, 2})
                roster = lcu_stats.load_import_rosters()
                self.assertEqual(roster[0]["puuid"], "p9")
            finally:
                lcu_stats.IMPORTS_DIR = original_imports
                lcu_stats.CACHE_DIR = original_cache


if __name__ == "__main__":
    unittest.main()
