/* Rift Report — dashboard logic (vanilla JS, no build step). */
(function () {
  "use strict";

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const MAYHEM = 2400;
  const dataBadge = $("#data-badge");
  const badgeText = $("#data-badge-text");
  const banner = $("#banner");
  const heroSource = $("#hero-source");
  const heroUpdated = $("#hero-updated");
  const heroLede = $("#hero-lede");
  const kpiGrid = $("#kpi-grid");
  const spotlightPanel = $("#spotlight-panel");
  const damageRanking = $("#damage-ranking");
  const performerPanel = $("#performer-panel");
  const lossRadar = $("#loss-radar");
  const insightsEl = $("#insights");
  const champTbody = $("#champ-tbody");
  const champEmpty = $("#champ-empty");
  const champFilter = $("#champion-filter");
  const playerGrid = $("#player-grid");
  const matchList = $("#match-list");
  const countSelect = $("#count-select");
  const syncBtn = $("#sync-btn");
  const menuBtn = $("#menu-btn");
  const nav = $("#main-nav");

  const state = {
    data: null,
    live: false,
    limit: 0,
    champion: "Kaisa",
    metric: "total",
    tableChampion: "",
    sort: { key: "games", dir: "desc" },
    lastFocused: null
  };

  /* ------------------------------------------------------------------ */
  /* Helpers                                                            */
  /* ------------------------------------------------------------------ */
  function esc(value) {
    return String(value == null ? "" : value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function fmtInt(n) {
    return Math.round(Number(n) || 0).toLocaleString("en-US");
  }

  function fmtCompact(n) {
    const v = Number(n) || 0;
    if (v >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, "") + "M";
    if (v >= 1e3) return (v / 1e3).toFixed(1).replace(/\.0$/, "") + "k";
    return String(Math.round(v));
  }

  function pct(value) {
    return (Number(value) || 0).toFixed(1) + "%";
  }

  function kda(k, d, a) {
    return ((Number(k) + Number(a)) / Math.max(Number(d), 1)).toFixed(2);
  }

  function duration(seconds) {
    const s = Math.max(0, Math.round(Number(seconds) || 0));
    return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
  }

  function timeAgo(ts) {
    const diff = Date.now() - Number(ts || 0);
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return "vừa xong";
    if (mins < 60) return mins + " phút trước";
    const hours = Math.floor(mins / 60);
    if (hours < 24) return hours + " giờ trước";
    const days = Math.floor(hours / 24);
    if (days < 30) return days + " ngày trước";
    return new Date(Number(ts)).toLocaleDateString("vi-VN");
  }

  function dateLabel(ts) {
    const date = typeof ts === "string" ? new Date(ts) : new Date(Number(ts || 0));
    if (Number.isNaN(date.getTime())) return "—";
    return date.toLocaleString("vi-VN", {
      day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit"
    });
  }

  function initialsOf(name) {
    const parts = String(name || "?").replace(/_/g, " ").split(/\s+/).filter(Boolean);
    if (!parts.length) return "??";
    if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase();
    return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase();
  }

  function championInfo(key) {
    const champs = (state.data && state.data.champions) || {};
    const found = champs[key] || {};
    const version = window.RIFT_CHAMPION_VERSION || "16.20.1";
    return {
      key,
      name: found.name || key,
      title: found.title || "",
      splash: found.splash || `https://ddragon.leagueoflegends.com/cdn/img/champion/splash/${key}_0.jpg`,
      tile: found.tile || `https://ddragon.leagueoflegends.com/cdn/img/champion/tiles/${key}_0.jpg`,
      version
    };
  }

  function champImg(key, cls) {
    const info = championInfo(key);
    return `<img class="${cls || ""}" src="${esc(info.tile)}" alt="" loading="lazy" width="34" height="34" ` +
      `onerror="this.style.visibility='hidden'">`;
  }

  function playerById(id) {
    return (state.data.players || []).find((p) => p.id === id) || {
      id, name: "Unknown", tag: "", initials: "??", c1: "#8b5cf6", c2: "#22d3ee"
    };
  }

  function avatar(player, cls) {
    const p = typeof player === "string" ? playerById(player) : player;
    return `<span class="avatar ${cls || ""}" style="--c1:${esc(p.c1 || "#8b5cf6")};--c2:${esc(p.c2 || "#22d3ee")}" ` +
      `aria-hidden="true">${esc(p.initials || initialsOf(p.name))}</span>`;
  }

  function playerLabel(player) {
    return player.tag ? `${player.name}#${player.tag}` : player.name;
  }

  /* ------------------------------------------------------------------ */
  /* Derived data                                                       */
  /* ------------------------------------------------------------------ */
  function activeMatches() {
    const all = (state.data.matches || [])
      .filter((m) => Number(m.queueId) === MAYHEM)
      .slice()
      .sort((a, b) => Number(b.timestamp || 0) - Number(a.timestamp || 0));
    return state.limit > 0 ? all.slice(0, state.limit) : all;
  }

  function aggregate(matches) {
    const players = new Map();
    const champRows = new Map();

    (state.data.players || []).forEach((p) => {
      players.set(p.id, {
        player: p, games: 0, wins: 0, kills: 0, deaths: 0, assists: 0,
        damage: 0, seconds: 0, champions: new Map()
      });
    });

    matches.forEach((match) => {
      const seconds = Number(match.duration) || 0;
      (match.participants || []).forEach((part) => {
        let row = players.get(part.playerId);
        if (!row) {
          row = {
            player: playerById(part.playerId), games: 0, wins: 0, kills: 0,
            deaths: 0, assists: 0, damage: 0, seconds: 0, champions: new Map()
          };
          players.set(part.playerId, row);
        }
        row.games += 1;
        row.wins += part.win ? 1 : 0;
        row.kills += Number(part.kills) || 0;
        row.deaths += Number(part.deaths) || 0;
        row.assists += Number(part.assists) || 0;
        row.damage += Number(part.damage) || 0;
        row.seconds += seconds;

        const champ = row.champions.get(part.champion) || {
          key: part.champion, games: 0, wins: 0, damage: 0, kills: 0,
          deaths: 0, assists: 0, seconds: 0
        };
        champ.games += 1;
        champ.wins += part.win ? 1 : 0;
        champ.damage += Number(part.damage) || 0;
        champ.kills += Number(part.kills) || 0;
        champ.deaths += Number(part.deaths) || 0;
        champ.assists += Number(part.assists) || 0;
        champ.seconds += seconds;
        row.champions.set(part.champion, champ);

        const rowKey = `${part.playerId}|${part.champion}`;
        let tableRow = champRows.get(rowKey);
        if (!tableRow) {
          tableRow = {
            playerId: part.playerId, champion: part.champion, games: 0, wins: 0,
            kills: 0, deaths: 0, assists: 0, damage: 0, seconds: 0
          };
          champRows.set(rowKey, tableRow);
        }
        tableRow.games += 1;
        tableRow.wins += part.win ? 1 : 0;
        tableRow.kills += Number(part.kills) || 0;
        tableRow.deaths += Number(part.deaths) || 0;
        tableRow.assists += Number(part.assists) || 0;
        tableRow.damage += Number(part.damage) || 0;
        tableRow.seconds += seconds;
      });
    });

    const totals = Array.from(players.values()).filter((r) => r.games > 0);
    totals.forEach((r) => {
      r.winrate = r.games ? (100 * r.wins) / r.games : 0;
      r.lossrate = 100 - r.winrate;
      r.kda = (r.kills + r.assists) / Math.max(r.deaths, 1);
      r.avgDamage = r.games ? r.damage / r.games : 0;
      r.dpm = r.seconds ? r.damage / (r.seconds / 60) : 0;
    });

    const rows = Array.from(champRows.values()).map((r) => ({
      ...r,
      winrate: r.games ? (100 * r.wins) / r.games : 0,
      kda: (r.kills + r.assists) / Math.max(r.deaths, 1),
      avgDamage: r.games ? r.damage / r.games : 0,
      dpm: r.seconds ? r.damage / (r.seconds / 60) : 0
    }));

    return { totals, rows, matchCount: matches.length };
  }

  /* ------------------------------------------------------------------ */
  /* Render: KPIs                                                       */
  /* ------------------------------------------------------------------ */
  function renderKpis(agg) {
    const totals = agg.totals;
    const totalDamage = totals.reduce((sum, r) => sum + r.damage, 0);
    const bestDpm = totals.slice().sort((a, b) => b.dpm - a.dpm)[0];
    const bestWr = totals.slice().sort((a, b) => b.winrate - a.winrate)[0];
    const worst = totals.slice().sort((a, b) => b.lossrate - a.lossrate)[0];

    const cards = [
      {
        label: "Trận Mayhem",
        value: fmtInt(agg.matchCount),
        sub: `${state.data.players.length} người chơi · tổng ${fmtCompact(totalDamage)} sát thương`,
        icon: "◈", accent: "#8b5cf6"
      },
      {
        label: "DPM cao nhất",
        value: bestDpm ? fmtInt(bestDpm.dpm) : "—",
        sub: bestDpm ? esc(bestDpm.player.name) + " · sát thương mỗi phút" : "chưa có dữ liệu",
        icon: "✦", accent: "#22d3ee"
      },
      {
        label: "Tỉ lệ thắng tốt nhất",
        value: bestWr ? pct(bestWr.winrate) : "—",
        sub: bestWr ? esc(bestWr.player.name) + ` · ${bestWr.wins}/${bestWr.games} trận thắng` : "chưa có dữ liệu",
        icon: "▲", accent: "#34d399"
      },
      {
        label: "Thua nhiều nhất",
        value: worst ? pct(worst.lossrate) : "—",
        sub: worst ? esc(worst.player.name) + ` · ${worst.games - worst.wins}/${worst.games} trận thua` : "chưa có dữ liệu",
        icon: "▼", accent: "#fb7185"
      }
    ];

    kpiGrid.innerHTML = cards.map((c) => `
      <article class="kpi" style="--accent:${c.accent}">
        <div class="kpi-top">
          <span class="kpi-label">${c.label}</span>
          <span class="kpi-icon" aria-hidden="true">${c.icon}</span>
        </div>
        <div class="kpi-value">${c.value}</div>
        <div class="kpi-sub">${c.sub}</div>
      </article>
    `).join("");

    heroLede.textContent =
      `${agg.matchCount} trận ARAM: Mayhem · ${state.data.players.length} người · ` +
      `${fmtCompact(totalDamage)} sát thương ra tướng.`;
  }

  /* ------------------------------------------------------------------ */
  /* Render: spotlight                                                  */
  /* ------------------------------------------------------------------ */
  function renderSpotlight(agg, matches) {
    const info = championInfo(state.champion);
    const rows = agg.rows.filter((r) => r.champion === state.champion)
      .sort((a, b) => b.games - a.games || b.dpm - a.dpm);
    const totalGames = rows.reduce((sum, r) => sum + r.games, 0);
    const totalWins = rows.reduce((sum, r) => sum + r.wins, 0);
    const totalDamage = rows.reduce((sum, r) => sum + r.damage, 0);
    const bestDamage = rows.slice().sort((a, b) => b.avgDamage - a.avgDamage)[0];
    const maxDpm = Math.max(1, ...rows.map((r) => r.dpm));

    const hero = `
      <div class="spotlight-hero">
        <div class="spot-splash-bg" style="background-image:url('${esc(info.splash)}')" aria-hidden="true"></div>
        <div class="spot-avatar"><img src="${esc(info.splash)}" alt="${esc(info.name)}" loading="lazy"></div>
        <div class="spot-info">
          <p class="eyebrow">${esc(info.name)}</p>
          <h3>${esc(info.title || "Champion spotlight")}</h3>
          <p>${totalGames ? `${totalGames} trận cả nhóm · ${pct((100 * totalWins) / totalGames)} thắng · ${fmtCompact(totalDamage)} sát thương.` : "Chưa có trận nào với tướng này trong khoảng đã chọn."}</p>
        </div>
        <div class="spot-kpis">
          <div><b>${bestDamage ? fmtCompact(bestDamage.avgDamage) : "—"}</b><span>DMG TB cao nhất</span></div>
          <div><b>${totalGames}</b><span>Trận</span></div>
          <div><b>${pct(totalGames ? (100 * totalWins) / totalGames : 0)}</b><span>Tỉ lệ thắng</span></div>
        </div>
      </div>`;

    const list = rows.length
      ? rows.map((r, i) => {
        const player = playerById(r.playerId);
        return `
        <div class="spot-row">
          <span class="rank">${i + 1}</span>
          ${avatar(player)}
          <span class="spot-name">${esc(player.name)}<em>${r.games} trận · KDA ${r.kda.toFixed(2)}</em></span>
          <span class="bar" aria-hidden="true"><i style="width:${Math.round((r.dpm / maxDpm) * 100)}%"></i></span>
          <span class="spot-val">${fmtCompact(r.avgDamage)}</span>
          <span class="spot-wr">${pct(r.winrate)} WR</span>
        </div>`;
      }).join("")
      : `<div class="spot-row is-empty">Chưa có dữ liệu cho ${esc(info.name)}. Chọn khoảng trận khác hoặc đồng bộ thêm.</div>`;

    spotlightPanel.innerHTML = hero + `<div class="spot-list">${list}</div>`;
    $("#spotlight-sub").textContent =
      `Ai chơi tốt nhất với ${info.name}? Xếp theo DPM trung bình.`;
    spotlightPanel.setAttribute(
      "aria-labelledby",
      state.champion === "Kaisa" ? "tab-kaisa" : "tab-ezreal"
    );
    $("#tab-kaisa").setAttribute("aria-selected", state.champion === "Kaisa" ? "true" : "false");
    $("#tab-ezreal").setAttribute("aria-selected", state.champion === "Ezreal" ? "true" : "false");
    $$(".tab").forEach((tab) => {
      tab.classList.toggle("is-active", tab.dataset.champion === state.champion);
    });
  }

  /* ------------------------------------------------------------------ */
  /* Render: damage ranking                                             */
  /* ------------------------------------------------------------------ */
  function renderDamage(agg) {
    const rows = agg.totals.slice().sort((a, b) => {
      if (state.metric === "avg") return b.avgDamage - a.avgDamage;
      if (state.metric === "dpm") return b.dpm - a.dpm;
      return b.damage - a.damage;
    });
    const max = Math.max(1, ...rows.map((r) =>
      state.metric === "avg" ? r.avgDamage : state.metric === "dpm" ? r.dpm : r.damage));

    const value = (r) => {
      if (state.metric === "avg") return fmtCompact(r.avgDamage);
      if (state.metric === "dpm") return fmtInt(r.dpm);
      return fmtCompact(r.damage);
    };

    damageRanking.innerHTML = `<div class="rank-list">${rows.map((r, i) => `
      <div class="rank-row">
        <span class="rank">${i + 1}</span>
        ${avatar(r.player)}
        <div class="rank-main">
          <div class="rank-line"><span>${esc(r.player.name)}</span><b>${value(r)}</b></div>
          <div class="bar"><i style="width:${Math.round(((state.metric === "avg" ? r.avgDamage : state.metric === "dpm" ? r.dpm : r.damage) / max) * 100)}%"></i></div>
        </div>
      </div>`).join("")}</div>`;
  }

  /* ------------------------------------------------------------------ */
  /* Render: performer                                                  */
  /* ------------------------------------------------------------------ */
  function renderPerformer(agg) {
    const candidates = agg.totals.filter((r) => r.games >= Math.min(3, agg.matchCount));
    const pool = candidates.length ? candidates : agg.totals;
    const best = pool.slice().sort((a, b) => b.dpm - a.dpm)[0];

    if (!best) {
      performerPanel.innerHTML = `<p class="empty">Chưa có dữ liệu.</p>`;
      return;
    }

    const champs = Array.from(best.champions.values())
      .sort((a, b) => b.games - a.games)
      .slice(0, 3);

    performerPanel.innerHTML = `
      <div class="performer">
        <div class="performer-top">
          ${avatar(best.player, "lg")}
          <div>
            <h3>${esc(best.player.name)}</h3>
            <span>${esc(best.player.tag ? "#" + best.player.tag : "")} · ${best.games} trận · ${fmtInt(best.dpm)} DPM</span>
          </div>
          <span class="performer-badge">MVP</span>
        </div>
        <div class="performer-stats">
          <div><b>${pct(best.winrate)}</b><span>Tỉ lệ thắng</span></div>
          <div><b>${best.kda.toFixed(2)}</b><span>KDA</span></div>
          <div><b>${fmtCompact(best.avgDamage)}</b><span>DMG / trận</span></div>
          <div><b>${fmtInt(best.kills + best.assists)}</b><span>Tham gia hạ gục</span></div>
        </div>
        <div class="performer-champs">
          ${champs.map((c) => `<span class="chip">${champImg(c.key)}<b>${esc(championInfo(c.key).name)}</b> ${c.games} trận · ${pct((100 * c.wins) / c.games)}</span>`).join("")}
        </div>
      </div>`;
  }

  /* ------------------------------------------------------------------ */
  /* Render: loss radar                                                 */
  /* ------------------------------------------------------------------ */
  function renderLoss(agg) {
    const rows = agg.totals.slice().sort((a, b) => b.lossrate - a.lossrate);
    lossRadar.innerHTML = `<div class="loss-list">${rows.map((r) => `
      <div class="loss-row">
        ${avatar(r.player, "sm")}
        <span class="loss-name">${esc(r.player.name)}</span>
        <span class="bar loss" aria-hidden="true"><i style="width:${Math.round(r.lossrate)}%"></i></span>
        <span class="loss-val">${pct(r.lossrate)}</span>
      </div>`).join("")}</div>`;
  }

  /* ------------------------------------------------------------------ */
  /* Render: insights                                                   */
  /* ------------------------------------------------------------------ */
  function renderInsights(agg, matches) {
    const totals = agg.totals;
    const items = [];

    if (totals.length) {
      const topDamage = totals.slice().sort((a, b) => b.damage - a.damage)[0];
      const topKda = totals.slice().sort((a, b) => b.kda - a.kda)[0];
      const topWr = totals.slice().sort((a, b) => b.winrate - a.winrate)[0];
      const worst = totals.slice().sort((a, b) => b.lossrate - a.lossrate)[0];

      items.push({
        icon: "✦",
        text: `<strong>${esc(topDamage.player.name)}</strong> dẫn đầu tổng sát thương với ${fmtCompact(topDamage.damage)} (${fmtInt(topDamage.dpm)} DPM).`
      });
      items.push({
        icon: "◆",
        text: `<strong>${esc(topKda.player.name)}</strong> có KDA cao nhất: ${topKda.kda.toFixed(2)} (${topKda.kills}/${topKda.deaths}/${topKda.assists}).`
      });

      const championCount = new Map();
      matches.forEach((m) => (m.participants || []).forEach((p) => {
        championCount.set(p.champion, (championCount.get(p.champion) || 0) + 1);
      }));
      const favourite = Array.from(championCount.entries()).sort((a, b) => b[1] - a[1])[0];
      if (favourite) {
        items.push({
          icon: "◈",
          text: `Tướng xuất hiện nhiều nhất: <strong>${esc(championInfo(favourite[0]).name)}</strong> với ${favourite[1]} lượt chọn.`
        });
      }

      if (topWr !== worst) {
        items.push({
          icon: "▲",
          text: `<strong>${esc(topWr.player.name)}</strong> giữ tỉ lệ thắng ${pct(topWr.winrate)}, trong khi <strong>${esc(worst.player.name)}</strong> đang ở ${pct(worst.winrate)}.`
        });
      }

      const bestChampion = agg.rows
        .filter((r) => r.games >= 2)
        .sort((a, b) => b.winrate - a.winrate || b.games - a.games)[0];
      if (bestChampion) {
        items.push({
          icon: "✧",
          text: `<strong>${esc(playerById(bestChampion.playerId).name)}</strong> thắng ${pct(bestChampion.winrate)} khi cầm <strong>${esc(championInfo(bestChampion.champion).name)}</strong> (${bestChampion.games} trận).`
        });
      }
    }

    if (!items.length) {
      insightsEl.innerHTML = `<p class="empty">Chưa đủ dữ liệu để tạo insight.</p>`;
      return;
    }

    insightsEl.innerHTML = items.map((item) => `
      <div class="insight">
        <span class="insight-icon" aria-hidden="true">${item.icon}</span>
        <p>${item.text}</p>
      </div>`).join("");
  }

  /* ------------------------------------------------------------------ */
  /* Render: champion table                                             */
  /* ------------------------------------------------------------------ */
  function tableValue(row, key) {
    if (key === "champion") return championInfo(row.champion).name.toLowerCase();
    if (key === "player") return playerById(row.playerId).name.toLowerCase();
    return Number(row[key]) || 0;
  }

  function renderTable(agg) {
    let rows = agg.rows.slice();
    if (state.tableChampion) {
      rows = rows.filter((r) => r.champion === state.tableChampion);
    }

    const dir = state.sort.dir === "asc" ? 1 : -1;
    rows.sort((a, b) => {
      const va = tableValue(a, state.sort.key);
      const vb = tableValue(b, state.sort.key);
      if (va < vb) return -1 * dir;
      if (va > vb) return 1 * dir;
      return b.games - a.games;
    });

    champTbody.innerHTML = rows.map((r) => {
      const player = playerById(r.playerId);
      const info = championInfo(r.champion);
      return `
        <tr>
          <td>
            <span class="champ-cell">${champImg(r.champion)}<span>${esc(info.name)}</span></span>
          </td>
          <td>
            <span class="player-cell">${avatar(player, "sm")}${esc(player.name)}</span>
          </td>
          <td class="num">${r.games}</td>
          <td class="num"><span class="pill ${r.winrate >= 50 ? "win" : "loss"}">${pct(r.winrate)}</span></td>
          <td class="num">${r.kda.toFixed(2)}</td>
          <td class="num">${fmtCompact(r.avgDamage)}</td>
          <td class="num">${fmtInt(r.dpm)}</td>
        </tr>`;
    }).join("");

    champEmpty.hidden = rows.length > 0;

    $$("#champ-table thead th").forEach((th) => {
      const btn = th.querySelector("button");
      if (!btn) return;
      th.setAttribute("aria-sort",
        btn.dataset.sort === state.sort.key
          ? (state.sort.dir === "asc" ? "ascending" : "descending")
          : "none");
    });
  }

  function fillChampionFilter(agg) {
    const keys = Array.from(new Set(agg.rows.map((r) => r.champion)))
      .sort((a, b) => championInfo(a).name.localeCompare(championInfo(b).name, "vi"));
    const current = state.tableChampion;
    champFilter.innerHTML = `<option value="">Tất cả tướng (${keys.length})</option>` +
      keys.map((k) => `<option value="${esc(k)}">${esc(championInfo(k).name)}</option>`).join("");
    if (keys.includes(current)) champFilter.value = current;
    else { state.tableChampion = ""; champFilter.value = ""; }
  }

  /* ------------------------------------------------------------------ */
  /* Render: player cards                                               */
  /* ------------------------------------------------------------------ */
  function renderPlayers(agg) {
    playerGrid.innerHTML = agg.totals.map((r) => {
      const champs = Array.from(r.champions.values())
        .sort((a, b) => b.games - a.games)
        .slice(0, 3);
      return `
        <button class="player-card" type="button" data-player="${esc(r.player.id)}"
                style="--c1:${esc(r.player.c1 || "#8b5cf6")};--c2:${esc(r.player.c2 || "#22d3ee")}"
                aria-label="Xem chi tiết ${esc(r.player.name)}">
          <div class="player-top">
            ${avatar(r.player)}
            <div class="player-id">
              <strong>${esc(r.player.name)}</strong>
              <span>${esc(r.player.tag ? "#" + r.player.tag : "")}${r.player.role ? " · " + esc(r.player.role) : ""}</span>
            </div>
            <span class="chev" aria-hidden="true">›</span>
          </div>
          <div class="player-stats">
            <div><b>${r.games}</b><span>Trận</span></div>
            <div><b>${pct(r.winrate)}</b><span>Thắng</span></div>
            <div><b>${r.kda.toFixed(2)}</b><span>KDA</span></div>
            <div><b>${fmtInt(r.dpm)}</b><span>DPM</span></div>
          </div>
          <div class="player-champs">
            ${champs.map((c) => `<span class="chip">${champImg(c.key)}<b>${esc(championInfo(c.key).name)}</b> ${pct((100 * c.wins) / c.games)}</span>`).join("")}
          </div>
        </button>`;
    }).join("");

    $("#players-sub").textContent = `${state.data.players.length} người chơi · bấm vào thẻ để xem chi tiết.`;
  }

  /* ------------------------------------------------------------------ */
  /* Render: recent matches                                             */
  /* ------------------------------------------------------------------ */
  function renderMatches(matches) {
    const recent = matches.slice(0, 8);
    if (!recent.length) {
      matchList.innerHTML = `<p class="empty">Chưa có trận nào.</p>`;
      return;
    }

    matchList.innerHTML = recent.map((m) => {
      const parts = m.participants || [];
      const win = parts.some((p) => p.win);
      const kills = parts.reduce((s, p) => s + (p.kills || 0), 0);
      const deaths = parts.reduce((s, p) => s + (p.deaths || 0), 0);
      const assists = parts.reduce((s, p) => s + (p.assists || 0), 0);
      const damage = parts.reduce((s, p) => s + (p.damage || 0), 0);
      return `
        <article class="match ${win ? "win" : "loss"}" title="${esc(dateLabel(m.timestamp))}">
          <div class="match-result">
            <span class="result">${win ? "Thắng" : "Thua"}</span>
            <span class="match-time">${esc(timeAgo(m.timestamp))}</span>
          </div>
          <div class="match-champs">
            ${parts.map((p) => `
              <span class="match-champ" title="${esc(playerById(p.playerId).name)} · ${esc(championInfo(p.champion).name)}">
                ${champImg(p.champion)}
                <span>${esc(playerById(p.playerId).initials || initialsOf(playerById(p.playerId).name))}</span>
              </span>`).join("")}
          </div>
          <div class="match-meta">
            <span><b>${duration(m.duration)}</b></span>
            <span>KDA <b>${kills}/${deaths}/${assists}</b></span>
            <span>DMG <b>${fmtCompact(damage)}</b></span>
          </div>
        </article>`;
    }).join("");
  }

  /* ------------------------------------------------------------------ */
  /* Drawer                                                            */
  /* ------------------------------------------------------------------ */
  function openDrawer(playerId) {
    const player = playerById(playerId);
    const matches = activeMatches();
    const agg = aggregate(matches);
    const row = agg.totals.find((r) => r.player.id === playerId);
    const overlay = $("#overlay");
    const drawer = $("#drawer");

    state.lastFocused = document.activeElement;

    if (!row) {
      $("#drawer-body").innerHTML = `<p class="empty">Chưa có dữ liệu cho người chơi này.</p>`;
    } else {
      const champs = Array.from(row.champions.values())
        .sort((a, b) => b.games - a.games)
        .slice(0, 8);
      const recent = matches.filter((m) =>
        (m.participants || []).some((p) => p.playerId === playerId)).slice(0, 5);

      $("#drawer-body").innerHTML = `
        <div class="drawer-profile">
          ${avatar(player, "lg")}
          <div>
            <h3>${esc(player.name)}</h3>
            <span>${esc(player.tag ? "#" + player.tag : "")}${player.role ? " · " + esc(player.role) : ""}</span>
          </div>
        </div>
        <div class="drawer-stats">
          <div><b>${row.games}</b><span>Trận</span></div>
          <div><b>${pct(row.winrate)}</b><span>Tỉ lệ thắng</span></div>
          <div><b>${row.kda.toFixed(2)}</b><span>KDA</span></div>
          <div><b>${fmtInt(row.dpm)}</b><span>DPM</span></div>
          <div><b>${fmtCompact(row.avgDamage)}</b><span>DMG / trận</span></div>
          <div><b>${fmtCompact(row.damage)}</b><span>Tổng sát thương</span></div>
        </div>
        <p class="drawer-sub">Tướng nhiều trận nhất</p>
        ${champs.map((c) => `
          <div class="drawer-champ">
            ${champImg(c.key)}
            <span>${esc(championInfo(c.key).name)}<br><small>${c.games} trận · KDA ${((c.kills + c.assists) / Math.max(c.deaths, 1)).toFixed(2)}</small></span>
            <b>${pct((100 * c.wins) / c.games)}</b>
            <b title="Sát thương mỗi phút">${fmtInt(c.seconds ? c.damage / (c.seconds / 60) : 0)}<small class="unit">DPM</small></b>
          </div>`).join("")}
        <p class="drawer-sub">Trận gần đây</p>
        ${recent.map((m) => {
          const p = (m.participants || []).find((x) => x.playerId === playerId) || {};
          return `
            <div class="drawer-champ">
              ${champImg(p.champion)}
              <span>${esc(championInfo(p.champion).name)}<br><small>${esc(timeAgo(m.timestamp))}</small></span>
              <b>${p.kills || 0}/${p.deaths || 0}/${p.assists || 0}</b>
              <b style="color:${p.win ? "var(--win)" : "var(--loss)"}">${p.win ? "W" : "L"}</b>
            </div>`;
        }).join("")}
      `;
    }

    drawer.hidden = false;
    overlay.hidden = false;
    requestAnimationFrame(() => {
      drawer.classList.add("is-open");
      overlay.classList.add("is-open");
    });
    $("#drawer-title").textContent = player.name;
    document.body.style.overflow = "hidden";
    $("#drawer-close").focus();
  }

  function closeDrawer() {
    const drawer = $("#drawer");
    const overlay = $("#overlay");
    if (drawer.hidden) return;
    drawer.classList.remove("is-open");
    overlay.classList.remove("is-open");
    document.body.style.overflow = "";
    setTimeout(() => {
      drawer.hidden = true;
      overlay.hidden = true;
      if (state.lastFocused && state.lastFocused.focus) state.lastFocused.focus();
    }, 280);
  }

  function trapFocus(event) {
    if (event.key !== "Tab") return;
    const drawer = $("#drawer");
    if (drawer.hidden) return;
    const focusable = $$("button, [href], select, input, textarea, [tabindex]:not([tabindex='-1'])", drawer)
      .filter((el) => !el.disabled && el.offsetParent !== null);
    if (!focusable.length) return;
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }

  /* ------------------------------------------------------------------ */
  /* Render orchestration                                               */
  /* ------------------------------------------------------------------ */
  function renderAll() {
    if (!state.data) return;
    const matches = activeMatches();
    const agg = aggregate(matches);
    renderKpis(agg);
    renderSpotlight(agg, matches);
    renderDamage(agg);
    renderPerformer(agg);
    renderLoss(agg);
    renderInsights(agg, matches);
    fillChampionFilter(agg);
    renderTable(agg);
    renderPlayers(agg);
    renderMatches(matches);
  }

  /* ------------------------------------------------------------------ */
  /* Banner / source                                                    */
  /* ------------------------------------------------------------------ */
  function setSource(live, message) {
    state.live = live;
    dataBadge.dataset.source = live ? "live" : "demo";
    badgeText.textContent = live ? "LCU LIVE" : "Demo data";
    heroSource.textContent = live
      ? "Nguồn: League Client (LCU) · queue 2400"
      : "Nguồn: dữ liệu demo";
    const generated = state.data && state.data.generatedAt;
    heroUpdated.textContent = generated ? "Cập nhật " + dateLabel(generated) : "—";
    $("#sync-btn").title = live
      ? "Đồng bộ trận mới từ League Client"
      : "Thử kết nối League Client";

    if (message) {
      banner.hidden = false;
      banner.textContent = message;
      banner.dataset.kind = "error";
    } else if (!live) {
      banner.hidden = false;
      banner.dataset.kind = "warn";
      banner.textContent =
        "Đang hiển thị dữ liệu demo. Mở League client rồi chạy server.py để xem số liệu thật.";
    } else {
      banner.hidden = true;
      banner.textContent = "";
    }
  }

  /* ------------------------------------------------------------------ */
  /* Loading                                                            */
  /* ------------------------------------------------------------------ */
  async function loadStats() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 6000);
    try {
      const response = await fetch("/api/stats", { signal: controller.signal, cache: "no-store" });
      if (!response.ok) throw new Error("HTTP " + response.status);
      const payload = await response.json();
      if (!payload || !Array.isArray(payload.matches) || !payload.matches.length) {
        throw new Error("No matches in payload");
      }
      state.data = payload;
      return true;
    } catch (err) {
      state.data = window.RIFT_DEMO || null;
      return false;
    } finally {
      clearTimeout(timer);
    }
  }

  async function boot() {
    if (!window.RIFT_DEMO) {
      banner.hidden = false;
      banner.dataset.kind = "error";
      banner.textContent = "Không tải được champions.js / demo-data.js.";
    }

    const live = await loadStats();
    if (!state.data) {
      heroSource.textContent = "Không có dữ liệu";
      return;
    }
    setSource(live, null);
    renderAll();
  }

  /* ------------------------------------------------------------------ */
  /* Events                                                             */
  /* ------------------------------------------------------------------ */
  countSelect.addEventListener("change", () => {
    state.limit = Number(countSelect.value) || 0;
    renderAll();
  });

  $$(".tabs .tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.champion = tab.dataset.champion;
      renderAll();
    });
  });

  $$(".segmented .seg").forEach((seg) => {
    seg.addEventListener("click", () => {
      state.metric = seg.dataset.metric;
      $$(".segmented .seg").forEach((s) => s.classList.toggle("is-active", s === seg));
      renderAll();
    });
  });

  champFilter.addEventListener("change", () => {
    state.tableChampion = champFilter.value;
    renderAll();
  });

  $$("#champ-table thead button").forEach((btn) => {
    btn.addEventListener("click", () => {
      const key = btn.dataset.sort;
      if (state.sort.key === key) {
        state.sort.dir = state.sort.dir === "asc" ? "desc" : "asc";
      } else {
        state.sort.key = key;
        state.sort.dir = key === "champion" || key === "player" ? "asc" : "desc";
      }
      renderTable(aggregate(activeMatches()));
    });
  });

  playerGrid.addEventListener("click", (event) => {
    const card = event.target.closest("[data-player]");
    if (card) openDrawer(card.dataset.player);
  });

  $("#drawer-close").addEventListener("click", closeDrawer);
  $("#overlay").addEventListener("click", closeDrawer);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDrawer();
      nav.classList.remove("is-open");
      menuBtn.setAttribute("aria-expanded", "false");
    }
    trapFocus(event);
  });

  menuBtn.addEventListener("click", () => {
    const open = nav.classList.toggle("is-open");
    menuBtn.setAttribute("aria-expanded", open ? "true" : "false");
    menuBtn.setAttribute("aria-label", open ? "Đóng menu" : "Mở menu");
  });

  nav.addEventListener("click", (event) => {
    if (event.target.closest("a")) {
      nav.classList.remove("is-open");
      menuBtn.setAttribute("aria-expanded", "false");
    }
  });

  syncBtn.addEventListener("click", async () => {
    syncBtn.classList.add("is-busy");
    syncBtn.disabled = true;
    banner.hidden = true;
    try {
      const response = await fetch("/api/sync", { method: "POST" });
      if (!response.ok) {
        const detail = await response.json().catch(() => ({}));
        throw new Error(detail.hint || detail.error || "HTTP " + response.status);
      }
      const live = await loadStats();
      setSource(live, live ? null : "Đồng bộ xong nhưng không đọc được dữ liệu.");
      renderAll();
      if (live) {
        banner.hidden = false;
        banner.dataset.kind = "warn";
        banner.textContent = "Đã đồng bộ từ League Client.";
        setTimeout(() => { if (state.live) banner.hidden = true; }, 4000);
      }
    } catch (err) {
      setSource(state.live, "Không đồng bộ được: " + err.message + ". Kiểm tra League client đang mở.");
    } finally {
      syncBtn.classList.remove("is-busy");
      syncBtn.disabled = false;
    }
  });

  window.addEventListener("resize", () => {
    if (window.innerWidth > 900) {
      nav.classList.remove("is-open");
      menuBtn.setAttribute("aria-expanded", "false");
    }
  });

  boot();
})();
