import datetime as dt
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

from model import cover_prob, live_cover_prob, load_ratings, project

DATA = Path(__file__).parent / "data"
RATINGS, HISTORY, BETS = DATA / "team_ratings.csv", DATA / "history.csv", DATA / "bets.csv"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
HIST_COLS = ["id", "date", "home", "away", "line", "proj_margin", "pick_side", "cover_prob", "final_margin", "covered"]
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
        line = None  # home-team spread, negative = home favored
        if c.get("odds"):
            d = c["odds"][0].get("details", "")
            if d.upper() == "EVEN":
                line = 0.0
            elif " " in d:
                abbr, num = d.rsplit(" ", 1)
                try:
                    line = float(num) if abbr == h["team"].get("abbreviation") else -float(num)
                except ValueError:
                    pass
        rows.append(dict(
            id=e["id"], home=h["team"]["location"], away=a["team"]["location"],
            home_score=int(h.get("score") or 0), away_score=int(a.get("score") or 0),
            status=c["status"]["type"]["shortDetail"], state=c["status"]["type"]["state"],
            neutral=c.get("neutralSite", False), line=line,
            period=c["status"].get("period", 0), clock=float(c["status"].get("clock") or 0)))
    return pd.DataFrame(rows)


def espn_events(**params):
    r = requests.get(ESPN, params={"groups": 80, "limit": 300, **params}, timeout=20)
    r.raise_for_status()
    return r.json().get("events", [])


def season_of(d):
    return d.year if d.month >= 7 else d.year - 1


@st.cache_data(ttl=3600)
def season_ratings(season, today):
    """Season-to-date points scored/allowed per game from completed games (week by week:
    ESPN's date-range queries currently fail, but week + season year works)."""
    tot, seen = {}, set()

    def done(ev):
        return ev["competitions"][0]["status"]["type"]["state"] == "post"

    def add(events):
        for ev in events:
            if ev["id"] in seen or not done(ev):
                continue
            seen.add(ev["id"])
            t = {x["homeAway"]: x for x in ev["competitions"][0]["competitors"]}
            for me, op in (("home", "away"), ("away", "home")):
                s = tot.setdefault(t[me]["team"]["location"], [0, 0, 0])
                s[0] += int(t[me].get("score") or 0)
                s[1] += int(t[op].get("score") or 0)
                s[2] += 1

    add(espn_events(dates=f"{season}08"))  # Week 0 games in August
    for w in range(1, 17):
        evs = espn_events(dates=season, seasontype=2, week=w)
        add(evs)
        if w > 1 and not any(done(e) for e in evs):
            break
    mx = max((v[2] for v in tot.values()), default=0)
    rows = [(n, a / g, b / g, g) for n, (a, b, g) in tot.items() if g >= max(1, (mx + 1) // 2)]
    return pd.DataFrame(rows, columns=["team", "ppg", "papg", "games"]).round(2)


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
if st.sidebar.button("Refresh now"):
    st.cache_data.clear()
auto = st.sidebar.checkbox("Auto-refresh every 30s", True)

ratings = load_ratings(RATINGS)
COLS = ["Game", "Status", "Score", "Home line", "Proj margin", "Edge (pts)", "Pick", "Pregame %", "Live cover %", "Note"]


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
               "Home line": line if pd.notna(line) else None}
        p = project(g.home, g.away, ratings, g.neutral, hfa)
        if p is not None and pd.notna(line):
            margin = p[0] - p[1]
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
                                cover_prob=round(pre, 4), final_margin=None, covered=None))
        else:
            missing = [t for t in (g.home, g.away) if t not in ratings.index]
            notes = ["Add to ratings: " + ", ".join(missing)] if missing else []
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
    st.write("Points scored (`ppg`) and allowed (`papg`) per game. Team names must match the Game column.")
    if st.button("⚡ Auto-fill from ESPN results"):
        try:
            with st.spinner("Fetching this season's results..."):
                fetched = season_ratings(season_of(day), dt.date.today().isoformat())
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
                st.session_state["rating_msg"] = f"Filled in {len(fetched)} teams from completed games this season."
                st.rerun()
    st.caption("Overwrites ratings for teams found in ESPN results and keeps any others. Season-to-date averages "
               "(including games vs FCS teams, not opponent-adjusted), so early-season numbers are noisy. "
               "Teams with far fewer games than the rest (mostly FCS opponents) are skipped.")
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
    st.dataframe(hist, hide_index=True)
