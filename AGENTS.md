# AGENTS.md — Rift Report / LoL Friend Stats handoff

## Vietnamese TL;DR

Dự án thống kê **ARAM: Mayhem** cho nhóm bạn. Toàn bộ source nằm trong repo
này: `lcu_probe.py`, `lcu_stats.py`, `server.py`, `web/`.

Trạng thái: **đã chạy thật** trên client patch 16.20 — queue `2400` có trong
match history, cache bất biến theo `gameId`, dashboard live + fallback demo.

Chạy:

```powershell
python lcu_stats.py
python server.py
# http://127.0.0.1:8000
```

Roster thật nằm trong `players.txt` local (không commit). LCU chỉ trả ~20 trận
gần nhất mỗi tài khoản, nên dữ liệu tích luỹ dần qua mỗi lần sync; muốn có
lịch sử sâu hơn cần export từ client của từng người rồi merge.

Không dùng lại Riot API key cũ (đã trả `401 Unknown apikey`). LCU không cần key.
Không commit lockfile/password/key. Chỉ đọc dữ liệu sau trận, không automate
game.

---

## 1. Mission

Build a private, local stats dashboard for a group of five League of Legends
friends, focused on **ARAM: Mayhem (queue 2400)**.

The dashboard should answer:

- Who deals the most damage on Kai'Sa?
- Who is the most effective on Ezreal?
- Who has the highest loss rate?
- What are each player's champion pool, KDA, DPM, and recent form?

The UI is implemented and runs on real LCU data, with the original mock
dashboard kept as an automatic fallback when the API/LCU is unavailable.

---

## 2. Where things are

The source now lives in this repo (not only on a separate PC):

```text
rift-analysis/
├── AGENTS.md          # this handoff / spec
├── README.md          # quick start (Vietnamese)
├── lcu_probe.py       # LCU probe (GET only)
├── lcu_stats.py       # collector + cache + aggregation + selftest
├── server.py          # stdlib HTTP server, 127.0.0.1:8000
├── players.txt        # real roster (LOCAL ONLY, gitignored)
├── cache/
│   ├── lcu/           # immutable match detail JSON per gameId
│   └── ddragon/       # champion id → key (Data Dragon 16.20.1)
├── lcu_debug/         # raw probe output (gitignored)
└── web/
    ├── index.html
    ├── styles.css
    ├── app.js
    ├── demo-data.js   # deterministic mock fallback (590 matches)
    └── champions.js   # 173 champions from Data Dragon 16.20.1
```

Nothing here requires npm or a build step. No secrets are committed.

---

## 3. Current state

**Status: working end-to-end on a real client (patch 16.20.824).**

### Key findings from the live LCU

- Queue `2400` **is** present in match history.
- `/lol-match-history/v1/products/lol/current-summoner/matches` ignores
  `begIndex`/`endIndex` on this build: it always returns the recent window
  (21 games, 20 of them Mayhem + 3 Practice Tool in one probe). Plan for
  incremental accumulation.
- History summaries contain only the logged-in participant; **full 10-player
  data requires `/lol-match-history/v1/games/{gameId}`**.
- Identity fields present: `player.gameName`, `player.tagLine`, `player.puuid`
  (`summonerName` is empty). Game duration is in seconds; `gameCreation` is ms.
- `playerAugment1..6` exist in `stats`; the UI does not show them yet.

### Collector (`lcu_stats.py`)

- Stdlib only. `find_lockfile()` (env `LEAGUE_LOCKFILE`, common paths, process
  path fallback), `LcuClient` with basic auth + unverified local SSL.
- Caches immutable details in `cache/lcu/<gameId>.json` (atomic write) and never
  refetches.
- Roster from `players.txt` (Riot ID lines), resolved to puuid from match data;
  falls back to auto-discovery of teammates with ≥ 2 shared games.
- Data Dragon id → champion key, cached 7 days in `cache/ddragon/`.
- `build_payload()` emits the §7 shape; `summarize()` prints a CLI table;
  `--selftest` covers aggregation offline.

### Server (`server.py`)

- `ThreadingHTTPServer` on `127.0.0.1`, serves `web/` and the API.
- Auto-syncs at most every 120 s; serves cache if LCU is down. Path traversal is
  blocked; no directory listing.
- `GET /api/stats`, `GET /api/status`, `POST /api/sync`, optional `--no-sync`.

### Web

- Vanilla HTML/CSS/JS, no build step. Void Hextech design, responsive at
  390/768/1024/1440; verified with Playwright + Edge.
- Data fetched from `/api/stats`; falls back to `demo-data.js` (590 deterministic
  matches) when the API is unreachable, with a banner and a "Demo data" badge.
- Features: KPI cards, Kai'Sa/Ezreal spotlight, damage ranking (total/avg/DPM),
  top performer, loss radar, insights, sortable/filterable champion table, player
  cards + drawer (focus trap, Escape, focus restore), recent matches, mobile
  menu, sync button.
- Verified: no JS errors, no horizontal overflow at 390 px, live and fallback
  modes both render.

### Players

`players.txt` holds the real roster locally (gitignored, never in this public
repo). The collector always includes the logged-in account.

### Riot API key

- The old Development key returned `401 {"message":"Unknown apikey"}`. Not used.
- LCU needs no key. Do not put API keys in the repo or browser.

---

## 4. Decisions and constraints

1. **Data source for Mayhem is LCU.**
   Riot Match-V5 does not expose queue `2400` (ARAM: Mayhem). A Personal or
   Production key will not change that. Do not build the production path around
   Match-V5 for Mayhem.

2. **League client must be running.**
   LCU is only available while the client is open and logged in. The `lockfile`
   exists only then. The collector must run on the same machine as the client.

3. **LCU sees the logged-in account's history.**
   A match detail contains all 10 participants, so shared games include all five
   friends. A friend's solo Mayhem games are only in that friend's own client
   history.

   Pick one:
   - **A. Shared games only** — simplest; one client covers the group.
   - **B. Per-friend export** — each friend runs a small exporter on their own
     client; merge JSON by `gameId`. Best data coverage.
   - **C. Hybrid** — Riot API for classic ARAM `450` + LCU for Mayhem shared
     games.

   Confirm with the user before implementing the multi-player merge.

4. **Read-only.**
   Only read post-game data. Do not automate gameplay, input, lobby actions, or
   anything that could affect a live game.

5. **Local-only.**
   Bind the local server to `127.0.0.1`. Do not expose LCU or the server through
   ngrok or a public tunnel. The LCU password is a local secret.

6. **No secrets in git.**
   Never commit `lockfile`, LCU password, Riot API key, or real player data to a
   public repo. This handoff repo is public; do not add real Riot IDs or personal
   data.

---

## 5. LCU protocol

### Lockfile

Typical content:

```text
LeagueClient:12345:54321:abcdefghijklmnop:https
```

Format:

```text
<process>:<pid>:<port>:<password>:<protocol>
```

Common locations:

```text
C:\Riot Games\League of Legends\lockfile
C:\Program Files\Riot Games\League of Legends\lockfile
```

Also support an env override:

```powershell
$env:LEAGUE_LOCKFILE = "D:\...\lockfile"
```

If not found, locate `LeagueClientUx.exe` via its process path and look for
`lockfile` in the install directory.

### HTTP

Base URL:

```text
https://127.0.0.1:<port>
```

Basic auth:

```text
username: riot
password: <lockfile password>
```

The certificate is self-signed. Use an unverified SSL context **only** for
`127.0.0.1`.

### Endpoints to probe first

```text
GET /lol-summoner/v1/current-summoner
GET /lol-match-history/v1/products/lol/current-summoner/matches?begIndex=0&endIndex=20
GET /lol-match-history/v1/games/{gameId}
```

Also test (may or may not work for friends):

```text
GET /lol-match-history/v1/products/lol/{puuid}/matches?begIndex=0&endIndex=20
```

Optional champion catalog:

```text
GET /lol-champions/v1/owned-champions-minimal
```

**Do not assume JSON shapes.** Probe and print keys/samples first. LCU is
undocumented and changes between patches.

Known likely shapes:

- Match list: `{ "games": { "games": [ ... ] } }`
- Game summary: `gameId`, `queueId`, `gameCreation` (ms), `gameDuration` (s)
- Game detail: `participants[]` with `puuid`, `championId`, `stats`
- Stats: `win`, `kills`, `deaths`, `assists`,
  `totalDamageDealtToChampions`

Identity fields vary by patch: `gameName`, `tagLine`, `summonerName`,
`riotIdGameName`, `riotIdTagline`.

### Auth sketch

```python
import base64
import ssl
import urllib.request

token = base64.b64encode(f"riot:{password}".encode()).decode()
request = urllib.request.Request(
    f"https://127.0.0.1:{port}/lol-summoner/v1/current-summoner",
    headers={"Authorization": f"Basic {token}", "Accept": "application/json"},
)
with urllib.request.urlopen(
    request, context=ssl._create_unverified_context(), timeout=10
) as response:
    data = response.read()
```

Do not print the password or the Authorization header.

---

## 6. Implementation plan

### Step 1 — `lcu_probe.py`

Create a small probe:

- Discover lockfile.
- Connect to LCU.
- Fetch current summoner.
- Fetch one page of match history.
- Print:
  - current summoner name/tag/puuid
  - number of games
  - queue IDs and counts
  - whether queue `2400` appears
  - keys of one game summary and one game detail
- Save raw JSON samples to `lcu_debug/` (gitignore this folder).

Run it with League open. Use the output to adapt the collector.

### Step 2 — `lcu_stats.py`

Implement:

- `find_lockfile()`
- `LcuClient` with basic auth and unverified local SSL
- `get_current_summoner()`
- `get_match_history(page_size=20, max_pages=...)`
- `get_match_detail(game_id)`
- filter `queueId == 2400`
- cache details in `cache/lcu/<gameId>.json` (atomic write)
- map `championId` to Data Dragon champion key
- extract only the group's participants (by puuid / Riot ID)
- aggregate by player and champion:
  - games, wins, losses
  - kills, deaths, assists
  - damage to champions
  - duration seconds
  - avgDamage, KDA, winrate, lossrate, DPM
- output JSON matching the web data model
- optional CLI table output for debugging

Reuse the aggregation/report patterns from `lol_stats.py` where possible.

### Step 3 — `server.py`

Use Python stdlib only:

- `http.server.ThreadingHTTPServer`, bound to `127.0.0.1`.
- Serve `web/` static files.
- `GET /api/stats?count=...&champion=...` → JSON data model.
- `GET /api/status` → LCU connection + cache status.
- Optional `POST /api/sync` → refresh LCU data.
- Cache LCU match details; do not refetch immutable games.
- On LCU error, return a clear JSON error; the frontend should fall back to mock
  data or show a banner.

### Step 4 — Wire the web

Current `app.js` expects:

```js
window.RIFT_DEMO = { players, champions, matches, queues }
```

Options:

- **A. Server-generated JS**: serve `/api/data.js` that sets
  `window.RIFT_DEMO = {...}`; `index.html` loads it instead of `demo-data.js`.
- **B. Fetch in app.js**: make `init()` async, load `/api/stats`, then build the
  view model; fall back to `demo-data.js` if the fetch fails.
- **C. Generated live file**: `lcu_stats.py` writes `web/live-data.js`; loader
  script tries it first, then `demo-data.js`.

Prefer B or C so the mock dashboard still works without LCU.

Frontend changes:

- Replace hardcoded “5 người” copy with `DATA.players.length` where needed.
- Change the demo badge to “LCU LIVE” when real data is loaded.
- Keep the “Demo data” badge for mock mode.
- Update the section subtitles to say ARAM: Mayhem (LCU) for real data.
- Handle a player count of 3–5.
- Keep the existing responsive/accessibility behavior.

### Step 5 — Multi-player

Implement only after confirming the chosen option:

- Shared-only: one LCU client; filter matches where all known friends appear
  (or include the current user + friends present).
- Per-friend export: `lcu_export.py --out friend.json`; merge by `gameId`,
  dedupe participant records, then build the dashboard payload.
- Hybrid: Riot API for `450`, LCU for `2400`; merge matches by ID.

Do not query other players' data without their consent.

---

## 7. Data model

Target JSON for the web:

```json
{
  "generatedAt": "2026-10-20T12:00:00Z",
  "players": [
    {
      "id": "player1",
      "name": "Player One",
      "tag": "TAG1",
      "initials": "P1",
      "role": "ADC",
      "c1": "#8B5CF6",
      "c2": "#22D3EE"
    }
  ],
  "champions": {
    "Kaisa": {
      "key": "Kaisa",
      "name": "Kai'Sa",
      "title": "Daughter of the Void",
      "role": "Marksman",
      "color": "#8B5CF6",
      "splash": "https://ddragon.leagueoflegends.com/cdn/img/champion/splash/Kaisa_0.jpg",
      "tile": "https://ddragon.leagueoflegends.com/cdn/img/champion/tiles/Kaisa_0.jpg"
    }
  },
  "matches": [
    {
      "id": "2400_1234567890",
      "queueId": 2400,
      "timestamp": 1760000000000,
      "duration": 1800,
      "participants": [
        {
          "playerId": "player1",
          "champion": "Kaisa",
          "win": true,
          "kills": 10,
          "deaths": 3,
          "assists": 8,
          "damage": 32000
        }
      ]
    }
  ],
  "queues": { "2400": "ARAM: Mayhem" }
}
```

`app.js` filters `queueId === 2400` and aggregates this shape. Do not change the
shape unless you update `app.js` accordingly.

---

## 8. Champion mapping

LCU gives numeric `championId`. The web expects a champion key such as `Kaisa`,
`Ezreal`, `MonkeyKing`.

Use Data Dragon:

```text
https://ddragon.leagueoflegends.com/api/versions.json
https://ddragon.leagueoflegends.com/cdn/<version>/data/en_US/champion.json
```

Build:

```python
# champion.json data:
# "Kaisa": { "key": "145", "id": "Kaisa", "name": "Kai'Sa", ... }
id_to_key = {int(champ["key"]): champ["id"] for champ in data.values()}
```

The existing `web/champions.js` (Data Dragon 16.20.1) already has 173 champion
keys/images. For real data, you can extend it with the numeric mapping or let the
server resolve keys.

If a new champion appears, regenerate from the latest Data Dragon version.

---

## 9. Web frontend notes

- `index.html` loads `champions.js`, `demo-data.js`, `app.js`.
- `app.js` is an IIFE; `DATA = window.RIFT_DEMO`; `state` holds `limit`,
  `champion`, `metric`, `tableChampion`, `sort`.
- Render functions: `renderKpis`, `renderSpotlight`, `renderPerformer`,
  `renderLoss`, `renderInsights`, `renderTable`, `renderPlayers`,
  `renderSidebar`, `renderMatches`, `renderDrawer`.
- Interactions: champion tabs, metric switch, count select, table sort/filter,
  player drawer, mobile menu, demo sync. Keep them working.
- The mock data has 5 players and 173 champions; real data may have 3–5 players.
- The dashboard uses Data Dragon images; fallbacks are letters if an image fails.
- Do not introduce a build step or external JS chart library; the prototype is
  stdlib/vanilla and lightweight.
- Accessibility: preserve focus rings, `aria-sort`, tab roles, drawer focus trap,
  `prefers-reduced-motion`, and mobile no-horizontal-scroll behavior.

---

## 10. Testing checklist

Verified on 2026-10-20 against a live client (patch 16.20.824):

- [x] League client running; `lockfile` found.
- [x] Probe returns current summoner.
- [x] Match history contains queue `2400` games.
- [x] Match detail has 10 participants and stats fields.
- [x] Collector caches games and does not refetch.
- [x] Server serves the web at `http://127.0.0.1:8000`.
- [x] `/api/stats` returns the documented shape.
- [x] Web displays real data with 5 players.
- [x] Champion tabs, table sort/filter, count select still work.
- [x] Player drawer opens/closes; Escape works; focus returns.
- [x] Mobile 390px has no page-level horizontal overflow.
- [x] No JS exceptions.
- [x] Mock fallback still works when LCU/server is unavailable.

Not yet done:

- [ ] Multi-player merge (per-friend export / hybrid). Currently one LCU client:
      shared games plus the logged-in account's own games.
- [ ] Longer history than the client's recent window (accumulates per sync).

---

## 11. Security / Riot rules

- LCU `lockfile` contains a temporary password. Never log it or commit it.
- Bind only to `127.0.0.1`; do not expose LCU or the local server publicly.
- Do not use ngrok for LCU. If a public demo is ever needed, use mock data only.
- No game automation, no input injection, no Vanguard bypass.
- Only collect data for consenting friends.
- Do not resell or redistribute Riot data.
- LCU is undocumented; endpoints can break with a patch. Keep the Riot API CLI
  as a fallback for classic ARAM `450`.

---

## 12. Local roster (not committed)

The real Riot IDs live in the local `players.txt` (gitignored) and are
intentionally not listed in this public repo. The collector resolves them to
puuids from match data and always includes the logged-in account.

The web mock roster is fictional and unrelated:

```text
VoidWalker#VN2
BaronSteal#VN2
SupportDiff#VN2
FlashOnD#VN2
IntingSion#VN2
```

---

## 13. Handoff checklist

1. [x] Clone this repo on the LoL machine.
2. [x] Source lives in the repo (`lcu_probe.py`, `lcu_stats.py`, `server.py`, `web/`).
3. [x] Open League client and log in.
4. [x] Run `lcu_probe.py`; inspect raw JSON (`lcu_debug/`).
5. [x] Implement `lcu_stats.py`.
6. [x] Implement `server.py`.
7. [x] Wire the web to `/api/stats`; keep mock fallback.
8. [x] Test with the real roster (5 accounts, shared games + solo games).
9. [ ] Add per-friend exports / merge to capture friends' solo games.
10. [x] Update README with the final run command.

---

## 14. Known risks / resolved questions

- **Resolved:** LCU on 16.20 exposes queue `2400` in match history.
- **Resolved:** history summaries carry only the logged-in participant; details
  carry all 10, so fetching details is required.
- **Resolved:** identity fields are `player.gameName` / `player.tagLine` /
  `player.puuid`.
- **Resolved:** the client's history window is ~21 games and ignores
  `begIndex`/`endIndex`; accumulate via permanent detail cache.
- **Resolved:** the client is on the development machine; the collector and
  server run beside it.
- **Open:** which multi-player option the group wants (shared-only vs per-friend
  export vs hybrid). Shared-only is live today.
- **Open:** whether to surface augments. They are already collected in
  `cache/lcu/` (`playerAugment1..6`) but not rendered.
- **Open:** friends' solo Mayhem games require each friend to run an exporter on
  their own client.
