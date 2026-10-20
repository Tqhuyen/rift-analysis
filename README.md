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
├── lcu_stats.py     # collector + aggregation, cache bất biến theo gameId
├── server.py        # http.server (stdlib), bound 127.0.0.1
├── web/
│   ├── index.html
│   ├── styles.css   # Void Hextech theme, responsive 390 → 1440
│   ├── app.js       # aggregate + render, không thư viện ngoài
│   ├── demo-data.js # 590 trận mock deterministic (fallback)
│   └── champions.js # 173 tướng Data Dragon 16.20.1
├── players.txt      # roster thật — LOCAL ONLY, đã gitignore
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

## Giới hạn đã biết

- **LCU chỉ trả ~20 trận gần nhất** cho mỗi tài khoản (endpoint bỏ qua
  `begIndex/endIndex` trên client hiện tại). Collector lưu vĩnh viễn từng match
  detail vào `cache/lcu/<gameId>.json`, nên dataset **tăng dần qua mỗi lần
  sync**. Muốn có lịch sử dài ngay lập tức cần import/merge từ máy của từng
  người (xem `AGENTS.md` §6, bước 5).
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
