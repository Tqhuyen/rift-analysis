# Rift Report — LoL Friend Stats

Dashboard thống kê **ARAM: Mayhem** (queue `2400`) cho nhóm bạn, chạy hoàn toàn
cục bộ trên máy có League client. Không cần Riot API key, không build step,
không dependency ngoài Python standard library.

![Trạng thái](https://img.shields.io/badge/data-League%20Client%20(LCU)-8b5cf6)
![Python](https://img.shields.io/badge/python-3.10%2B-22d3ee)

---

## Chạy nhanh

```powershell
cd $HOME\rift-analysis

# 1. Mở League client và đăng nhập (bắt buộc với dữ liệu thật)

# 2. (tuỳ chọn) kiểm tra LCU + queue 2400
python lcu_probe.py

# 3. Thu thập dữ liệu vào cache
python lcu_stats.py

# 4. Chạy web
python server.py
# mở http://127.0.0.1:8000
```

`server.py` tự đồng bộ từ LCU khi mở trang (tối đa mỗi 2 phút). Nút **Đồng bộ**
trên web gọi `POST /api/sync`. Nếu LCU không chạy, web tự chuyển sang dữ liệu
demo và hiện banner — dashboard vẫn dùng được.

### Các tham số hữu ích

```powershell
python server.py --port 8000 --no-sync   # chỉ phục vụ cache, không gọi LCU
python lcu_stats.py --json cache/stats.json
python lcu_stats.py --selftest           # test aggregation offline
python lcu_probe.py --pages 3            # xem JSON thật từ LCU
```

---

## Thành phần

```text
rift-analysis/
├── lcu_probe.py     # probe LCU: summoner, history, match detail, queue 2400
├── lcu_export.py    # export Mayhem games từ máy của từng người
├── lcu_stats.py     # collector + aggregation, cache bất biến theo gameId
├── rift_db.py       # Supabase push/pull/status (PostgREST, stdlib)
├── server.py        # http.server (stdlib), bound 127.0.0.1
├── supabase/
│   └── schema.sql   # chạy 1 lần trong SQL Editor
├── web/
│   ├── index.html
│   ├── styles.css   # Void Hextech theme, responsive 390 → 1440
│   ├── app.js       # aggregate + render, không thư viện ngoài
│   ├── demo-data.js # 590 trận mock deterministic (fallback)
│   └── champions.js # 173 tướng Data Dragon 16.20.1
├── tests/           # unittest: merge + Supabase row mapping
├── players.txt      # roster thật — LOCAL ONLY, đã gitignore
├── imports/         # export bundles từ máy bạn bè — gitignored
├── exports/         # output của lcu_export.py — gitignored
├── cache/lcu/       # match detail JSON — gitignored
├── cache/ddragon/   # champion id → key — gitignored
└── lcu_debug/       # raw probe output — gitignored
```

### API

| Endpoint | Mô tả |
|---|---|
| `GET /api/stats?count=50&champion=Kaisa` | payload cho dashboard (players, champions, matches) |
| `GET /api/status` | LCU available, lần sync cuối, số match đã cache |
| `POST /api/sync` | đồng bộ ngay từ LCU |

Payload dùng đúng shape trong `AGENTS.md` §7; `web/app.js` tự aggregate từ
`matches`.

---

## Roster

`players.txt` (không commit) — mỗi dòng một Riot ID:

```text
GameName#TAG
GameName2#TAG2
```

- Nếu file tồn tại: chỉ những người này được tính.
- Nếu chưa có: collector tự dò đồng đội xuất hiện **≥ 2 trận cùng team** với
  tài khoản đang đăng nhập, rồi luôn thêm chính tài khoản đó.
- Có thể thêm bạn mới bất cứ lúc nào; người chưa từng xuất hiện trong cache sẽ
  được resolve ở lần sync sau.

---

## Thu thập từ máy của bạn bè (merge)

Mỗi người chạy exporter trên máy của họ khi League client đang mở:

```powershell
python lcu_export.py
# -> exports/rift-export-<ten>-<thoi-gian>.json
```

Gửi file đó cho máy chạy dashboard, bỏ vào `imports/` (hoặc
`python rift_db.py push --import <file>`). `lcu_stats.py` tự merge mọi file
trong `imports/`, dedupe theo `gameId`, cache local thắng khi trùng. Nhờ vậy dữ
liệu solo Mayhem của từng người cũng được tính.

Bundle chỉ chứa trận Mayhem sau khi kết thúc, danh tính người trong
`players.txt` + chính người export — không có lockfile, password hay key.

---

## Lưu trữ Supabase (tuỳ chọn)

1. Tạo project tại <https://supabase.com> (hoặc dùng project sẵn có — bảng được
   prefix `rift_` để không đụng bảng khác).
2. Mở **SQL Editor**, chạy toàn bộ `supabase/schema.sql`.
3. Tạo `.env` từ `.env.example`:

   ```text
   SUPABASE_URL=https://<project>.supabase.co
   SUPABASE_SERVICE_KEY=<service-role key>
   ```

4. Kiểm tra và đẩy dữ liệu:

   ```powershell
   python rift_db.py status
   python rift_db.py push
   python rift_db.py pull --out cache/db-stats.json
   ```

`server.py` tự push sau mỗi lần sync LCU, rồi đọc lại bản canonical từ
Supabase. Nếu LCU tắt, server vẫn phục vụ dữ liệu Supabase. Tắt bằng
`python server.py --no-db`.

**Bảo mật:** service-role key bypass RLS, chỉ dùng phía server. Schema bật RLS
và chỉ cho `anon` quyền `select`; không đưa key vào browser, repo hay file
export.

---

## Giới hạn đã biết

- **LCU chỉ trả ~20 trận gần nhất** cho mỗi tài khoản (endpoint bỏ qua
  `begIndex/endIndex` trên client hiện tại). Collector lưu vĩnh viễn từng match
  detail vào `cache/lcu/<gameId>.json`, nên dataset **tăng dần qua mỗi lần
  sync**. Dùng `lcu_export.py` trên máy từng người để bù phần lịch sử mà một
  client không thấy.
- Match detail có đủ 10 người, nhưng chỉ người trong roster được đưa vào
  dashboard.
- ARAM: Mayhem không có trên Riot Match-V5 public, nên Riot API không phải
  nguồn thay thế cho queue `2400`.
- Tên/tag người chơi có thể đổi; puuid mới là khoá ổn định.

---

## Bảo mật / Riot

- Chỉ bind `127.0.0.1`; không mở server/LCU ra internet hay ngrok.
- Không commit `lockfile`, password LCU, API key, `players.txt`, hay dữ liệu
  người chơi thật.
- Chỉ đọc dữ liệu sau trận; không automate gameplay/input.
- Chỉ phân tích tài khoản của những người đã đồng ý.
- LCU là API nội bộ không chính thức và có thể đổi theo patch.

---

## Kiểm thử

```powershell
python lcu_stats.py --selftest
python -m unittest discover -s tests -v
python server.py --no-sync
# mở http://127.0.0.1:8000
```

Đã kiểm tra trên client thật (patch 16.20): queue `2400` xuất hiện, match detail
có 10 participants, cache không refetch, dashboard render không lỗi JS, không
overflow ngang ở 390px, fallback demo hoạt động khi chặn `/api/**`.

---

## Disclaimer

Không được Riot Games bảo trợ. League of Legends và Riot Games là thương hiệu
của Riot Games, Inc.
