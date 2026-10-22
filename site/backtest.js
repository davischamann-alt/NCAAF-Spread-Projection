"use strict";
// "Run your own backtest": the walk-forward backtest from model.py and sources.py, in the browser.
// Uses the visitor's own CollegeFootballData key, which is saved only in their browser and sent
// only to CollegeFootballData. Results should match the Python backtest exactly.

const CFBD_API = "https://api.collegefootballdata.com";
const FPI_WEEKLY = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football";
const BOOKS = ["DraftKings", "ESPN Bet", "Bovada", "William Hill (New Jersey)", "consensus"];
const RIDGE = 2.0, START_WEEK = 3, FPI_MAX_AGE_DAYS = 10, FIRST_TRAIN_SEASON = 2023;
const CACHE_NAME = "cfb-edge-data-v1";

const cfbdKey = {
  get: () => store.get("cfbdKey", ""),
  set: (k) => store.set("cfbdKey", k.trim()),
  clear: () => { try { localStorage.removeItem("cfb.cfbdKey"); } catch { /* nothing saved */ } },
};

// ---------- Downloads (cached in the browser so each season is only fetched once) ----------

async function cachedJSON(url, { headers = {}, keep = true } = {}) {
  let cache = null;
  try { cache = await caches.open(CACHE_NAME); } catch { /* no Cache API (e.g. private mode) */ }
  if (cache && keep) {
    const hit = await cache.match(url);
    if (hit) return hit.json();
  }
  const r = await fetch(url, { headers });
  if (r.status === 401) throw new Error("CollegeFootballData didn't accept the API key. Check it and try again.");
  if (r.status === 429) throw new Error("CollegeFootballData's monthly limit for this key has been reached.");
  if (!r.ok) throw new Error(`${r.status} ${r.statusText} from ${new URL(url).hostname}`);
  if (cache && keep) { try { await cache.put(url, r.clone()); } catch { /* storage full: carry on */ } }
  return r.json();
}

let cfbdCalls = 0;
async function cfbd(path, params, finished) {
  const url = `${CFBD_API}${path}?${new URLSearchParams(params)}`;
  let cache = null;
  try { cache = await caches.open(CACHE_NAME); } catch { /* no cache */ }
  if (!(cache && finished && await cache.match(url))) cfbdCalls++;
  // A finished season never changes, so keep it; the current season is fetched fresh each run
  return cachedJSON(url, { headers: { Authorization: `Bearer ${cfbdKey.get()}` }, keep: finished });
}

/** Games, {id: [closing line, opening line]} and FBS team names for a regular season (cfbd_season in sources.py). */
async function cfbdSeason(season, finished) {
  const raw = await cfbd("/games", { seasonType: "regular", year: season }, finished);
  const games = raw.filter((g) => g.completed && g.homePoints != null).map((g) => ({
    id: String(g.id), week: g.week, start: g.startDate, home: g.homeTeam, away: g.awayTeam,
    homeId: String(g.homeId), awayId: String(g.awayId), homePts: g.homePoints, awayPts: g.awayPoints, neutral: !!g.neutralSite }));
  const fbs = new Set();
  for (const g of raw) for (const s of ["home", "away"]) if (g[`${s}Classification`] === "fbs") fbs.add(g[`${s}Team`]);
  const lines = {};
  for (const g of await cfbd("/lines", { seasonType: "regular", year: season }, finished)) {
    const books = {};
    for (const b of g.lines || []) if (b.spread != null) books[b.provider] = b;
    // prefer a book that also has the opening line
    const pick = BOOKS.map((p) => books[p]).find((b) => b && b.spreadOpen != null)
      || BOOKS.map((p) => books[p]).find(Boolean) || Object.values(books)[0];
    if (pick) lines[String(g.id)] = [pick.spread, pick.spreadOpen ?? null];
  }
  return { games, lines, fbs };
}

/** {week - 1: {team id: fpi}}: the newest ESPN FPI snapshot taken before each week's first game,
 *  if it's at most 10 days old (fpi_before_weeks in sources.py). */
async function fpiBeforeWeeks(season, games, finished) {
  const snaps = [];
  for (let w = 1; w <= 16; w++) {
    const j = await cachedJSON(`${FPI_WEEKLY}/seasons/${season}/types/2/weeks/${w}/powerindex?limit=200`, { keep: finished });
    const items = j.items || [];
    if (!items.length) continue;
    const vals = {};
    for (const it of items) {
      const id = it.team.$ref.match(/\/teams\/(\d+)/)[1];
      const v = (it.predictives || []).find((p) => p.name === "fpi")?.value;
      if (v != null) vals[id] = v;
    }
    snaps.push([Date.parse(items[0].lastUpdated), vals]);
  }
  const first = {};
  for (const g of games) { const t = Date.parse(g.start); if (!(g.week in first) || t < first[g.week]) first[g.week] = t; }
  const out = {};
  for (const [w, t] of Object.entries(first)) {
    const before = snaps.filter(([ts]) => ts < t);
    if (!before.length) continue;
    const [ts, vals] = before.reduce((a, b) => (b[0] > a[0] ? b : a));
    if (t - ts <= FPI_MAX_AGE_DAYS * 864e5) out[+w - 1] = vals;
  }
  return out;
}

// ---------- Math ----------

/** Solves A x = b for symmetric positive definite A (Cholesky). A is a flat n*n Float64Array. */
function solveSPD(A, b, n) {
  const L = new Float64Array(n * n);
  for (let i = 0; i < n; i++) {
    for (let j = 0; j <= i; j++) {
      let s = A[i * n + j];
      for (let k = 0; k < j; k++) s -= L[i * n + k] * L[j * n + k];
      L[i * n + j] = i === j ? Math.sqrt(s) : s / L[j * n + j];
    }
  }
  const y = new Float64Array(n);
  for (let i = 0; i < n; i++) { let s = b[i]; for (let k = 0; k < i; k++) s -= L[i * n + k] * y[k]; y[i] = s / L[i * n + i]; }
  const x = new Float64Array(n);
  for (let i = n - 1; i >= 0; i--) { let s = y[i]; for (let k = i + 1; k < n; k++) s -= L[k * n + i] * x[k]; x[i] = s / L[i * n + i]; }
  return x;
}

/** Opponent-adjusted ratings (fit_ratings in model.py): pts = avg + off[team] + def[opp] +/- hfa/2,
 *  ridge least squares with team terms shrunk toward average. Returns {team: {ppg, papg}}. */
function fitRatings(games) {
  const teams = [...new Set(games.flatMap((g) => [g.home, g.away]))].sort();
  const ix = Object.fromEntries(teams.map((t, i) => [t, i]));
  const n = teams.length, p = 2 * n + 2;
  const A = new Float64Array(p * p), b = new Float64Array(p);
  const add = (cols, vals, y) => {
    for (let i = 0; i < cols.length; i++) {
      b[cols[i]] += vals[i] * y;
      for (let j = 0; j < cols.length; j++) A[cols[i] * p + cols[j]] += vals[i] * vals[j];
    }
  };
  for (const g of games) {
    for (const [me, op, pts, side] of [[g.home, g.away, g.homePts, 0.5], [g.away, g.home, g.awayPts, -0.5]]) {
      const cols = [0, 1 + ix[me], 1 + n + ix[op]], vals = [1, 1, 1];
      if (!g.neutral) { cols.push(p - 1); vals.push(side); }
      add(cols, vals, pts);
    }
  }
  for (let i = 1; i < p - 1; i++) A[i * p + i] += RIDGE;
  const c = solveSPD(A, b, p);
  return Object.fromEntries(teams.map((t, i) => [t, { ppg: c[0] + c[1 + i], papg: c[0] + c[1 + n + i] }]));
}

/** Predicts each week from earlier games only (walk_forward in model.py). */
function walkForward(season, games, lines, fpiByWeek, fbs, hfa) {
  const pooled = games.map((g) => ({ ...g, home: fbs.has(g.home) ? g.home : "FCS", away: fbs.has(g.away) ? g.away : "FCS" }));
  const weeks = [...new Set(games.filter((g) => g.week >= START_WEEK).map((g) => g.week))].sort((a, b) => a - b);
  const rows = [];
  for (const w of weeks) {
    const r = fitRatings(pooled.filter((g) => g.week < w));
    const fpi = fpiByWeek[w - 1] || {};
    for (const g of games.filter((x) => x.week === w)) {
      const [line, openLine] = lines[g.id] || [null, null];
      if (!fbs.has(g.home) || !fbs.has(g.away) || line == null) continue;
      const h = r[g.home], a = r[g.away];
      if (!h || !a || !(g.homeId in fpi) || !(g.awayId in fpi)) continue;
      const bump = g.neutral ? 0 : hfa;
      const points = (h.ppg + a.papg) - (a.ppg + h.papg) + bump;
      const fpiM = fpi[g.homeId] - fpi[g.awayId] + bump;
      rows.push({ season, id: g.id, week: w, game: `${g.away} @ ${g.home}`, line, openLine,
        finalMargin: g.homePts - g.awayPts, points, fpi: fpiM, blend: (points + fpiM) / 2, anchored: null });
    }
  }
  return rows;
}

/** Ordinary least squares for the Market-anchored weights (fit_anchor in model.py). */
function fitAnchor(rows) {
  const d = rows.filter((r) => r.openLine != null);
  const A = new Float64Array(16), b = new Float64Array(4);
  for (const r of d) {
    const x = [1, -r.openLine, r.fpi, r.points];
    for (let i = 0; i < 4; i++) { b[i] += x[i] * r.finalMargin; for (let j = 0; j < 4; j++) A[i * 4 + j] += x[i] * x[j]; }
  }
  const w = solveSPD(A, b, 4);
  return { const: w[0], line: w[1], fpi: w[2], points: w[3] };
}

/** Each season's Market-anchored projection from weights fit on earlier selected seasons (add_anchored). */
function addAnchored(rows) {
  for (const s of [...new Set(rows.map((r) => r.season))].sort()) {
    const train = rows.filter((r) => r.season < s && r.season >= FIRST_TRAIN_SEASON);
    if (train.filter((r) => r.openLine != null).length < 200) continue;
    const w = fitAnchor(train);
    for (const r of rows.filter((x) => x.season === s))
      r.anchored = w.const - w.line * (r.openLine ?? r.line) + w.fpi * r.fpi + w.points * r.points;
  }
}

/** Record and accuracy for each source (score_backtest in model.py). */
function scoreBacktest(all, minEdge, against) {
  const lineOf = (r) => (against === "open" ? r.openLine : r.line);
  const res = all.filter((r) => lineOf(r) != null);
  const sources = [["Adjusted points", "points"], ["ESPN FPI", "fpi"], ["Blend", "blend"]];
  if (res.some((r) => r.anchored != null)) sources.push(["Market-anchored", "anchored"]);
  const rmse = (errs) => (errs.length ? Math.sqrt(errs.reduce((s, e) => s + e * e, 0) / errs.length) : null);
  const out = sources.map(([name, col]) => {
    let w = 0, l = 0, pu = 0, clvN = 0, clvSum = 0, moved = 0, movedOk = 0;
    for (const r of res) {
      if (r[col] == null) continue;
      const edge = r[col] + lineOf(r);
      if (Math.abs(edge) < minEdge) continue;
      const side = Math.sign(edge), ats = (r.finalMargin + lineOf(r)) * side;
      if (ats > 0) w++; else if (ats < 0) l++; else pu++;
      if (against === "open") {
        const clv = (r.openLine - r.line) * side;
        clvN++; clvSum += clv;
        if (clv !== 0) { moved++; if (clv > 0) movedOk++; }
      }
    }
    const errs = res.filter((r) => r[col] != null).map((r) => r[col] - r.finalMargin);
    return { name, picks: w + l, wins: w, losses: l, pushes: pu, hit_rate: w + l ? w / (w + l) : null,
      rmse_vs_result: rmse(errs), avg_clv: clvN ? clvSum / clvN : null, clv_beat_rate: moved ? movedOk / moved : null };
  });
  out.push({ name: `${against === "open" ? "Opening" : "Closing"} line (baseline)`,
    rmse_vs_result: rmse(res.map((r) => -lineOf(r) - r.finalMargin)) });
  return out;
}

/** The season in progress: college football seasons start in August (season_of in sources.py). */
function currentSeason() {
  const d = new Date();
  return d.getMonth() >= 6 ? d.getFullYear() : d.getFullYear() - 1;
}

async function runBacktest(seasons, hfa, progress) {
  cfbdCalls = 0;
  const current = currentSeason();
  const rows = [];
  for (const s of [...seasons].sort()) {
    const finished = s < current;
    progress(`${s}: downloading games and lines…`);
    const { games, lines, fbs } = await cfbdSeason(s, finished);
    progress(`${s}: downloading ESPN's weekly FPI…`);
    const fpi = await fpiBeforeWeeks(s, games, finished);
    progress(`${s}: replaying the season week by week…`);
    await new Promise((r) => setTimeout(r, 0));  // let the progress message paint
    rows.push(...walkForward(s, games, lines, fpi, fbs, hfa));
  }
  addAnchored(rows);
  return rows;
}

// ---------- Panel ----------

let btRows = null, btAgainst = "open", btEdge = 0;

function renderBacktestPanel() {
  const key = cfbdKey.get();
  $("#bt-key-row").hidden = !!key;
  $("#bt-ready").hidden = !key;
  if (key) $("#bt-key-status").textContent = `Key saved in this browser (ends in …${key.slice(-4)}).`;
  if (!btRows) return;
  const t = scoreBacktest(btRows, btEdge, btAgainst);
  const clv = btAgainst === "open";
  $("#bt-table").innerHTML = `<tr><th>Projection</th><th>Picks</th><th>Record</th><th>Hit rate</th><th>Typical miss</th>${clv ? "<th>Line moved our way</th>" : ""}</tr>` +
    t.map((x) => /baseline/.test(x.name)
      ? `<tr><td class="l note">${esc(x.name.replace(" (baseline)", ""))} itself</td><td></td><td></td><td></td><td>${x.rmse_vs_result?.toFixed(1) ?? "—"}</td>${clv ? "<td></td>" : ""}</tr>`
      : `<tr><td class="l">${esc(x.name)}</td><td>${x.picks}</td><td>${x.wins}-${x.losses}</td>
        <td class="${x.hit_rate >= BREAKEVEN ? "good" : "bad"}">${pct(x.hit_rate, 1)}</td><td>${x.rmse_vs_result?.toFixed(1) ?? "—"}</td>
        ${clv ? `<td>${pct(x.clv_beat_rate)}</td>` : ""}</tr>`).join("");
  const seasons = [...new Set(btRows.map((r) => r.season))];
  const noAnchor = !btRows.some((r) => r.anchored != null);
  $("#bt-summary").textContent = `${btRows.length} games across ${seasons.length} season${seasons.length > 1 ? "s" : ""} (${seasons.join(", ")}).` +
    (noAnchor ? " Market-anchored needs an earlier season from 2023 on to learn from, so it isn't shown." : "");
  $("#bt-results").hidden = false;
}

function bindBacktestPanel() {
  const cur = currentSeason();
  $("#bt-seasons").innerHTML = Array.from({ length: cur - 2020 }, (_, i) => cur - i).map((y) =>
    `<button type="button" data-v="${y}" class="${y >= 2023 ? "on" : ""}">${y}</button>`).join("");
  $$("#bt-seasons button").forEach((b) => b.addEventListener("click", () => b.classList.toggle("on")));
  $("#bt-key-form").addEventListener("submit", (e) => {
    e.preventDefault();
    const v = $("#bt-key").value.trim();
    if (!v) return;
    cfbdKey.set(v); $("#bt-key").value = ""; renderBacktestPanel();
  });
  $("#bt-forget").addEventListener("click", () => { cfbdKey.clear(); btRows = null; $("#bt-results").hidden = true; renderBacktestPanel(); });
  $("#bt-run").addEventListener("click", async () => {
    const seasons = $$("#bt-seasons button.on").map((b) => +b.dataset.v);
    const msg = $("#bt-progress");
    if (!seasons.length) { msg.textContent = "Pick at least one season."; return; }
    $("#bt-run").disabled = true;
    msg.classList.remove("error");
    try {
      btRows = await runBacktest(seasons, hfa(), (m) => (msg.textContent = m));
      msg.textContent = `Done. Used ${cfbdCalls} CollegeFootballData call${cfbdCalls === 1 ? "" : "s"} (the free plan allows 1,000 a month; past seasons are saved in this browser, so running them again is free).`;
      renderBacktestPanel();
    } catch (e) {
      msg.textContent = e.message; msg.classList.add("error");
    } finally { $("#bt-run").disabled = false; }
  });
  for (const [id, set] of [["#bt-against", (v) => (btAgainst = v)], ["#bt-edge", (v) => (btEdge = +v)]]) {
    $$(`${id} button`).forEach((b) => b.addEventListener("click", () => {
      $$(`${id} button`).forEach((x) => x.classList.toggle("on", x === b)); set(b.dataset.v); renderBacktestPanel();
    }));
  }
  renderBacktestPanel();
}

bindBacktestPanel();
