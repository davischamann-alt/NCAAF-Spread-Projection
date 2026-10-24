"use strict";
// Game detail view: opened by tapping a game card, at #game/<ESPN game id>. Combines ESPN's
// per-game summary feed with the site's own projections, ratings and forward-test log.

const GAME_STATS_SHOWN = ["Total Yards", "Passing", "Rushing", "Turnovers", "3rd down efficiency", "Possession"];
let gameTimer = null, gameLog = null;

async function loadGameLog() {
  try { gameLog = await getJSON("data/game_log.json"); } catch { gameLog = gameLog || {}; }
  return gameLog;
}

/** A game in the same shape as parseEvent() makes, from the summary feed (for games not on the board). */
function gameFromSummary(s) {
  const c = s.header.competitions[0];
  const t = Object.fromEntries(c.competitors.map((x) => [x.homeAway, x]));
  const team = (x) => ({
    id: x.team.id, name: x.team.location || x.team.displayName, abbr: x.team.abbreviation,
    logo: x.team.logos?.[0]?.href || LOGO(x.team.id), rank: x.rank && x.rank < 26 ? x.rank : null,
    record: x.record?.find((r) => r.type === "total")?.summary || "", score: parseInt(x.score || 0, 10), winner: x.winner,
  });
  const g = {
    id: String(c.id), date: c.date, home: team(t.home), away: team(t.away), state: c.status.type.state,
    status: c.status.type.shortDetail, period: c.status.period || 0, clock: parseFloat(c.status.clock || 0),
    neutral: !!c.neutralSite, tv: (c.broadcasts || []).map((b) => b.media?.shortName).filter(Boolean).join(", "),
    line: null, openLine: null, total: null,
  };
  const saved = store.get("line." + g.id, null);
  if (saved) Object.assign(g, { line: saved.line, openLine: saved.open, total: saved.total });
  return g;
}

/** Every source's view of the game, using each source's own tested std dev. */
function allSources(g) {
  const proj = projections(g);
  return ["anchored", "fpi", "blend", "points"].map((src) => {
    const m = proj[src];
    if (m == null || g.line == null) return { src, margin: m };
    const s = state.settings.sigma || state.model?.sigma?.[src] || 15.5;
    const edge = m + g.line, home = edge >= 0, homeProb = normCdf(edge / s);
    return {
      src, margin: m, edge: Math.abs(edge), side: home ? "home" : "away", team: home ? g.home : g.away,
      pickLine: home ? g.line : -g.line, prob: home ? homeProb : 1 - homeProb,
      tier: Math.abs(edge) >= STRONG ? "strong" : Math.abs(edge) >= LEAN ? "lean" : "pass",
    };
  });
}

const TIER_TXT = { strong: "Go for it", lean: "Lean", pass: "Punt" };
const marginTxt = (g, m) => (Math.abs(m) < 0.05 ? "Even" : `${(m >= 0 ? g.home : g.away).abbr} by ${Math.abs(m).toFixed(1)}`);
const lineTxt = (g, line) => (line == null ? "—" : `${g.home.abbr} ${fmtLine(line)}`);

function headerCard(g, s) {
  const venue = s.gameInfo?.venue;
  const when = new Date(g.date).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  const status = g.state === "pre" ? when : g.status;
  const team = (t) => `<div class="gd-team${g.state === "post" && t.winner === false ? " lost" : ""}">
      <img src="${esc(t.logo)}" alt="">
      <div class="gd-name">${t.rank ? `<span class="rank">${t.rank}</span>` : ""}${esc(t.name)}<span>${esc(t.record)}</span></div>
      ${g.state === "pre" ? "" : `<div class="gd-score">${t.score}</div>`}
    </div>`;
  return `<div class="card gd-head">
    <div class="game-top"><span class="${g.state === "in" ? "status live" : "status"}">${esc(status)}</span>
      <span>${esc(g.tv)}${g.neutral ? " · Neutral site" : ""}</span></div>
    ${team(g.away)}<div class="gd-at">at</div>${team(g.home)}
    <div class="lines">
      <div><span class="k">Line</span><span class="v">${esc(lineTxt(g, g.line))}</span>
        ${g.openLine != null && g.openLine !== g.line ? `<span class="open"> opened ${fmtLine(g.openLine)}</span>` : ""}</div>
      <div><span class="k">Total</span><span class="v">${g.total ?? "—"}</span></div>
    </div>
    ${venue ? `<p class="note">${esc(venue.fullName)}${venue.address?.city ? `, ${esc(venue.address.city)}${venue.address.state ? ", " + esc(venue.address.state) : ""}` : ""}</p>` : ""}
  </div>`;
}

function pickCard(g) {
  const rows = allSources(g);
  const usable = rows.filter((r) => r.edge != null);
  if (!usable.length) {
    return `<div class="card"><h3>Why this pick</h3><p class="nopick">${esc(evaluate(g).reason || "No projection for this game.")}</p></div>`;
  }
  const chosen = rows.find((r) => r.src === state.source && r.edge != null) || usable[0];
  const same = usable.filter((r) => r.side === chosen.side).length;
  const verdict = same === usable.length
    ? `All ${usable.length} projections take <b>${esc(chosen.team.name)}</b>.`
    : `Projections split: ${same} take <b>${esc(chosen.team.name)}</b>, ${usable.length - same} take the other side. A split is a reason to punt.`;
  return `<div class="card"><h3>Why this pick</h3>
    <p>${verdict}</p>
    <div class="table-wrap"><table class="data">
      <tr><th>Projection</th><th>Model</th><th class="l">Pick</th><th>Edge</th><th>Cover</th></tr>
      ${rows.map((r) => `<tr class="${r.src === chosen.src ? "gd-chosen" : ""}">
        <td class="l">${esc(SOURCE_LABEL[r.src])}${r.src === state.source ? " ★" : ""}</td>
        <td>${r.margin == null ? "—" : esc(marginTxt(g, r.margin))}</td>
        <td class="l">${r.edge == null ? "—" : `<b>${esc(r.team.abbr)} ${fmtLine(r.pickLine)}</b>`}</td>
        <td>${r.edge == null ? "—" : `<span class="badge ${r.tier}">${TIER_TXT[r.tier]} · ${r.edge.toFixed(1)}</span>`}</td>
        <td>${r.edge == null ? "—" : pct(r.prob)}</td></tr>`).join("")}
    </table></div>
    <p class="note">★ is the projection chosen on the Games tab. Each uses its own tested std dev for the cover chance.
      ${g.state === "pre" ? "" : "These use today's ratings, which can include this game's own result. <b>Forward test</b> below shows the picks as they were recorded before kickoff."}</p>
  </div>`;
}

/** Small SVG line chart. points: [[x, y]]; x in ms. */
function lineChart(points, { yFmt = (v) => v, height = 140, step = false, yMin, yMax, mid } = {}) {
  const W = 600, H = height, P = { l: 56, r: 12, t: 12, b: 24 };
  const xs = points.map((p) => p[0]), ys = points.map((p) => p[1]);
  let lo = yMin ?? Math.min(...ys), hi = yMax ?? Math.max(...ys);
  // give a nearly flat line some room, unless the caller fixed the range (e.g. 0-100%)
  if (yMin == null && yMax == null && hi - lo < 2) { const c = (hi + lo) / 2; lo = c - 1; hi = c + 1; }
  const x0 = Math.min(...xs), x1 = Math.max(...xs) || x0 + 1;
  const X = (x) => P.l + ((x - x0) / Math.max(x1 - x0, 1)) * (W - P.l - P.r);
  const Y = (y) => P.t + ((hi - y) / (hi - lo)) * (H - P.t - P.b);
  let d = "";
  points.forEach(([x, y], i) => {
    if (i === 0) d += `M${X(x)},${Y(y)}`;
    else d += step ? `H${X(x)}V${Y(y)}` : `L${X(x)},${Y(y)}`;
  });
  const ticks = [hi, (hi + lo) / 2, lo];
  return `<svg class="gd-chart" viewBox="0 0 ${W} ${H}" role="img">
    ${ticks.map((t) => `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(t)}" y2="${Y(t)}" class="grid"/>
      <text x="${P.l - 8}" y="${Y(t) + 4}" text-anchor="end">${esc(yFmt(t))}</text>`).join("")}
    ${mid != null ? `<line x1="${P.l}" x2="${W - P.r}" y1="${Y(mid)}" y2="${Y(mid)}" class="mid"/>` : ""}
    <path d="${d}" class="line"/>
    ${points.length < 40 ? points.map(([x, y]) => `<circle cx="${X(x)}" cy="${Y(y)}" r="4" class="dot"/>`).join("") : ""}
  </svg>`;
}

function lineCard(g, log) {
  const pts = (log?.lines || []).map(([t, l]) => [Date.parse(t), l]);
  if (g.openLine != null && (!pts.length || pts[0][1] !== g.openLine)) pts.unshift([pts.length ? pts[0][0] - 36e5 : Date.parse(g.date) - 6 * 864e5, g.openLine]);
  if (g.state === "pre" && g.line != null && (!pts.length || pts[pts.length - 1][1] !== g.line)) pts.push([Date.now(), g.line]);
  if (g.state === "pre" && pts.length) pts.push([Date.now(), pts[pts.length - 1][1]]);
  const first = pts[0]?.[1], last = pts[pts.length - 1]?.[1];
  let text = "No line history for this game yet.";
  if (first != null) {
    const moved = last - first;
    text = moved === 0
      ? `Opened at ${esc(lineTxt(g, first))} and hasn't moved.`
      : `Opened at ${esc(lineTxt(g, first))}, now ${esc(lineTxt(g, last))}: moved ${Math.abs(moved)} point${Math.abs(moved) === 1 ? "" : "s"} toward <b>${esc((moved < 0 ? g.home : g.away).name)}</b>.`;
  }
  return `<div class="card"><h3>Line movement</h3><p>${text}</p>
    ${pts.length > 1 ? lineChart(pts, { step: true, yFmt: (v) => `${g.home.abbr} ${fmtLine(Math.round(v * 2) / 2)}` }) : ""}
    <p class="note">Recorded every two hours by the forward test. A falling number means the market moved toward ${esc(g.home.name)}.</p>
  </div>`;
}

function matchupCard(g, s) {
  const r = state.ratings?.byId || {};
  const list = state.ratings?.list || [];
  const rank = (t) => { const v = r[t.id]?.fpi; return v == null ? null : list.filter((x) => x.fpi > v).length + 1; };
  // one comparison row; "better" highlights the stronger side when both have a number
  const row = (label, a, h, better) => {
    const good = (x, y) => (better && x != null && y != null && better(x, y) ? "good" : "");
    return `<tr><td class="${good(a.n, h.n)}">${a.v ?? "—"}</td><td class="gd-mid">${label}</td><td class="${good(h.n, a.n)}">${h.v ?? "—"}</td></tr>`;
  };
  const ra = r[g.away.id], rh = r[g.home.id];
  const fmt = (v) => (v == null ? null : v.toFixed(1));
  let rows = row("FPI (rank)", { v: ra?.fpi == null ? null : `${fmt(ra.fpi)} (#${rank(g.away)})`, n: ra?.fpi }, { v: rh?.fpi == null ? null : `${fmt(rh.fpi)} (#${rank(g.home)})`, n: rh?.fpi }, (x, y) => x > y)
    + row("Adj. offense", { v: fmt(ra?.ppg), n: ra?.ppg }, { v: fmt(rh?.ppg), n: rh?.ppg }, (x, y) => x > y)
    + row("Adj. defense", { v: fmt(ra?.papg), n: ra?.papg }, { v: fmt(rh?.papg), n: rh?.papg }, (x, y) => x < y);
  const box = Object.fromEntries((s.boxscore?.teams || []).map((t) => [t.team.id, Object.fromEntries((t.statistics || []).map((x) => [x.label, x.displayValue]))]));
  const labels = g.state === "pre" ? Object.keys(box[g.home.id] || {}) : GAME_STATS_SHOWN.filter((l) => box[g.home.id]?.[l] != null);
  if (labels.length) {
    rows += `<tr><th colspan="3" class="gd-sub">${g.state === "pre" ? "Season averages" : "This game"}</th></tr>`;
    rows += labels.map((l) => row(esc(l), { v: esc(box[g.away.id]?.[l]) }, { v: esc(box[g.home.id]?.[l]) })).join("");
  }
  const form = (s.lastFiveGames || []).map((t) => {
    const games = (t.events || []).map((e) => `<span class="gd-form ${e.gameResult === "W" ? "w" : e.gameResult === "L" ? "l" : ""}"
        title="${esc(`${e.gameResult} ${e.score} ${e.atVs} ${e.opponent?.displayName || ""}`)}">${esc(e.gameResult || "–")}</span>
        <span class="gd-form-opp">${esc(e.atVs === "@" ? "@" : "vs")} ${esc(e.opponent?.abbreviation || "")} ${esc(e.score || "")}</span>`).join("");
    return games ? `<div class="gd-form-row"><b>${esc(t.team?.abbreviation || "")}</b><div>${games}</div></div>` : "";
  }).join("");
  return `<div class="card"><h3>Matchup</h3>
    <div class="table-wrap"><table class="data gd-vs">
      <tr><th>${esc(g.away.abbr)}</th><th class="gd-mid"></th><th>${esc(g.home.abbr)}</th></tr>${rows}
    </table></div>
    ${form ? `<h4 class="gd-h4">Last five games</h4>${form}` : ""}
  </div>`;
}

function opinionCard(g, s) {
  const pr = s.predictor;
  const espnHome = pr?.homeTeam?.gameProjection != null ? parseFloat(pr.homeTeam.gameProjection) / 100 : null;
  const m = projections(g)[state.source];
  const sig = state.settings.sigma || state.model?.sigma?.[state.source] || 15.5;
  const modelHome = m == null ? null : normCdf(m / sig);
  if (espnHome == null && modelHome == null) return "";
  const bar = (label, p) => p == null ? "" : `<div class="gd-wp"><span>${label}</span>
      <div class="gd-wp-bar"><i style="width:${(100 * (1 - p)).toFixed(1)}%"></i></div>
      <span class="gd-wp-num">${esc(g.away.abbr)} ${pct(1 - p)} · ${esc(g.home.abbr)} ${pct(p)}</span></div>`;
  return `<div class="card"><h3>Win chance: a second opinion</h3>
    ${bar("ESPN's matchup predictor", espnHome)}${bar(`This model (${SOURCE_LABEL[state.source]})`, modelHome)}
    <p class="note">Chance to win the game outright, not to cover. When ESPN and the model disagree a lot, be careful with the pick.</p>
  </div>`;
}

function conditionsCard(g, s) {
  const gi = s.gameInfo || {}, w = gi.weather, v = gi.venue;
  const items = [];
  if (v) items.push(["Venue", `${v.fullName}${v.grass === true ? " · grass" : v.grass === false ? " · artificial turf" : ""}`]);
  items.push(["Site", g.neutral ? "Neutral site: no home-field advantage" : `${g.home.name} at home`]);
  if (w) {
    items.push(["Temperature", w.temperature != null ? `${w.temperature}°F` : "—"]);
    if (w.gust != null) items.push(["Wind gusts", `${w.gust} mph`]);
    if (w.precipitation != null) items.push(["Rain chance", `${w.precipitation}%`]);
  } else if (g.state === "pre") items.push(["Weather", "No forecast yet (or played indoors)"]);
  if (gi.attendance) items.push(["Attendance", gi.attendance.toLocaleString()]);
  return `<div class="card"><h3>Conditions</h3><dl class="gd-dl">${items.map(([k, val]) => `<dt>${esc(k)}</dt><dd>${esc(val)}</dd>`).join("")}</dl>
    ${w?.gust >= 20 ? `<p class="note">Strong wind tends to lower scoring and hurts passing teams most.</p>` : ""}</div>`;
}

function flowCard(g, s) {
  if (g.state === "pre") return "";
  const wp = (s.winprobability || []).map((p, i) => [i, p.homeWinPercentage]);
  const leaders = (s.leaders || []).map((t) => {
    const cats = (t.leaders || []).map((c) => c.leaders?.[0] ? `<tr><td class="l">${esc(c.displayName)}</td>
        <td class="l">${esc(c.leaders[0].athlete?.displayName || "")}</td><td class="l note">${esc(c.leaders[0].displayValue)}</td></tr>` : "").join("");
    return cats ? `<h4 class="gd-h4">${esc(t.team?.displayName || "")}</h4><div class="table-wrap"><table class="data">${cats}</table></div>` : "";
  }).join("");
  return `<div class="card gd-wide"><h3>${g.state === "in" ? "Live" : "How it played out"}</h3>
    ${wp.length > 1 ? `<p class="note">ESPN's win chance for ${esc(g.home.name)}, play by play.</p>
      ${lineChart(wp, { yMin: 0, yMax: 1, mid: 0.5, yFmt: (v) => pct(v), height: 160 })}` : ""}
    ${leaders}
  </div>`;
}

function forwardCard(g, log) {
  const L = log?.logged;
  if (!L) return `<div class="card"><h3>Forward test</h3><p class="note">This game isn't in the pick log${g.state === "pre" ? " yet. It's recorded the first time its line appears" : " (it may be outside the last three weeks)"}.</p></div>`;
  const res = { W: `<span class="badge win">Won</span>`, L: `<span class="badge loss">Lost</span>`, P: `<span class="badge pass">Push</span>` };
  const at = new Date(L.at).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
  return `<div class="card"><h3>Forward test</h3>
    <p>Recorded <b>${esc(at)}</b> at <b>${esc(lineTxt(g, L.line))}</b>${L.close != null ? `, ${g.state === "pre" ? "latest line" : "closed at"} ${esc(lineTxt(g, L.close))}` : ""}. These picks can't be changed after the fact.</p>
    <div class="table-wrap"><table class="data">
      <tr><th>Projection</th><th class="l">Pick</th><th>Edge</th><th>Line moved</th><th class="l">Result</th></tr>
      ${["anchored", "fpi", "blend", "points"].filter((k) => L.picks[k]).map((k) => {
        const p = L.picks[k], team = p.side === "home" ? g.home : g.away;
        // until the game is graded, show movement so far from the logged line to the latest one
        const clv = p.clv ?? (L.close != null ? (L.line - L.close) * (p.side === "home" ? 1 : -1) : null);
        return `<tr><td class="l">${esc(SOURCE_LABEL[k])}</td><td class="l"><b>${esc(team.abbr)} ${fmtLine(p.side === "home" ? L.line : -L.line)}</b></td>
          <td><span class="badge ${p.tier === "small" ? "pass" : p.tier}">${p.edge.toFixed(1)}</span></td>
          <td class="${clv > 0 ? "good" : clv < 0 ? "bad" : ""}">${clv == null ? "—" : (clv > 0 ? "+" : "") + clv}</td>
          <td class="l">${p.result ? res[p.result] : `<span class="note">Pending</span>`}</td></tr>`;
      }).join("")}
    </table></div></div>`;
}

const injuryNote = `<div class="card gd-warn"><h3>Not included: injuries</h3>
  <p>ESPN doesn't publish injury reports for college football, so the model doesn't know about them. Check team news before
  betting, especially at quarterback, which is the model's biggest blind spot.</p></div>`;

async function renderGameDetail(id) {
  const box = $("#game-detail");
  try {
    const [s, log] = await Promise.all([getJSON(`${ESPN}/summary?event=${id}`), gameLog ? Promise.resolve(gameLog) : loadGameLog()]);
    if ($("#tab-game").hidden || location.hash !== `#game/${id}`) return;  // user navigated away
    const g = state.games.find((x) => x.id === id) || gameFromSummary(s);
    if (g.line == null) {
      const pc = s.pickcenter?.[0];
      if (pc?.spread != null) Object.assign(g, { line: num(pc.spread), openLine: num(pc.pointSpread?.home?.open?.line), total: num(pc.overUnder) });
    }
    document.title = `${g.away.abbr} @ ${g.home.abbr} · Fourth & Value`;
    box.innerHTML = headerCard(g, s) + `<div class="gd-grid">${pickCard(g)}${lineCard(g, log[id])}${matchupCard(g, s)}${opinionCard(g, s)}${conditionsCard(g, s)}${forwardCard(g, log[id])}${flowCard(g, s)}${injuryNote}</div>`;
    clearTimeout(gameTimer);
    if (g.state === "in") gameTimer = setTimeout(() => renderGameDetail(id), 30e3);
  } catch (e) {
    box.innerHTML = `<div class="card error">Couldn't load this game from ESPN (${esc(e.message)}). Check your connection and try again.</div>`;
  }
}

async function showGame(id) {
  $("#game-detail").innerHTML = `<div class="card note">Loading game…</div>`;
  window.scrollTo(0, 0);
  try { await appReady; } catch { /* show what we can */ }
  renderGameDetail(id);
}

function leaveGame() {
  clearTimeout(gameTimer);
  document.title = "Fourth & Value";
}

// The page may have been opened straight at #game/<id> before this file loaded
if (location.hash.startsWith("#game/")) showGame(location.hash.slice(6));
