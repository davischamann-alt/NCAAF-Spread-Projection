import datetime as dt
import json

import pandas as pd
import streamlit as st

import sources
from model import (add_anchored, anchored_margin, cover_prob, fit_anchor, fpi_margin, live_cover_prob, load_ratings,
                   project, score_backtest)
from sources import ANCHOR, DATA, RATINGS, cfbd_key, season_of

HISTORY, BETS = DATA / "history.csv", DATA / "bets.csv"

HIST_COLS = ["id", "date", "home", "away", "line", "proj_margin", "pick_side", "cover_prob", "final_margin", "covered", "source"]
BET_COLS = ["date", "game", "side", "line", "odds", "stake", "result"]

st.set_page_config(page_title="CFB Edge Dashboard", page_icon="🏈", layout="wide")


def read(path, cols, **kw):
    df = pd.read_csv(path, **kw) if path.exists() else pd.DataFrame(columns=cols)
    return df.astype({c: object for c in ("covered", "result") if c in df.columns})


@st.cache_data(ttl=20)
def scoreboard(date_str):
    return sources.scoreboard(date_str)


@st.cache_data(ttl=3600)
def season_ratings(season, today):
    return sources.season_ratings(season)


@st.cache_data(ttl=3600)
def season_backtest(season, hfa, today):
    return sources.season_backtest(season, hfa, today)


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
