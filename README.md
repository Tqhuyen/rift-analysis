# Rift Report — LoL Friend Stats

Dashboard thống kê **ARAM: Mayhem** cho một nhóm 5 người bạn. Repo này là
**handoff/spec** cho máy có League client; source code đầy đủ nằm trong project
local trên máy gốc. Đọc `AGENTS.md` trước khi code tiếp.

---

## Trạng thái hiện tại

| Phần | Trạng thái |
|---|---|
| CLI `lol_stats.py` | Có — Python stdlib, Riot API Account-V1 + Match-V5, cache, selftest |
| Web `web/` | Có — Void Hextech dashboard, mock data, 173 tướng Data Dragon 16.20.1, responsive, đã test |
| `players.txt` | 3 Riot ID thật đã thêm local; chờ thêm 2 người |
| Nguồn dữ liệu | Quyết định dùng **LCU** cho Mayhem queue `2400` |
| LCU | Chưa test — máy gốc không có League client đang chạy |
| Riot API key | Key dev cũ trả `401 Unknown apikey`; không dùng nữa |

---

## Vì sao dùng LCU

ARAM: Mayhem dùng queue `2400`, nhưng Riot **không trả match queue này qua
Match-V5 public**. Vì vậy:

- Riot API chỉ dùng được cho ARAM thường `450` và các queue public khác.
- Muốn số liệu Mayhem thật phải đọc **LCU** (League Client Update API) trên máy
  đang chạy League client, hoặc import dữ liệu tự thu thập.
- LCU không cần API key; nó dùng `lockfile` local (port + password tạm).

---

## Kiến trúc mục tiêu

```text
League client (đang chạy)
        │  lockfile: port + password
        ▼
lcu_stats.py / server.py  ──►  cache/lcu/<gameId>.json
        │  JSON stats
        ▼
web/ (HTML/CSS/JS)  ──►  http://127.0.0.1:8000
```

- `lcu_stats.py`: đọc lịch sử Mayhem của tài khoản đang đăng nhập, lấy match
  detail, gộp theo tướng/người chơi.
- `server.py`: `http.server` stdlib, serve `web/` + `/api/stats`, cache; key
  không bao giờ xuống browser.
- `web/app.js`: fetch `/api/stats`; fallback về mock data nếu chưa có LCU.

---

## Chạy web mock (trên máy gốc)

```powershell
cd "C:\path\to\lol-stats"
python -m http.server 8000 --directory web
# mở http://127.0.0.1:8000
```

Web mock dùng 5 người chơi giả, 590 trận Mayhem, 173 tướng. Không cần key.

---

## Việc tiếp theo

1. Mở League client trên máy có LoL, đăng nhập.
2. Chạy `lcu_probe.py` để xem JSON thật của LCU:
   - current summoner
   - match history
   - match detail
   - queue `2400` có xuất hiện không
3. Viết `lcu_stats.py` + `server.py`.
4. Nối web với `/api/stats`, bỏ dần mock data.
5. Test với 3–5 người thật, responsive 390/1440, không lỗi JS.

Chi tiết endpoint, data model và checklist nằm trong `AGENTS.md`.

---

## Lưu ý về 5 người

LCU chỉ trả lịch sử của **tài khoản đang đăng nhập**:

- Trận cả nhóm chơi chung: match detail có đủ 5 người → một client lấy được stats
  của cả nhóm.
- Trận mỗi người tự chơi Mayhem: chỉ tài khoản đó có trong lịch sử client của họ.

Ba hướng:

1. Chỉ phân tích các trận cả nhóm.
2. Mỗi người chạy `lcu_export.py` trên client của họ, merge JSON.
3. Hybrid: Riot API ARAM `450` + LCU Mayhem `2400`.

Chọn hướng trước khi implement phần gộp nhiều người.

---

## Bảo mật / Riot

- Không commit `lockfile`, password LCU, Riot API key, hoặc dữ liệu người chơi
  thật lên repo public.
- Chỉ đọc dữ liệu sau trận; không automate gameplay, không can thiệp Vanguard.
- Chỉ dùng cho các tài khoản trong nhóm đã đồng ý.
- LCU là API local không chính thức; Riot có thể đổi endpoint bất kỳ lúc nào.
- Không mở LCU port ra internet/ngrok.

---

## Nội dung repo

```text
README.md     # file này
AGENTS.md     # handoff chi tiết cho agent/máy có LoL
```

Source code (`lol_stats.py`, `web/`, `players.txt`, `cache/`) nằm trong project
local, không đưa lên repo này.

---

## Disclaimer

Không được Riot Games bảo trợ. League of Legends và Riot Games là thương hiệu của
Riot Games, Inc.
