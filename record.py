"""Forward test: records lines and the model's picks before kickoff, then grades them. Run by the
GitHub job every two hours, or by hand:

    python record.py

Writes three files:
  data/live/line_history.csv  every line change seen, with the time it was seen
  data/live/picks.csv         each game's pick from every source, logged the first time the game
                              has a line and never changed after; closing line and result are
                              filled in later
  site/data/live.json         the summary the website's Track record tab shows

Because the job commits these files to git each run, the repository history proves every pick
was recorded before its game started."""
import datetime as dt
import json

import pandas as pd

import sources
from build_site import clean
from model import projections

LIVE = sources.DATA / "live"
LINES, PICKS = LIVE / "line_history.csv", LIVE / "picks.csv"
SITE_LIVE = sources.DATA.parent / "site" / "data" / "live.json"
HFA = 2.5
STRONG, LEAN = 3.0, 1.5
SOURCES = {"anchored": "Market-anchored", "fpi": "ESPN FPI", "blend": "Blend", "points": "Adjusted points"}
LINE_COLS = ["seen_at", "id", "season", "week", "kickoff", "home", "away", "line", "open_line", "total"]
# columns up to "tier" are written once when a pick is logged and never edited
PICK_COLS = ["logged_at", "id", "season", "seasontype", "week", "kickoff", "home", "away", "neutral", "source",
             "margin", "line_logged", "open_line", "edge", "side", "tier",
             "close_line", "final_margin", "result_logged", "result_close", "clv"]


def load(path, cols):
    return pd.read_csv(path, dtype={"id": str}) if path.exists() else pd.DataFrame(columns=cols)


def weeks_to_check():
    """The current week, plus the next one so Sunday's opening lines for it are caught."""
    games, info = sources.week_scoreboard()
    out = [(info, games)]
    key = (info["seasontype"], info["week"])
    if key in info["calendar"] and info["calendar"].index(key) + 1 < len(info["calendar"]):
        st, wk = info["calendar"][info["calendar"].index(key) + 1]
        nxt, ninfo = sources.week_scoreboard(info["season"], st, wk)
        out.append((ninfo, nxt))
    return out


def record_lines(weeks, now):
    hist = load(LINES, LINE_COLS)
    last = hist.drop_duplicates("id", keep="last").set_index("id")
    new = []
    for info, games in weeks:
        for g in games[(games.state == "pre") & games.line.notna()].itertuples():
            prev = last.loc[g.id] if g.id in last.index else None
            if prev is not None and prev["line"] == g.line and (prev["total"] == g.total or
                                                                (pd.isna(prev["total"]) and pd.isna(g.total))):
                continue
            new.append(dict(seen_at=now, id=g.id, season=info["season"], week=info["week"], kickoff=g.kickoff,
                            home=g.home, away=g.away, line=g.line, open_line=g.open_line, total=g.total))
    if new:
        pd.concat([hist, pd.DataFrame(new, columns=LINE_COLS)], ignore_index=True).to_csv(LINES, index=False)
    return len(new)


def log_picks(weeks, picks, ratings, weights, now):
    """Logs every source's pick for games seen with a line for the first time."""
    have = set(picks["id"])
    new = []
    for info, games in weeks:
        for g in games[(games.state == "pre") & games.line.notna()].itertuples():
            if g.id in have:
                continue
            proj = projections(g.home, g.away, ratings, g.neutral, HFA, g.line, weights)
            for src, m in proj.items():
                if m is None:
                    continue
                edge = m + g.line
                new.append(dict(logged_at=now, id=g.id, season=info["season"], seasontype=info["seasontype"],
                                week=info["week"], kickoff=g.kickoff, home=g.home, away=g.away, neutral=g.neutral,
                                source=src, margin=round(m, 2), line_logged=g.line, open_line=g.open_line,
                                edge=round(abs(edge), 2), side="home" if edge >= 0 else "away",
                                tier="strong" if abs(edge) >= STRONG else "lean" if abs(edge) >= LEAN else "small"))
    return pd.concat([picks, pd.DataFrame(new, columns=PICK_COLS)], ignore_index=True), len({p["id"] for p in new})


def ats(margin, line, side):
    x = (margin + line) * (1 if side == "home" else -1)
    return "W" if x > 0 else "L" if x < 0 else "P"


def update_picks(picks, weeks):
    """Closing line (last line seen before kickoff) and results for finished games."""
    lines = load(LINES, LINE_COLS).drop_duplicates("id", keep="last").set_index("id")["line"]
    finals = {}
    for _, games in weeks:
        finals.update({g.id: g.home_score - g.away_score for g in games[games.state == "post"].itertuples()})
    # finished games from earlier weeks that aren't graded yet
    todo = picks[picks.result_logged.isna() & ~picks.id.isin(finals)]
    todo = todo[pd.to_datetime(todo.kickoff, utc=True) < pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=3)]
    for (season, st, wk), _ in todo.groupby(["season", "seasontype", "week"]):
        games, _ = sources.week_scoreboard(int(season), int(st), int(wk))
        finals.update({g.id: g.home_score - g.away_score for g in games[games.state == "post"].itertuples()})
    for i, p in picks.iterrows():
        if pd.isna(p.result_logged) and p.id in lines.index:
            picks.at[i, "close_line"] = lines[p.id]
        if pd.isna(p.result_logged) and p.id in finals:
            fm, close = finals[p.id], picks.at[i, "close_line"]
            picks.at[i, "final_margin"] = fm
            picks.at[i, "result_logged"] = ats(fm, p.line_logged, p.side)
            if pd.notna(close):
                picks.at[i, "result_close"] = ats(fm, close, p.side)
                picks.at[i, "clv"] = (p.line_logged - close) * (1 if p.side == "home" else -1)
    return picks


def summary(picks, now):
    def record(d, col):
        w, l, pu = (d[col] == "W").sum(), (d[col] == "L").sum(), (d[col] == "P").sum()
        return dict(wins=int(w), losses=int(l), pushes=int(pu), hit_rate=float(w / (w + l)) if w + l else None)

    rows = []
    for src, name in SOURCES.items():
        for tier, label in (("all", "Every game"), ("lean", "Edge 1.5+"), ("strong", "Edge 3+")):
            d = picks[picks.source == src]
            if tier == "lean":
                d = d[d.tier.isin(["lean", "strong"])]
            elif tier == "strong":
                d = d[d.tier == "strong"]
            done = d[d.result_logged.notna()]
            moved = done.clv.dropna()
            moved = moved[moved != 0]
            rows.append(dict(source=name, key=src, tier=tier, label=label, picks=len(d), pending=int(len(d) - len(done)),
                             at_logged=record(done, "result_logged"), at_close=record(done, "result_close"),
                             avg_clv=float(done.clv.mean()) if done.clv.notna().any() else None,
                             clv_beat_rate=float((moved > 0).mean()) if len(moved) else None))
    anchored = picks[(picks.source == "anchored") & picks.tier.isin(["lean", "strong"])].sort_values("kickoff", ascending=False)
    recent = [dict(id=p.id, kickoff=p.kickoff, game=f"{p.away} @ {p.home}", side=p.side, team=p.home if p.side == "home" else p.away,
                   line=p.line_logged if p.side == "home" else -p.line_logged, edge=p.edge, tier=p.tier,
                   logged_at=p.logged_at, result=None if pd.isna(p.result_logged) else p.result_logged,
                   clv=None if pd.isna(p.clv) else float(p.clv))
              for p in anchored.head(60).itertuples()]
    return dict(updated=now, since=picks.logged_at.min() if len(picks) else None, games=int(picks.id.nunique()),
                summary=rows, recent=recent)


def main():
    LIVE.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    weeks = weeks_to_check()
    n_lines = record_lines(weeks, now)

    picks = load(PICKS, PICK_COLS).astype({c: object for c in ("result_logged", "result_close")})
    ratings, _, _ = sources.season_ratings(weeks[0][0]["season"])
    ratings = ratings.set_index("team")
    weights = json.loads(sources.ANCHOR.read_text())["weights"] if sources.ANCHOR.exists() else None
    picks, n_new = log_picks(weeks, picks, ratings, weights, now)
    picks = update_picks(picks, weeks)
    picks.to_csv(PICKS, index=False)

    SITE_LIVE.write_text(json.dumps(clean(summary(picks, now)), indent=1))
    graded = picks.drop_duplicates("id").result_logged.notna().sum()
    print(f"{n_lines} line changes, {n_new} new games logged, {graded} of {picks.id.nunique()} games graded")


if __name__ == "__main__":
    main()
