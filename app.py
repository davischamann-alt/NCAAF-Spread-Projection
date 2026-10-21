import datetime as dt
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from model import (add_anchored, anchored_margin, cover_prob, fit_anchor, fit_ratings, fpi_margin, live_cover_prob,
                   load_ratings, pool_fcs, project, score_backtest, walk_forward)

DATA = Path(__file__).parent / "data"
RATINGS, HISTORY, BETS = DATA / "team_ratings.csv", DATA / "history.csv", DATA / "bets.csv"
CLOSING = DATA / "closing_lines.csv"
ANCHOR = DATA / "anchor_weights.json"
CFBD_DIR = DATA / "cfbd"
CFBD = "https://api.collegefootballdata.com"
# sportsbooks to take lines from, in order of preference (CFBD's provider names)
BOOKS = ["DraftKings", "ESPN Bet", "Bovada", "William Hill (New Jersey)", "consensus"]
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
FPI = "https://site.web.api.espn.com/apis/fitt/v3/sports/football/college-football/powerindex"
FPI_WEEKLY = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"
HIST_COLS = ["id", "date", "home", "away", "line", "proj_margin", "pick_side", "cover_prob", "final_margin", "covered", "source"]
BET_COLS = ["date", "game", "side", "line", "odds", "stake", "result"]

st.set_page_config(page_title="CFB Edge Dashboard", page_icon="🏈", layout="wide")


def read(path, cols, **kw):
    df = pd.read_csv(path, **kw) if path.exists() else pd.DataFrame(columns=cols)
    return df.astype({c: object for c in ("covered", "result") if c in df.columns})


@st.cache_data(ttl=20)
def scoreboard(date_str):
    r = requests.get(ESPN, params={"dates": date_str, "groups": 80, "limit": 200}, timeout=10)
    r.raise_for_status()
    rows = []
    for e in r.json().get("events", []):
        c = e["competitions"][0]
        t = {x["homeAway"]: x for x in c["competitors"]}
        h, a = t["home"], t["away"]
        line, open_line, total = parse_odds(c.get("odds") or [], h["team"].get("abbreviation"))
        rows.append(dict(
            id=e["id"], home=h["team"]["location"], away=a["team"]["location"],
            home_score=int(h.get("score") or 0), away_score=int(a.get("score") or 0),
            status=c["status"]["type"]["shortDetail"], state=c["status"]["type"]["state"],
            neutral=c.get("neutralSite", False), line=line, open_line=open_line, total=total,
            period=c["status"].get("period", 0), clock=float(c["status"].get("clock") or 0)))
    return pd.DataFrame(rows)


def num(x):
    try:
        return 0.0 if str(x).upper() in ("PK", "EVEN") else float(str(x).lstrip("ou"))
    except ValueError:
        return None


def parse_odds(odds, home_abbr):
    """(home line, home opening line, total). Prefers the numeric fields and falls back
    to parsing the "ABBR -7.5" details text."""
    if not odds:
        return None, None, None
    o = odds[0]
    line = num(o["spread"]) if o.get("spread") is not None else None
    if line is None:
        d = o.get("details", "")
        if d.upper() == "EVEN":
            line = 0.0
        elif " " in d and (v := num(d.rsplit(" ", 1)[1])) is not None:
            line = v if d.rsplit(" ", 1)[0] == home_abbr else -v
    open_line = num(o.get("pointSpread", {}).get("home", {}).get("open", {}).get("line", ""))
    return line, open_line, num(o["overUnder"]) if o.get("overUnder") is not None else None


def espn_events(**params):
    r = requests.get(ESPN, params={"groups": 80, "limit": 300, **params}, timeout=20)
    r.raise_for_status()
    return r.json().get("events", [])


def season_of(d):
    return d.year if d.month >= 7 else d.year - 1


def season_games(season):
    """This season's completed games, fetched week by week: ESPN's date-range queries currently
    fail, but week + season year works. August (Week 0) games get week 0."""
    rows, seen = [], set()

    def done(ev):
        return ev["competitions"][0]["status"]["type"]["state"] == "post"

    def add(events, week):
        for ev in events:
            if ev["id"] in seen or not done(ev):
                continue
            seen.add(ev["id"])
            c = ev["competitions"][0]
            t = {x["homeAway"]: x for x in c["competitors"]}
            rows.append(dict(id=ev["id"], week=week, start=ev["date"], home=t["home"]["team"]["location"],
                             away=t["away"]["team"]["location"], home_id=t["home"]["team"]["id"],
                             away_id=t["away"]["team"]["id"], home_pts=int(t["home"].get("score") or 0),
                             away_pts=int(t["away"].get("score") or 0), neutral=c.get("neutralSite", False)))

    add(espn_events(dates=f"{season}08"), 0)
    for w in range(1, 17):
        evs = espn_events(dates=season, seasontype=2, week=w)
        add(evs, w)
        if w > 1 and not any(done(e) for e in evs):
            break
    return pd.DataFrame(rows, columns=["id", "week", "start", "home", "away", "home_id", "away_id",
                                       "home_pts", "away_pts", "neutral"])


def team_names(games):
    return dict(zip(games.home_id, games.home)) | dict(zip(games.away_id, games.away))


@st.cache_data(ttl=3600)
def season_ratings(season, today):
    """Opponent-adjusted points scored/allowed per game from this season's completed games,
    plus ESPN FPI. Returns (ratings, fitted home-field edge, FPI error or None)."""
    games = season_games(season)
    if games.empty:
        return pd.DataFrame(columns=["team", "ppg", "papg", "games", "fpi"]), None, None
    names = team_names(games)
    try:
        fpi, fpi_err = espn_fpi(season), None
    except Exception as ex:
        fpi, fpi_err = {}, str(ex)
    fbs = {names[i] for i in fpi if i in names} or None  # FPI covers exactly the FBS teams
    fit = list(games[["home", "away", "home_pts", "away_pts", "neutral"]].itertuples(index=False, name=None))
    df, fitted_hfa = fit_ratings(pool_fcs(fit, fbs))
    df = df[df["team"] != "FCS"]
    df["fpi"] = df["team"].map({names[i]: v for i, v in fpi.items() if i in names})
    return df.round(2), fitted_hfa, fpi_err


def espn_fpi(season):
    """ESPN Football Power Index by ESPN team id: expected margin vs an average FBS team on a
    neutral field. Built from efficiency stats plus preseason priors, so it's steadier early on."""
    r = requests.get(FPI, params={"season": season, "limit": 200}, timeout=20)
    r.raise_for_status()
    out = {}
    for t in r.json().get("teams", []):
        cat = next((c for c in t.get("categories", []) if c.get("name") == "fpi"), None)
        if cat and cat.get("values"):
            out[t["team"]["id"]] = cat["values"][0]
    return out


def weekly_fpi(season, week):
    """(time taken, {team id: fpi}) for ESPN's FPI snapshot for `week`, or None if there isn't one."""
    url = f"{FPI_WEEKLY}/seasons/{season}/types/2/weeks/{week}/powerindex"
    r = requests.get(url, params={"limit": 200}, timeout=30)
    r.raise_for_status()
    items = r.json().get("items", [])
    if not items:
        return None
    out = {}
    for it in items:
        tid = re.search(r"/teams/(\d+)", it["team"]["$ref"]).group(1)
        v = next((p["value"] for p in it.get("predictives", []) if p["name"] == "fpi"), None)
        if v is not None:
            out[tid] = v
    return pd.Timestamp(items[0]["lastUpdated"]), out


def fpi_before_weeks(season, games, max_age_days=10):
    """{week - 1: fpi} as walk_forward expects: for each week, the newest snapshot taken before
    that week's first game. Picking by timestamp matters for past seasons, where ESPN has
    overwritten some weekly snapshots months later. Weeks whose newest earlier snapshot is
    stale get no FPI, so their games are left out rather than graded with old ratings."""
    snaps = [x for w in range(1, 17) if (x := weekly_fpi(season, w))]
    out = {}
    for w, first in games.groupby("week")["start"].min().items():
        first = pd.Timestamp(first)
        before = [x for x in snaps if x[0] < first]
        if before:
            ts, vals = max(before, key=lambda x: x[0])
            if first - ts <= pd.Timedelta(days=max_age_days):
                out[w - 1] = vals
    return out, (max(snaps, key=lambda x: x[0])[1] if snaps else {})


def pregame_line(gid):
    """(home closing line, home opening line, total) from ESPN's game summary, which keeps the
    pregame lines after the game."""
    r = requests.get(SUMMARY, params={"event": gid}, timeout=20)
    r.raise_for_status()
    pc = r.json().get("pickcenter") or []
    if not pc or pc[0].get("spread") is None:
        return gid, None, None, None
    o = pc[0]
    open_line = num(o.get("pointSpread", {}).get("home", {}).get("open", {}).get("line", ""))
    return gid, num(o["spread"]), open_line, num(o["overUnder"]) if o.get("overUnder") is not None else None


def closing_lines(ids):
    """{id: (closing line, opening line)} for finished games, cached in data/closing_lines.csv so
    each game is fetched once. A cache from before opening lines were saved is refetched."""
    cols = ["id", "line", "open", "total"]
    have = pd.read_csv(CLOSING, dtype={"id": str}) if CLOSING.exists() else pd.DataFrame(columns=cols)
    if "open" not in have.columns:
        have = pd.DataFrame(columns=cols)
    todo = sorted(set(ids) - set(have["id"]))
    if todo:
        with ThreadPoolExecutor(8) as pool:
            got = pd.DataFrame(pool.map(pregame_line, todo), columns=cols)
        have = pd.concat([have, got], ignore_index=True)
        have.to_csv(CLOSING, index=False)
    return dict(zip(have["id"], zip(have["line"], have["open"])))


@st.cache_data(ttl=3600)
def season_backtest(season, hfa, today):
    """Walk-forward results for every FBS game in a season (see model.walk_forward). The current
    season comes from ESPN; past seasons' games and lines come from CollegeFootballData."""
    if season == season_of(dt.date.fromisoformat(today)):
        games = season_games(season)
        fpi_by_week, latest = fpi_before_weeks(season, games)
        names = team_names(games)
        fbs = {names[i] for i in latest if i in names}  # FPI covers exactly the FBS teams
        both = games[games.home.isin(fbs) & games.away.isin(fbs) & (games.week >= 3)]
        lines = closing_lines(both["id"])
    else:
        games, lines, fbs = cfbd_season(season)
        fpi_by_week = fpi_before_weeks(season, games)[0]
    res = walk_forward(games, lines, fpi_by_week, fbs, hfa)
    return res.assign(season=season)


def cfbd_key():
    try:
        key = st.secrets.get("CFBD_API_KEY", "")
    except Exception:  # no secrets file
        key = ""
    return key or os.environ.get("CFBD_API_KEY", "")


def cfbd(path, **params):
    """GET from CollegeFootballData, saved under data/cfbd/ so a finished season is only
    downloaded once (the free plan allows 1,000 calls a month)."""
    f = CFBD_DIR / f"{path.strip('/')}_{'_'.join(f'{k}{v}' for k, v in sorted(params.items()))}.json"
    if f.exists():
        return json.loads(f.read_text())
    r = requests.get(CFBD + path, params=params, headers={"Authorization": f"Bearer {cfbd_key()}"}, timeout=60)
    if r.status_code == 401:
        raise RuntimeError("CollegeFootballData rejected the API key. Check .streamlit/secrets.toml.")
    r.raise_for_status()
    CFBD_DIR.mkdir(exist_ok=True)
    f.write_text(r.text)
    return r.json()


def cfbd_season(season):
    """(games, {id: (closing line, opening line)}, FBS team names) for a finished regular season.
    CFBD uses ESPN's team and game ids, so ESPN's FPI lines up by id."""
    raw = cfbd("/games", year=season, seasonType="regular")
    games = pd.DataFrame([dict(id=str(g["id"]), week=g["week"], start=g["startDate"], home=g["homeTeam"],
                               away=g["awayTeam"], home_id=str(g["homeId"]), away_id=str(g["awayId"]),
                               home_pts=g["homePoints"], away_pts=g["awayPoints"], neutral=g["neutralSite"])
                          for g in raw if g.get("completed") and g.get("homePoints") is not None])
    fbs = {g[f"{s}Team"] for g in raw for s in ("home", "away") if g.get(f"{s}Classification") == "fbs"}
    lines = {}
    for g in cfbd("/lines", year=season, seasonType="regular"):
        books = {b["provider"]: b for b in g.get("lines", []) if b.get("spread") is not None}
        # prefer a book that also has the opening line
        pick = next((books[p] for p in BOOKS if p in books and books[p].get("spreadOpen") is not None),
                    next((books[p] for p in BOOKS if p in books), next(iter(books.values()), None)))
        if pick:
            lines[str(g["id"])] = (pick["spread"], pick.get("spreadOpen"))
    return games, lines, fbs


def grade(hist, games):
    if hist.empty or games.empty:
        return hist
    final = games[games.state == "post"].set_index("id")
    for i, h in hist.iterrows():
        if h["id"] in final.index and pd.isna(h["covered"]):
            f = final.loc[h["id"]]
            fm = int(f.home_score - f.away_score)
            x = (fm + h["line"]) * (1 if h["pick_side"] == "home" else -1)
            hist.loc[i, "final_margin"] = fm
            hist.loc[i, "covered"] = "Y" if x > 0 else "N" if x < 0 else "Push"
    return hist


st.title("🏈 College Football Edge Dashboard")
day = st.sidebar.date_input("Date", dt.date.today())
sigma = st.sidebar.slider("Margin std dev (pts)", 10.0, 20.0, 14.0, 0.5)
hfa = st.sidebar.slider("Home-field advantage (pts)", 0.0, 5.0, 2.5, 0.5)
SOURCES = ["Blend (points + FPI)", "Adjusted points", "ESPN FPI", "Market-anchored"]
source = st.sidebar.radio("Projection source", SOURCES,
                          help="Blend averages points and FPI when both are available and falls back to whichever one "
                               "is. Market-anchored starts from the opening line and shifts it by FPI and points, with "
                               "weights learned in the season backtest.")
if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
auto = st.sidebar.checkbox("Auto-refresh every 30s", True)

ratings = load_ratings(RATINGS)
anchor = json.loads(ANCHOR.read_text()) if ANCHOR.exists() else None
COLS = ["Game", "Status", "Score", "Home line", "Open", "Total", "Proj margin", "Edge (pts)", "Pick", "Pregame %", "Live cover %", "Note"]


@st.cache_resource
def line_store():
    f = DATA / "lines.csv"
    return dict(pd.read_csv(f, dtype={"id": str}).values) if f.exists() else {}


def get_games(warn=True):
    try:
        return scoreboard(day.strftime("%Y%m%d"))
    except Exception as ex:
        if warn:
            st.warning(f"Couldn't load scores: {ex}")
        return pd.DataFrame()


def sync_history(games):
    h = grade(read(HISTORY, HIST_COLS, dtype={"id": str}), games)
    if not h.empty:
        h.to_csv(HISTORY, index=False)
    return h


def proj_margin(g, line):
    p = project(g.home, g.away, ratings, g.neutral, hfa)
    pts = None if p is None else p[0] - p[1]
    fpi = fpi_margin(g.home, g.away, ratings, g.neutral, hfa)
    if source == "Adjusted points":
        return pts
    if source == "ESPN FPI":
        return fpi
    if source == "Market-anchored":
        # trained on opening lines, so anchor on the opener and fall back to the pregame line
        base = g.open_line if pd.notna(g.open_line) else line
        if anchor is None or pts is None or fpi is None or pd.isna(base):
            return None
        return anchored_margin(anchor["weights"], base, fpi, pts)
    both = [m for m in (pts, fpi) if m is not None]
    return sum(both) / len(both) if both else None


def secs_left(g):
    if g.state == "pre":
        return 3600
    if g.state == "post":
        return 0
    return 120 if g.period > 4 else (4 - g.period) * 900 + g.clock


hist = sync_history(get_games(warn=False))
t1, t2, t3, t4 = st.tabs(["Today's games", "Team ratings", "Bet tracker", "Backtest"])


@st.fragment(run_every="30s" if auto else None)
def live_board():
    games, store = get_games(), line_store()
    h = sync_history(games)
    table, log = [], []
    for g in games.itertuples():
        if g.state == "pre" and pd.notna(g.line) and store.get(g.id) != g.line:
            store[g.id] = g.line  # remember the pregame line
            pd.DataFrame(list(store.items()), columns=["id", "line"]).to_csv(DATA / "lines.csv", index=False)
        line = g.line if g.state == "pre" else store.get(g.id, g.line)
        row = {"Game": f"{g.away} @ {g.home}", "Status": g.status, "Score": f"{g.away_score}-{g.home_score}",
               "Home line": line if pd.notna(line) else None,
               "Open": g.open_line if pd.notna(g.open_line) else None, "Total": g.total if pd.notna(g.total) else None}
        margin = proj_margin(g, line)
        if margin is not None and pd.notna(line):
            pre = cover_prob(margin, line, sigma)
            live = live_cover_prob(g.home_score - g.away_score, margin, line, secs_left(g), sigma)
            home_pick = pre >= 0.5
            pre, live = (pre, live) if home_pick else (1 - pre, 1 - live)
            row.update({"Home line": line, "Proj margin": margin, "Edge (pts)": abs(margin + line),
                        "Pick": f"{g.home} {line:+g}" if home_pick else f"{g.away} {-line:+g}",
                        "Pregame %": 100 * pre, "Live cover %": 100 * live})
            if g.state == "pre":
                log.append(dict(id=g.id, date=str(day), home=g.home, away=g.away, line=line,
                                proj_margin=round(margin, 2), pick_side="home" if home_pick else "away",
                                cover_prob=round(pre, 4), final_margin=None, covered=None, source=source))
        else:
            missing = [t for t in (g.home, g.away) if t not in ratings.index]
            notes = ["Add to ratings: " + ", ".join(missing)] if missing else []
            if not missing and source in ("ESPN FPI", "Market-anchored"):
                notes.append("No FPI for a team (try Auto-fill or another source)")
            if source == "Market-anchored" and anchor is None:
                notes.append("Run the season backtest with past seasons to train Market-anchored")
            if pd.isna(line):
                notes.append("No line yet" if g.state == "pre" else "No pregame line saved")
            row["Note"] = " · ".join(notes)
        table.append(row)
    if not table:
        st.info("No games found for this date.")
        return
    st.dataframe(pd.DataFrame(table, columns=COLS), hide_index=True, column_config={
        "Pregame %": st.column_config.NumberColumn(format="%.0f%%"),
        "Live cover %": st.column_config.ProgressColumn(min_value=0, max_value=100, format="%.0f%%"),
        "Proj margin": st.column_config.NumberColumn(format="%+.1f"),
        "Open": st.column_config.NumberColumn(format="%+g", help="Opening home line; compare with Home line for movement"),
        "Edge (pts)": st.column_config.NumberColumn(format="%.1f")})
    st.caption(f"Updated {dt.datetime.now():%I:%M:%S %p}" + (" · auto-refreshing every 30s" if auto else ""))
    st.caption("Live % = chance the pregame pick covers the pregame line, given the score and clock. "
               "Picks need both teams in team_ratings.csv and a line. Open the app before kickoff so the pregame line is saved.")
    if log and st.button("📌 Log these pregame picks to history"):
        new = [x for x in log if x["id"] not in set(h["id"])]
        pd.concat([h, pd.DataFrame(new, columns=HIST_COLS)]).to_csv(HISTORY, index=False)
        st.success(f"Logged {len(new)} picks. They're graded automatically once games go final.")


with t1:
    live_board()


with t2:
    if m := st.session_state.pop("rating_msg", None):
        st.success(m)
    rv = st.session_state.setdefault("rv", 0)
    st.write("Opponent-adjusted points scored (`ppg`) and allowed (`papg`) per game, plus ESPN's `fpi`. "
             "Team names must match the Game column.")
    if st.button("⚡ Auto-fill from ESPN results"):
        try:
            with st.spinner("Fetching this season's results and FPI..."):
                fetched, fitted_hfa, fpi_err = season_ratings(season_of(day), dt.date.today().isoformat())
        except Exception as ex:
            st.error(f"Couldn't fetch results: {ex}")
        else:
            if fetched.empty:
                st.warning("No completed games found yet.")
            else:
                cur = ratings.reset_index()
                keep = cur[~cur["team"].isin(fetched["team"])]
                pd.concat([fetched, keep]).sort_values("team").to_csv(RATINGS, index=False)
                st.session_state["rv"] = rv + 1
                msg = f"Filled in {len(fetched)} teams from completed games this season."
                if fitted_hfa is not None:
                    msg += (f" Home teams scored {fitted_hfa:+.1f} pts vs expectation this season (noisy, since early "
                            "schedules are home-heavy; the long-run college average is about 2.5-3).")
                msg += f" FPI unavailable: {fpi_err}" if fpi_err else f" FPI found for {fetched['fpi'].notna().sum()} teams."
                st.session_state["rating_msg"] = msg
                st.rerun()
    st.caption("Overwrites ratings for teams found in ESPN results and keeps any others. Points are adjusted for "
               "opponent strength (scoring 40 on a top defense counts for more than 40 on a weak one) and shrunk toward "
               "average, which matters most early in the season. Teams with far fewer games than the rest (mostly FCS "
               "opponents) are left out of the table but still count in the adjustment.")
    edited = st.data_editor(ratings.reset_index(), num_rows="dynamic", hide_index=True, key=f"ratings_{rv}")
    if st.button("Save ratings"):
        edited.dropna(subset=["team"]).to_csv(RATINGS, index=False)
        st.session_state["rv"] = rv + 1
        st.rerun()

with t3:
    bets = read(BETS, BET_COLS)
    ed = st.data_editor(bets, num_rows="dynamic", hide_index=True, key=f"bets_{st.session_state.get('bv', 0)}", column_config={
        "result": st.column_config.SelectboxColumn(options=["W", "L", "Push"])})
    if st.button("Save bets"):
        ed.to_csv(BETS, index=False)
        st.session_state["bv"] = st.session_state.get("bv", 0) + 1
        st.rerun()
    d = ed.dropna(subset=["stake", "result"]).copy()
    if not d.empty:
        d["stake"] = pd.to_numeric(d["stake"], errors="coerce").fillna(0)
        d["odds"] = pd.to_numeric(d["odds"], errors="coerce").fillna(-110)

        def profit(r):
            if r.result == "W":
                return r.stake * (100 / abs(r.odds) if r.odds < 0 else r.odds / 100)
            return -r.stake if r.result == "L" else 0.0

        d["profit"] = d.apply(profit, axis=1)
        c1, c2, c3 = st.columns(3)
        c1.metric("Bets graded", len(d))
        c2.metric("Net profit", f"{d.profit.sum():+.2f}")
        c3.metric("ROI", f"{100 * d.profit.sum() / max(d.stake.sum(), 1e-9):+.1f}%")

with t4:
    h = hist[hist["covered"].isin(["Y", "N"])].copy()
    if h.empty:
        st.info("Log picks, then come back after games finish. Results fill in automatically.")
    else:
        h["bucket"] = pd.cut(h["cover_prob"].astype(float), [0.5, 0.55, 0.6, 0.65, 0.7, 1.01], right=False,
                             labels=["50-54%", "55-59%", "60-64%", "65-69%", "70%+"])
        out = h.groupby("bucket", observed=True).agg(picks=("covered", "size"), hit_rate=("covered", lambda s: (s == "Y").mean()))
        st.metric("Overall ATS hit rate", f"{100 * (h.covered == 'Y').mean():.1f}%", f"{len(h)} picks")
        st.dataframe(out, column_config={"hit_rate": st.column_config.NumberColumn(format="percent")})
        if "source" in h.columns and h["source"].notna().any():
            st.write("By projection source")
            by_src = h.groupby(h["source"].fillna("Points (before sources)")).agg(
                picks=("covered", "size"), hit_rate=("covered", lambda s: (s == "Y").mean()))
            st.dataframe(by_src, column_config={"hit_rate": st.column_config.NumberColumn(format="percent")})
    st.dataframe(hist, hide_index=True)

    st.divider()
    st.subheader("Season backtest (walk-forward)")
    st.caption("Replays each season from week 3: each week's FBS games are predicted using only earlier results "
               "(points ratings refit on prior games, FPI from the newest snapshot taken before the week started) and "
               "graded against the opening or closing line. The current season uses ESPN; past seasons use "
               "CollegeFootballData. Everything is downloaded once and cached in data/. "
               "At -110 odds you need 52.4% to break even.")
    cur = season_of(dt.date.today())
    seasons = st.multiselect("Seasons", list(range(cur, 2020, -1)), [cur],
                             help="Past seasons need a free CollegeFootballData key in .streamlit/secrets.toml. "
                                  "2021 and 2022 only have a few usable weeks because ESPN overwrote most of "
                                  "their weekly FPI snapshots.")
    past = [y for y in seasons if y != cur]
    if past and not cfbd_key():
        st.warning("Past seasons need a free API key from collegefootballdata.com/key. Paste it into "
                   "`.streamlit/secrets.toml` as `CFBD_API_KEY = \"your-key\"`, then click **Refresh now**.")
    if st.button("▶ Run season backtest", disabled=not seasons or bool(past and not cfbd_key())):
        try:
            with st.spinner("Fetching games, lines and weekly FPI (first run takes a minute per season)..."):
                res = add_anchored(pd.concat([season_backtest(y, hfa, dt.date.today().isoformat())
                                              for y in sorted(seasons)], ignore_index=True))
                st.session_state["bt"] = res
                done = sorted(y for y in seasons if 2023 <= y < cur)
                if done:  # weights for the live board, from every finished season run here
                    w = fit_anchor(res[res["season"].isin(done)])
                    ANCHOR.write_text(json.dumps({"weights": w, "seasons": done, "hfa": hfa}))
                    anchor = json.loads(ANCHOR.read_text())
        except Exception as ex:
            st.error(f"Couldn't run backtest: {ex}")
    res = st.session_state.get("bt")
    if res is not None and not res.empty:
        c1, c2 = st.columns(2)
        against = c1.radio("Grade against", ["open", "close"], horizontal=True,
                           format_func=lambda x: {"open": "Opening line", "close": "Closing line"}[x],
                           help="Opening: picks made when lines are first posted, the market's weakest point. "
                                "Closing: the final line at kickoff, the market's strongest.")
        min_edge = c2.slider("Only bet when edge is at least (pts)", 0.0, 10.0, 0.0, 0.5)
        pct = st.column_config.NumberColumn(format="percent")
        st.dataframe(score_backtest(res, min_edge, against), column_config={
            "hit_rate": pct, "mae_vs_result": st.column_config.NumberColumn("avg miss vs result", format="%.1f"),
            "rmse_vs_result": st.column_config.NumberColumn("RMSE vs result", format="%.1f",
                                                            help="Use this as the margin std dev for that source"),
            "mae_vs_line": st.column_config.NumberColumn("avg gap to line", format="%.1f"),
            "avg_clv": st.column_config.NumberColumn("avg CLV (pts)", format="%+.2f",
                                                     help="Average points the line moved toward the pick by kickoff"),
            "clv_beat_rate": st.column_config.NumberColumn("line moved our way", format="percent",
                                                           help="Share of picks whose line moved toward the pick, among lines that moved")})
        if against == "open":
            st.caption("CLV (closing line value) = how far the line moved toward each pick between open and kickoff. "
                       "Beating the close consistently is the standard sign of a real edge, and it shows up in far "
                       "fewer games than win rate does. Lines that didn't move are left out of the 'moved our way' rate.")
        by = "season" if res["season"].nunique() > 1 else "week"
        names = score_backtest(res, min_edge, against).index[:-1]
        weekly = res.groupby(by).apply(lambda d: score_backtest(d, min_edge, against)["hit_rate"].reindex(names),
                                       include_groups=False)
        st.write(f"Hit rate by {by}")
        st.dataframe(weekly, column_config={c: pct for c in weekly.columns})
        st.caption(f"{len(res)} games across {res['season'].nunique()} season(s). "
                   "The line (baseline) row shows how close the line itself came to final margins, for comparison.")
        if anchor:
            w = anchor["weights"]
            st.caption(f"Market-anchored weights (learned from {', '.join(map(str, anchor['seasons']))}): "
                       f"{w['line']:.2f} x opening line + {w['fpi']:.2f} x FPI + {w['points']:.2f} x adjusted points "
                       f"{w['const']:+.2f}. In the table above, each season is predicted with weights from earlier "
                       "selected seasons only (2023 on), so include earlier seasons to see it.")
        with st.expander("Game-by-game"):
            st.dataframe(res, hide_index=True)
    elif res is not None:
        st.info("Not enough completed games with lines yet (the backtest starts at week 3).")
