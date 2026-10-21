"use strict";

// ---------- Settings and storage ----------

const ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football";
const LOGO = (id) => `https://a.espncdn.com/i/teamlogos/ncaa/500/${id}.png`;
const STRONG = 3, LEAN = 1.5;          // edge thresholds in points
const BREAKEVEN = 0.524;               // hit rate needed at -110
const SOURCE_LABEL = { anchored: "Market-anchored", fpi: "ESPN FPI", blend: "Blend", points: "Adjusted points" };

const store = {
  get(key, fallback) {
    try { const v = localStorage.getItem("cfb." + key); return v === null ? fallback : JSON.parse(v); }
    catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem("cfb." + key, JSON.stringify(value)); } catch { /* private mode: keep going */ }
  },
};

const state = {
  ratings: null,        // {byId, list, updated, season}
  model: null,          // {hfa, anchor, sigma}
  record: null,         // track_record.json
  calendar: [],         // [{label, detail, week, seasontype, start, end}]
  weekIndex: -1,
  season: null,
  games: [],
  filter: "all",
  source: store.get("source", "anchored"),
  sort: store.get("sort", "time"),
  search: "",
  settings: store.get("settings", { hfa: null, sigma: null, theme: "auto" }),
  timer: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const fmtLine = (x) => (x == null ? "—" : x === 0 ? "PK" : (x > 0 ? "+" : "") + x);
const pct = (x, digits = 0) => (x == null ? "—" : (100 * x).toFixed(digits) + "%");
const num = (x) => {
  if (x == null || x === "") return null;
  const s = String(x).trim().toUpperCase();
  if (s === "PK" || s === "EVEN") return 0;
  const v = parseFloat(s.replace(/^[OU]/, ""));
  return Number.isFinite(v) ? v : null;
};

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// ---------- Model (same math as model.py) ----------

function erf(x) {
  // Abramowitz and Stegun 7.1.26, accurate to about 1e-7
  const s = Math.sign(x); x = Math.abs(x);
  const t = 1 / (1 + 0.3275911 * x);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return s * y;
}
const normCdf = (z) => 0.5 * (1 + erf(z / Math.SQRT2));

const hfa = () => state.settings.hfa ?? state.model?.hfa ?? 2.5;
const sigma = () => state.settings.sigma || state.model?.sigma?.[state.source] || 15.5;

/** Projected home margin for one game from every source, or null where a source can't make one. */
function projections(g) {
  const r = state.ratings?.byId || {};
  const h = r[g.home.id], a = r[g.away.id];
  const bump = g.neutral ? 0 : hfa();
  const points = h && a && h.ppg != null && a.ppg != null ? (h.ppg + a.papg) - (a.ppg + h.papg) + bump : null;
  const fpi = h && a && h.fpi != null && a.fpi != null ? h.fpi - a.fpi + bump : null;
  const both = [points, fpi].filter((x) => x != null);
  const blend = both.length ? both.reduce((s, x) => s + x, 0) / both.length : null;
  const w = state.model?.anchor?.weights;
  const base = g.openLine ?? g.line;
  const anchored = w && points != null && fpi != null && base != null
    ? w.const - w.line * base + w.fpi * fpi + w.points * points : null;
  return { points, fpi, blend, anchored };
}

function secsLeft(g) {
  if (g.state === "pre") return 3600;
  if (g.state === "post") return 0;
  return g.period > 4 ? 120 : (4 - g.period) * 900 + g.clock;
}

/** Everything the card needs about the model's view of a game. */
function evaluate(g) {
  const margin = projections(g)[state.source];
  const line = g.line;
  if (margin == null || line == null) return { margin, reason: whyNoPick(g, margin, line) };
  const s = sigma();
  const homeProb = normCdf((margin + line) / s);
  const homePick = homeProb >= 0.5;
  const left = secsLeft(g), cur = g.home.score - g.away.score, x = cur + line;
  let live;
  if (g.state === "pre") live = null;
  else if (left <= 0) live = x > 0 ? 1 : x < 0 ? 0 : 0.5;
  else { const f = Math.min(left / 3600, 1); live = normCdf((x + margin * f) / (s * Math.sqrt(f))); }
  const edge = Math.abs(margin + line);
  return {
    margin, line, edge,
    tier: edge >= STRONG ? "strong" : edge >= LEAN ? "lean" : "pass",
    side: homePick ? "home" : "away",
    team: homePick ? g.home : g.away,
    pickLine: homePick ? line : -line,
    pre: homePick ? homeProb : 1 - homeProb,
    live: live == null ? null : homePick ? live : 1 - live,
  };
}

function whyNoPick(g, margin, line) {
  const r = state.ratings?.byId || {};
  const missing = [g.home, g.away].filter((t) => !r[t.id]).map((t) => t.name);
  if (missing.length) return `No rating for ${missing.join(" and ")} (usually an FCS team)`;
  if (line == null) return g.state === "pre" ? "No line posted yet" : "No pregame line available";
  if (margin == null && state.source === "anchored" && !state.model?.anchor) return "Market-anchored isn't trained yet";
  return "Not enough data for this projection";
}

// ---------- ESPN data ----------

function parseEvent(e) {
  const c = e.competitions[0];
  const t = Object.fromEntries(c.competitors.map((x) => [x.homeAway, x]));
  const team = (x) => ({
    id: x.team.id,
    name: x.team.location || x.team.shortDisplayName,
    abbr: x.team.abbreviation,
    logo: x.team.logo || LOGO(x.team.id),
    rank: x.curatedRank?.current && x.curatedRank.current < 26 ? x.curatedRank.current : null,
    record: x.records?.[0]?.summary || "",
    score: parseInt(x.score || 0, 10),
    winner: x.winner,
  });
  const g = {
    id: e.id, date: e.date, home: team(t.home), away: team(t.away),
    state: c.status.type.state, status: c.status.type.shortDetail,
    period: c.status.period || 0, clock: parseFloat(c.status.clock || 0),
    neutral: !!c.neutralSite, tv: c.broadcasts?.[0]?.names?.join(", ") || "",
    line: null, openLine: null, total: null,
  };
  const o = c.odds?.[0];
  if (o) Object.assign(g, parseOdds(o, g.home.abbr));
  // Remember the pregame line: once a game starts ESPN drops it from the scoreboard
  const saved = store.get("line." + g.id, null);
  if (g.state === "pre" && g.line != null) store.set("line." + g.id, { line: g.line, open: g.openLine, total: g.total });
  else if (saved) { g.line ??= saved.line; g.openLine ??= saved.open; g.total ??= saved.total; }
  return g;
}

function parseOdds(o, homeAbbr) {
  let line = num(o.spread);
  if (line == null && o.details) {
    const d = o.details.trim();
    if (d.toUpperCase() === "EVEN") line = 0;
    else { const i = d.lastIndexOf(" "); const v = num(d.slice(i + 1)); if (v != null) line = d.slice(0, i) === homeAbbr ? v : -v; }
  }
  return { line, openLine: num(o.pointSpread?.home?.open?.line), total: num(o.overUnder) };
}

/** Started games with no saved pregame line: ESPN's game summary still has it. */
async function fillMissingLines(games) {
  const todo = games.filter((g) => g.state !== "pre" && g.line == null).slice(0, 40);
  await Promise.all(todo.map(async (g) => {
    try {
      const pc = (await getJSON(`${ESPN}/summary?event=${g.id}`)).pickcenter?.[0];
      if (!pc || pc.spread == null) return;
      g.line = num(pc.spread); g.openLine = num(pc.pointSpread?.home?.open?.line); g.total = num(pc.overUnder);
      store.set("line." + g.id, { line: g.line, open: g.openLine, total: g.total });
    } catch { /* leave the game without a line */ }
  }));
}

async function loadWeek(index) {
  const params = new URLSearchParams({ groups: 80, limit: 300 });
  if (index >= 0 && state.calendar[index]) {
    const w = state.calendar[index];
    params.set("dates", state.season); params.set("seasontype", w.seasontype); params.set("week", w.week);
  }
  const data = await getJSON(`${ESPN}/scoreboard?${params}`);
  if (!state.calendar.length) {
    state.season = data.season?.year;
    state.calendar = (data.leagues?.[0]?.calendar || [])
      .filter((c) => c.value === "2" || c.value === "3")
      .flatMap((c) => (c.entries || []).map((x) => ({
        label: x.label, detail: x.detail, week: x.value, seasontype: c.value, start: x.startDate, end: x.endDate })));
    state.weekIndex = state.calendar.findIndex((w) => String(w.week) === String(data.week?.number)
      && String(w.seasontype) === String(data.season?.type));
  }
  const games = (data.events || []).map(parseEvent);
  await fillMissingLines(games);
  state.games = games;
  gradePicks(games);
}

// ---------- Games tab ----------

function renderWeekbar() {
  const w = state.calendar[state.weekIndex];
  $("#week-name").textContent = w ? w.label : "This week";
  $("#week-dates").textContent = w?.detail || "";
  $("#week-prev").disabled = state.weekIndex <= 0;
  $("#week-next").disabled = state.weekIndex < 0 || state.weekIndex >= state.calendar.length - 1;
}

function renderGames() {
  const q = state.search.trim().toLowerCase();
  let rows = state.games.map((g) => ({ g, ev: evaluate(g) }));
  rows = rows.filter(({ g, ev }) => {
    if (q && !`${g.home.name} ${g.away.name} ${g.home.abbr} ${g.away.abbr}`.toLowerCase().includes(q)) return false;
    if (state.filter === "edge") return ev.edge >= LEAN;
    if (state.filter === "strong") return ev.edge >= STRONG;
    if (state.filter === "live") return g.state === "in";
    return true;
  });
  if (state.sort === "edge") rows.sort((a, b) => (b.ev.edge ?? -1) - (a.ev.edge ?? -1));
  else rows.sort((a, b) => a.g.date.localeCompare(b.g.date) || (b.ev.edge ?? -1) - (a.ev.edge ?? -1));

  const all = state.games.map(evaluate);
  const live = state.games.filter((g) => g.state === "in").length;
  $("#games-summary").textContent = state.games.length
    ? `${state.games.length} games · ${all.filter((e) => e.edge >= STRONG).length} strong edges · ` +
      `${all.filter((e) => e.edge >= LEAN && e.edge < STRONG).length} leans` + (live ? ` · ${live} live now` : "") +
      ` · projection: ${SOURCE_LABEL[state.source]}, std dev ${sigma()}`
    : "";

  const box = $("#games");
  if (!rows.length) {
    box.innerHTML = `<div class="card nopick">${state.games.length ? "No games match these filters." : "No games this week."}</div>`;
    return;
  }
  const tracked = new Set(store.get("picks", []).map((p) => p.id));
  let html = "", day = "";
  const byDay = state.sort === "time";
  for (const { g, ev } of rows) {
    const d = new Date(g.date).toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
    if (byDay && d !== day) { html += (day ? "</div>" : "") + `<h2 class="day-head">${esc(d)}</h2><div class="grid">`; day = d; }
    html += card(g, ev, tracked.has(g.id));
  }
  box.innerHTML = byDay ? html + "</div>" : `<div class="grid">${html}</div>`;
}

function teamRow(t, g) {
  const showScore = g.state !== "pre";
  const lost = g.state === "post" && t.winner === false;
  return `<div class="team${lost ? " lost" : ""}">
    <img src="${esc(t.logo)}" alt="" loading="lazy">
    <span class="name">${t.rank ? `<span class="rank">${t.rank}</span>` : ""}${esc(t.name)}<span class="rec">${esc(t.record)}</span></span>
    ${showScore ? `<span class="score">${t.score}</span>` : ""}
  </div>`;
}

function card(g, ev, isTracked) {
  const time = g.state === "pre"
    ? new Date(g.date).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })
    : g.status;
  const statusCls = g.state === "in" ? "status live" : "status";
  const moved = g.openLine != null && g.line != null && g.openLine !== g.line
    ? `<span class="open"> opened ${fmtLine(g.openLine)}</span>` : "";
  const homeLine = g.line == null ? "—" : `${esc(g.home.abbr)} ${fmtLine(g.line)}`;
  let body;
  if (ev.margin == null || ev.line == null) {
    body = `<div class="nopick">${esc(ev.reason)}</div>`;
  } else {
    const fav = ev.margin >= 0 ? g.home : g.away;
    const modelTxt = Math.abs(ev.margin) < 0.05 ? "Even" : `${esc(fav.abbr)} by ${Math.abs(ev.margin).toFixed(1)}`;
    const tierTxt = { strong: "Strong edge", lean: "Lean", pass: "Small edge" }[ev.tier];
    const p = ev.live ?? ev.pre;
    const done = g.state === "post";
    const barCls = done ? (ev.live > 0.5 ? "good" : ev.live < 0.5 ? "bad" : "") : "";
    const result = done ? (ev.live > 0.5 ? `<span class="badge win">Covered</span>` : ev.live < 0.5 ? `<span class="badge loss">Didn't cover</span>` : `<span class="badge pass">Push</span>`) : "";
    body = `
      <div class="pick-row">
        <span class="pick">${esc(ev.team.name)} ${fmtLine(ev.pickLine)}</span>
        ${result || `<span class="badge ${ev.tier}">${tierTxt} · ${ev.edge.toFixed(1)}</span>`}
      </div>
      <div class="prob">
        <div class="row"><span>${g.state === "pre" ? "Cover chance" : done ? "Final" : "Live cover chance"}</span><b>${done ? "" : pct(p)}</b></div>
        <div class="bar ${barCls}"><i style="width:${(100 * p).toFixed(0)}%"></i></div>
        ${g.state !== "pre" ? `<div class="row"><span>Before kickoff</span><b>${pct(ev.pre)}</b></div>` : ""}
      </div>
      <div class="lines" style="margin-bottom:0"><div><span class="k">Model</span><span class="v">${modelTxt}</span></div>
        <div><span class="k">Edge</span><span class="v">${ev.edge.toFixed(1)} pts</span></div></div>`;
  }
  const canTrack = g.state === "pre" && ev.margin != null && ev.line != null;
  return `<article class="card game${ev.tier === "strong" ? " strong" : ""}">
    <div class="game-top"><span class="${statusCls}">${esc(time)}</span><span>${esc(g.tv)}${g.neutral ? " · Neutral site" : ""}</span></div>
    ${teamRow(g.away, g)}${teamRow(g.home, g)}
    <div class="lines">
      <div><span class="k">Line</span><span class="v">${homeLine}</span>${moved}</div>
      <div><span class="k">Total</span><span class="v">${g.total ?? "—"}</span></div>
    </div>
    ${body}
    <div class="game-foot">
      <span>${g.away.abbr} @ ${g.home.abbr}</span>
      <button class="track${isTracked ? " on" : ""}" data-track="${esc(g.id)}" ${canTrack || isTracked ? "" : "disabled"}>
        ${isTracked ? "★ Tracked" : "☆ Track pick"}</button>
    </div>
  </article>`;
}

function toggleTrack(id) {
  const picks = store.get("picks", []);
  const i = picks.findIndex((p) => p.id === id);
  if (i >= 0) { picks.splice(i, 1); store.set("picks", picks); return renderAll(); }
  const g = state.games.find((x) => x.id === id);
  const ev = g && evaluate(g);
  if (!g || g.state !== "pre" || !ev || ev.margin == null) return;
  const w = state.calendar[state.weekIndex];
  picks.push({
    id, date: g.date, season: state.season, week: w?.week, seasontype: w?.seasontype,
    game: `${g.away.name} @ ${g.home.name}`, pick: `${ev.team.name} ${fmtLine(ev.pickLine)}`,
    side: ev.side, line: ev.line, edge: +ev.edge.toFixed(1), prob: +ev.pre.toFixed(3),
    source: state.source, result: null, finalMargin: null,
  });
  store.set("picks", picks);
  renderAll();
}

// ---------- My picks ----------

function gradeOne(p, g) {
  if (!g || g.state !== "post" || p.result) return false;
  const m = g.home.score - g.away.score;
  const x = (m + p.line) * (p.side === "home" ? 1 : -1);
  p.finalMargin = m; p.result = x > 0 ? "W" : x < 0 ? "L" : "P";
  return true;
}

function gradePicks(games) {
  const picks = store.get("picks", []);
  const byId = Object.fromEntries(games.map((g) => [g.id, g]));
  if (picks.some((p) => gradeOne(p, byId[p.id]))) store.set("picks", picks);
}

/** Grade picks from other weeks by loading each of those weeks once. */
async function gradeOldPicks() {
  const picks = store.get("picks", []);
  const weeks = new Map();
  for (const p of picks) {
    if (!p.result && new Date(p.date) < Date.now() - 4 * 3600e3 && p.week)
      weeks.set(`${p.season}-${p.seasontype}-${p.week}`, p);
  }
  let changed = false;
  for (const p of weeks.values()) {
    try {
      const d = await getJSON(`${ESPN}/scoreboard?groups=80&limit=300&dates=${p.season}&seasontype=${p.seasontype}&week=${p.week}`);
      const byId = Object.fromEntries((d.events || []).map((e) => [e.id, parseEvent(e)]));
      for (const q of picks) changed = gradeOne(q, byId[q.id]) || changed;
    } catch { /* try again next visit */ }
  }
  if (changed) { store.set("picks", picks); renderPicks(); }
}

function renderPicks() {
  const picks = store.get("picks", []).slice().sort((a, b) => b.date.localeCompare(a.date));
  const done = picks.filter((p) => p.result === "W" || p.result === "L");
  const wins = done.filter((p) => p.result === "W").length;
  const strong = done.filter((p) => p.edge >= STRONG);
  const sw = strong.filter((p) => p.result === "W").length;
  $("#pick-stats").innerHTML = [
    ["Tracked picks", picks.length],
    ["Record", `${wins}-${done.length - wins}${picks.some((p) => p.result === "P") ? `-${picks.filter((p) => p.result === "P").length}` : ""}`],
    ["Hit rate", done.length ? pct(wins / done.length, 1) : "—"],
    ["Strong edges", strong.length ? `${sw}-${strong.length - sw}` : "—"],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  const res = { W: `<span class="badge win">Won</span>`, L: `<span class="badge loss">Lost</span>`, P: `<span class="badge pass">Push</span>` };
  $("#picks-table").innerHTML = `<tr><th>Game</th><th class="l">Pick</th><th>Edge</th><th>Chance</th><th class="l">Projection</th><th class="l">Result</th><th></th></tr>` +
    (picks.length ? picks.map((p) => `<tr>
      <td class="l">${esc(new Date(p.date).toLocaleDateString(undefined, { month: "short", day: "numeric" }))} · ${esc(p.game)}</td>
      <td class="l"><b>${esc(p.pick)}</b></td><td>${p.edge.toFixed(1)}</td><td>${pct(p.prob)}</td>
      <td class="l">${esc(SOURCE_LABEL[p.source] || p.source)}</td>
      <td class="l">${p.result ? res[p.result] : `<span class="note">Pending</span>`}</td>
      <td><button data-unpick="${esc(p.id)}" title="Remove">✕</button></td></tr>`).join("")
      : `<tr><td colspan="7" class="empty">No tracked picks yet. Use ☆ Track pick on the Games tab.</td></tr>`);
}

// ---------- Bets ----------

const BET_COLS = ["date", "game", "side", "line", "odds", "stake", "result"];

function profit(b) {
  const stake = +b.stake || 0, odds = +b.odds || -110;
  if (b.result === "W") return stake * (odds < 0 ? 100 / -odds : odds / 100);
  return b.result === "L" ? -stake : 0;
}

function renderBets() {
  const bets = store.get("bets", []);
  const graded = bets.filter((b) => b.result);
  const net = graded.reduce((s, b) => s + profit(b), 0);
  const staked = graded.reduce((s, b) => s + (+b.stake || 0), 0);
  const wins = graded.filter((b) => b.result === "W").length, losses = graded.filter((b) => b.result === "L").length;
  $("#bet-stats").innerHTML = [
    ["Bets", bets.length], ["Record", `${wins}-${losses}`],
    ["Net profit", `${net >= 0 ? "+" : "−"}$${Math.abs(net).toFixed(2)}`],
    ["ROI", staked ? `${net >= 0 ? "+" : ""}${(100 * net / staked).toFixed(1)}%` : "—"],
  ].map(([k, v]) => `<div class="stat"><div class="k">${k}</div><div class="v">${v}</div></div>`).join("");
  $("#bets-table").innerHTML = `<tr><th>Date</th><th class="l">Game</th><th class="l">Side</th><th>Line</th><th>Odds</th><th>Stake</th><th class="l">Result</th><th>Profit</th><th></th></tr>` +
    (bets.length ? bets.map((b, i) => `<tr>
      <td class="l">${esc(b.date)}</td><td class="l">${esc(b.game)}</td><td class="l">${esc(b.side)}</td>
      <td>${b.line === "" || b.line == null ? "—" : fmtLine(+b.line)}</td><td>${esc(b.odds || -110)}</td><td>$${(+b.stake).toFixed(2)}</td>
      <td class="l"><select data-bet="${i}"><option value="">Pending</option>${["W", "L", "Push"].map((r) =>
        `<option value="${r}" ${b.result === r ? "selected" : ""}>${{ W: "Won", L: "Lost", Push: "Push" }[r]}</option>`).join("")}</select></td>
      <td class="${profit(b) > 0 ? "good" : profit(b) < 0 ? "bad" : ""}">${b.result ? (profit(b) >= 0 ? "+" : "−") + "$" + Math.abs(profit(b)).toFixed(2) : "—"}</td>
      <td><button data-delbet="${i}" title="Delete">✕</button></td></tr>`).join("")
      : `<tr><td colspan="9" class="empty">No bets yet. Add one above.</td></tr>`);
}

function csvCell(v) { const s = String(v ?? ""); return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s; }

function parseCSV(text) {
  const rows = []; let row = [], cell = "", q = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (q) { if (c === '"' && text[i + 1] === '"') { cell += '"'; i++; } else if (c === '"') q = false; else cell += c; }
    else if (c === '"') q = true;
    else if (c === ",") { row.push(cell); cell = ""; }
    else if (c === "\n" || c === "\r") { if (c === "\r" && text[i + 1] === "\n") i++; row.push(cell); rows.push(row); row = []; cell = ""; }
    else cell += c;
  }
  if (cell || row.length) { row.push(cell); rows.push(row); }
  return rows.filter((r) => r.some((x) => x.trim()));
}

// ---------- Ratings ----------

let ratingSort = { key: "fpi", dir: -1 };

function renderRatings() {
  const list = state.ratings?.list || [];
  const q = $("#rating-search").value.trim().toLowerCase();
  const fpiRank = new Map([...list].filter((t) => t.fpi != null).sort((a, b) => b.fpi - a.fpi).map((t, i) => [t.team, i + 1]));
  const rows = list.filter((t) => !q || t.team.toLowerCase().includes(q)).map((t) => ({ ...t, net: t.ppg - t.papg, rank: fpiRank.get(t.team) }));
  const k = ratingSort.key, d = ratingSort.dir;
  rows.sort((a, b) => (typeof a[k] === "string" ? a[k].localeCompare(b[k]) : ((a[k] ?? -1e9) - (b[k] ?? -1e9))) * d);
  const cols = [["rank", "#"], ["team", "Team"], ["fpi", "FPI"], ["ppg", "Offense"], ["papg", "Defense"], ["net", "Net"], ["games", "Games"]];
  $("#ratings-table").innerHTML = `<tr>${cols.map(([c, l]) => `<th data-sort="${c}" class="${c === "team" ? "l" : ""}">${l}${k === c ? (d > 0 ? " ▲" : " ▼") : ""}</th>`).join("")}</tr>` +
    rows.map((t) => `<tr><td>${t.rank ?? ""}</td><td class="l"><img src="${LOGO(t.id)}" alt="" loading="lazy">${esc(t.team)}</td>
      <td>${t.fpi?.toFixed(1) ?? "—"}</td><td>${t.ppg.toFixed(1)}</td><td>${t.papg.toFixed(1)}</td>
      <td class="${t.net > 0 ? "good" : "bad"}">${(t.net > 0 ? "+" : "") + t.net.toFixed(1)}</td><td>${t.games}</td></tr>`).join("");
  $("#ratings-summary").textContent = state.ratings
    ? `${list.length} FBS teams · updated ${new Date(state.ratings.updated).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}`
    : "";
}

// ---------- Track record ----------

let recAgainst = "open", recEdge = "0";

function renderRecord() {
  const r = state.record;
  if (!r) { $("#record-headline").innerHTML = `<div class="card">Track record isn't available yet.</div>`; return; }
  const rows = (key) => (r.tables[key] || []).filter((x) => !/baseline/.test(x.name));
  const best = (key) => rows(key).filter((x) => x.picks).sort((a, b) => b.hit_rate - a.hit_rate)[0];
  const open3 = best("open_3"), close0 = best("close_0"), open0 = best("open_0");
  const moved = rows("open_3").filter((x) => x.clv_beat_rate != null).sort((a, b) => b.clv_beat_rate - a.clv_beat_rate)[0];
  $("#record-headline").innerHTML = [
    ["Betting at the closing line", close0 && close0.hit_rate >= BREAKEVEN ? pct(close0.hit_rate, 1) : "No edge",
      `Best source: ${close0?.name} at ${pct(close0?.hit_rate, 1)}. Break-even is 52.4%. The final line is very hard to beat.`],
    ["Opening line, every game", pct(open0?.hit_rate, 1), `${open0?.name}, ${open0?.wins}-${open0?.losses}. Just above break-even.`],
    ["Opening line, 3+ pt edges", pct(open3?.hit_rate, 1), `${open3?.name}, ${open3?.wins}-${open3?.losses}. The strongest result, but a small sample.`],
    ["Line moved toward the pick", pct(moved?.clv_beat_rate), `${moved?.name}, 3+ pt edges. Lines moving your way is the best sign of a real edge.`],
  ].map(([h, big, p]) => `<div class="card"><h4>${h}</h4><div class="big">${big}</div><p>${esc(p)}</p></div>`).join("");

  const t = r.tables[`${recAgainst}_${recEdge}`] || [];
  const clv = recAgainst === "open";
  $("#record-table").innerHTML = `<tr><th>Projection</th><th>Picks</th><th>Record</th><th>Hit rate</th><th>Typical miss</th>${clv ? "<th>Line moved our way</th>" : ""}</tr>` +
    t.map((x) => /baseline/.test(x.name)
      ? `<tr><td class="l note">${esc(x.name.replace(" (baseline)", ""))} itself</td><td></td><td></td><td></td><td>${x.rmse_vs_result?.toFixed(1)}</td>${clv ? "<td></td>" : ""}</tr>`
      : `<tr><td class="l">${esc(x.name)}</td><td>${x.picks ?? 0}</td><td>${x.wins ?? 0}-${x.losses ?? 0}</td>
        <td class="${x.hit_rate >= BREAKEVEN ? "good" : "bad"}">${pct(x.hit_rate, 1)}</td><td>${x.rmse_vs_result?.toFixed(1)}</td>
        ${clv ? `<td>${pct(x.clv_beat_rate)}</td>` : ""}</tr>`).join("");

  const names = (r.tables.open_0 || []).map((x) => x.name).filter((n) => !/baseline/.test(n));
  $("#season-table").innerHTML = `<tr><th>Season</th><th>Games</th>${names.map((n) => `<th>${esc(n)}</th>`).join("")}</tr>` +
    r.by_season.map((s) => `<tr><td class="l">${s.season}</td><td>${s.games}</td>${names.map((n) =>
      `<td class="${s[n] == null ? "" : s[n] >= BREAKEVEN ? "good" : "bad"}">${s[n] == null ? "—" : pct(s[n], 1)}</td>`).join("")}</tr>`).join("");
}

// ---------- Wiring ----------

function renderAll() { renderWeekbar(); renderGames(); renderPicks(); renderBets(); }

function applyTheme() {
  const t = state.settings.theme;
  if (t === "auto") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
}

async function refresh(index = state.weekIndex) {
  try {
    await loadWeek(index);
    renderAll();
    $("#updated").textContent = `Scores updated ${new Date().toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" })}` +
      (state.ratings ? ` · ratings ${new Date(state.ratings.updated).toLocaleDateString(undefined, { month: "short", day: "numeric" })}` : "");
  } catch (e) {
    $("#games").innerHTML = `<div class="card error">Couldn't load games from ESPN (${esc(e.message)}). Check your connection and try again.</div>`;
  }
  clearTimeout(state.timer);
  // Live games refresh every 30 seconds; otherwise every 5 minutes
  state.timer = setTimeout(() => refresh(), state.games.some((g) => g.state === "in") ? 30e3 : 300e3);
}

function bind() {
  const showTab = () => {
    const name = $(`.tabs button[data-tab="${location.hash.slice(1)}"]`) ? location.hash.slice(1) : "games";
    $$(".tabs button").forEach((x) => x.setAttribute("aria-selected", x.dataset.tab === name));
    $$(".tab").forEach((s) => (s.hidden = s.id !== "tab-" + name));
    if (name === "picks") gradeOldPicks();
  };
  $$(".tabs button").forEach((b) => b.addEventListener("click", () => { location.hash = b.dataset.tab; }));
  window.addEventListener("hashchange", showTab);
  showTab();

  $("#week-prev").addEventListener("click", () => { if (state.weekIndex > 0) refresh(--state.weekIndex); });
  $("#week-next").addEventListener("click", () => { if (state.weekIndex < state.calendar.length - 1) refresh(++state.weekIndex); });

  const src = $("#source"); src.value = state.source;
  src.addEventListener("change", () => { state.source = src.value; store.set("source", state.source); renderGames(); });
  const sort = $("#sort"); sort.value = state.sort;
  sort.addEventListener("change", () => { state.sort = sort.value; store.set("sort", state.sort); renderGames(); });
  $("#search").addEventListener("input", (e) => { state.search = e.target.value; renderGames(); });
  $$("#filter button").forEach((b) => b.addEventListener("click", () => {
    $$("#filter button").forEach((x) => x.classList.toggle("on", x === b));
    state.filter = b.dataset.filter; renderGames();
  }));

  document.addEventListener("click", (e) => {
    const t = e.target.closest("[data-track],[data-unpick],[data-delbet],th[data-sort]");
    if (!t) return;
    if (t.dataset.track) toggleTrack(t.dataset.track);
    else if (t.dataset.unpick) { store.set("picks", store.get("picks", []).filter((p) => p.id !== t.dataset.unpick)); renderAll(); }
    else if (t.dataset.delbet) { const b = store.get("bets", []); b.splice(+t.dataset.delbet, 1); store.set("bets", b); renderBets(); }
    else { const k = t.dataset.sort; ratingSort = { key: k, dir: ratingSort.key === k ? -ratingSort.dir : k === "team" ? 1 : -1 }; renderRatings(); }
  });
  $("#bets-table").addEventListener("change", (e) => {
    const i = e.target.dataset.bet; if (i == null) return;
    const b = store.get("bets", []); b[+i].result = e.target.value || null; store.set("bets", b); renderBets();
  });
  $("#picks-clear").addEventListener("click", () => {
    if (confirm("Remove all tracked picks from this browser?")) { store.set("picks", []); renderAll(); }
  });

  const form = $("#bet-form");
  const today = () => new Date().toLocaleDateString("en-CA");  // YYYY-MM-DD in local time
  form.date.value = today();
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const b = Object.fromEntries(new FormData(form)); b.result = null;
    store.set("bets", [...store.get("bets", []), b]);
    form.reset(); form.date.value = today();
    renderBets();
  });
  $("#bets-export").addEventListener("click", () => {
    const rows = [BET_COLS, ...store.get("bets", []).map((b) => BET_COLS.map((c) => b[c] ?? ""))];
    const a = document.createElement("a");
    a.href = URL.createObjectURL(new Blob([rows.map((r) => r.map(csvCell).join(",")).join("\n")], { type: "text/csv" }));
    a.download = "bets.csv"; a.click(); URL.revokeObjectURL(a.href);
  });
  $("#bets-import").addEventListener("change", async (e) => {
    const f = e.target.files[0]; if (!f) return;
    const [head, ...rows] = parseCSV(await f.text());
    const idx = head.map((h) => h.trim().toLowerCase());
    const imported = rows.map((r) => Object.fromEntries(BET_COLS.map((c) => [c, r[idx.indexOf(c)] ?? ""])))
      .map((b) => ({ ...b, result: b.result || null }));
    store.set("bets", [...store.get("bets", []), ...imported]);
    e.target.value = ""; renderBets();
  });

  $("#rating-search").addEventListener("input", renderRatings);
  for (const [id, setter] of [["#rec-against", (v) => (recAgainst = v)], ["#rec-edge", (v) => (recEdge = v)]]) {
    $$(`${id} button`).forEach((b) => b.addEventListener("click", () => {
      $$(`${id} button`).forEach((x) => x.classList.toggle("on", x === b)); setter(b.dataset.v); renderRecord();
    }));
  }

  const dlg = $("#settings");
  $("#settings-btn").addEventListener("click", () => {
    $("#set-hfa").value = hfa(); $("#set-sigma").value = state.settings.sigma ?? ""; $("#set-theme").value = state.settings.theme;
    dlg.showModal();
  });
  dlg.addEventListener("close", () => {
    const h = parseFloat($("#set-hfa").value), s = parseFloat($("#set-sigma").value);
    state.settings = { hfa: Number.isFinite(h) ? h : null, sigma: Number.isFinite(s) ? s : null, theme: $("#set-theme").value };
    store.set("settings", state.settings); applyTheme(); renderGames();
  });
}

async function init() {
  applyTheme();
  bind();
  const [ratings, model, record] = await Promise.all(
    ["ratings", "model", "track_record"].map((n) => getJSON(`data/${n}.json`).catch(() => null)));
  if (ratings) state.ratings = { ...ratings, list: ratings.teams, byId: Object.fromEntries(ratings.teams.map((t) => [String(t.id), t])) };
  state.model = model;
  state.record = record;
  renderRatings();
  renderRecord();
  await refresh(-1);
}

init();
