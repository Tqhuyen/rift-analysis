// Deterministic mock data for offline / no-LCU use.
// Shape matches GET /api/stats: { players, champions, matches, queues }.
(function () {
  "use strict";

  function mulberry32(seed) {
    return function () {
      seed |= 0;
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  const rand = mulberry32(0x5eed);
  const pick = (list) => list[Math.floor(rand() * list.length)];
  const between = (min, max) => min + rand() * (max - min);

  const players = [
    { id: "player1", name: "VoidWalker", tag: "VN2", initials: "VW", role: "ADC",
      c1: "#8B5CF6", c2: "#22D3EE",
      pool: ["Kaisa", "Ezreal", "Vayne", "Jinx", "Caitlyn", "Ashe"],
      dmg: 1.0, kda: 1.0 },
    { id: "player2", name: "BaronSteal", tag: "VN2", initials: "BS", role: "Bruiser",
      c1: "#F59E0B", c2: "#EF4444",
      pool: ["Darius", "Garen", "Sett", "Aatrox", "Volibear", "Urgot"],
      dmg: 0.88, kda: 1.05 },
    { id: "player3", name: "SupportDiff", tag: "VN2", initials: "SD", role: "Support",
      c1: "#10B981", c2: "#3B82F6",
      pool: ["Thresh", "Nautilus", "Leona", "Lulu", "Janna", "Karma"],
      dmg: 0.55, kda: 1.25 },
    { id: "player4", name: "FlashOnD", tag: "VN2", initials: "FD", role: "Mage",
      c1: "#EC4899", c2: "#8B5CF6",
      pool: ["Ahri", "Syndra", "Lux", "Veigar", "Orianna", "Zoe"],
      dmg: 1.06, kda: 0.95 },
    { id: "player5", name: "IntingSion", tag: "VN2", initials: "IS", role: "Tank",
      c1: "#06B6D4", c2: "#A3E635",
      pool: ["Sion", "Malphite", "Maokai", "Chogath", "DrMundo", "Zac"],
      dmg: 0.78, kda: 0.78 }
  ];

  const allChampions = Object.keys(window.RIFT_CHAMPIONS || {});
  const profiles = players.map((p) => {
    const base = { id: p.id, dmg: p.dmg, kda: p.kda, pool: p.pool.slice() };
    return base;
  });

  const matches = [];
  const baseTime = Date.UTC(2026, 9, 20, 12, 0, 0);
  const count = 590;

  for (let i = 0; i < count; i++) {
    const duration = Math.round(between(780, 2100));
    const participants = [];
    let groupDamage = 0;

    players.forEach((player, index) => {
      const profile = profiles[index];
      const usePool = rand() < 0.78 && profile.pool.length;
      let champion = usePool ? pick(profile.pool) : pick(allChampions);
      // Keep the spotlight champions well represented.
      if (index === 0 && i % 9 === 0) champion = "Kaisa";
      if (index === 0 && i % 13 === 0) champion = "Ezreal";

      const minutes = duration / 60;
      const damage = Math.round(
        between(520, 900) * minutes * profile.dmg * between(0.82, 1.18)
      );
      const kills = Math.max(0, Math.round(between(2, 16) * profile.kda));
      const deaths = Math.max(1, Math.round(between(3, 11) / profile.kda));
      const assists = Math.max(1, Math.round(between(6, 26) * (index === 2 ? 1.4 : 1)));

      groupDamage += damage;
      participants.push({
        playerId: player.id,
        champion,
        win: false, // filled in below
        kills,
        deaths,
        assists,
        damage
      });
    });

    // Slightly favour the higher-damage team but keep chaos.
    const winChance = Math.min(0.72, Math.max(0.32, groupDamage / (groupDamage + 210000)));
    const win = rand() < winChance;
    participants.forEach((p) => { p.win = win; });

    matches.push({
      id: "demo_" + (1600000000 + i),
      queueId: 2400,
      timestamp: baseTime - Math.round(i * between(1.6, 3.4) * 3600 * 1000),
      duration,
      participants
    });
  }

  matches.sort((a, b) => b.timestamp - a.timestamp);

  window.RIFT_DEMO = {
    generatedAt: "2026-10-20T12:00:00Z",
    source: "demo",
    players: players.map(({ pool, dmg, kda, ...rest }) => rest),
    champions: window.RIFT_CHAMPIONS,
    matches,
    queues: { "2400": "ARAM: Mayhem" }
  };
})();
