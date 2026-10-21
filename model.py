import math

import numpy as np
import pandas as pd


def load_ratings(path):
    return pd.read_csv(path).set_index("team")


def project(home, away, r, neutral=False, hfa=2.5):
    """Expected (home_pts, away_pts) from each side's scoring vs the other's defense."""
    if home not in r.index or away not in r.index:
        return None
    avg = (r["ppg"].mean() + r["papg"].mean()) / 2
    h, a = r.loc[home], r.loc[away]
    bump = 0 if neutral else hfa / 2
    return (h["ppg"] + a["papg"] - avg + bump, a["ppg"] + h["papg"] - avg - bump)


def fpi_margin(home, away, r, neutral=False, hfa=2.5):
    """Projected home margin from ESPN FPI (points vs an average team on a neutral field)."""
    if "fpi" not in r.columns or home not in r.index or away not in r.index:
        return None
    h, a = r.at[home, "fpi"], r.at[away, "fpi"]
    if pd.isna(h) or pd.isna(a):
        return None
    return h - a + (0 if neutral else hfa)


def fit_ratings(games, ridge=2.0):
    """Opponent-adjusted scoring. games: (home, away, home_pts, away_pts, neutral) tuples.
    Fits pts = avg + off[team] + dfn[opp] +/- hfa/2 by ridge least squares, so a team that
    put up 40 on a bad defense counts for less than 40 on a good one. Returns
    (DataFrame of team, ppg, papg, games on the raw points scale, fitted home-field edge)."""
    teams = sorted({t for g in games for t in g[:2]})
    ix, n = {t: i for i, t in enumerate(teams)}, len(teams)
    X, y = np.zeros((2 * len(games), 2 * n + 2)), np.zeros(2 * len(games))
    for k, (h, a, hs, as_, neu) in enumerate(games):
        for j, (me, op, pts, side) in enumerate(((h, a, hs, 0.5), (a, h, as_, -0.5))):
            row = 2 * k + j
            X[row, [0, 1 + ix[me], 1 + n + ix[op]]] = 1
            X[row, -1] = 0 if neu else side
            y[row] = pts
    pen = np.sqrt(ridge) * np.eye(2 * n + 2)[1:-1]  # shrink team terms toward average, not avg/hfa
    coef = np.linalg.lstsq(np.vstack([X, pen]), np.concatenate([y, np.zeros(2 * n)]), rcond=None)[0]
    cnt = pd.Series([t for g in games for t in g[:2]]).value_counts()
    df = pd.DataFrame({"team": teams, "ppg": coef[0] + coef[1:1 + n], "papg": coef[0] + coef[1 + n:-1]})
    df["games"] = df["team"].map(cnt)
    return df, coef[-1]


def cover_prob(margin, home_line, sigma=14.0):
    """P(home covers). margin = home - away; home_line is negative when home is favored."""
    z = (margin + home_line) / sigma
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def live_cover_prob(cur_margin, proj_margin, home_line, secs_left, sigma=14.0):
    """P(home covers) mid-game: current margin plus the model's projection for the time left."""
    x = cur_margin + home_line
    if secs_left <= 0:
        return 1.0 if x > 0 else 0.0 if x < 0 else 0.5
    f = min(secs_left / 3600, 1.0)
    z = (x + proj_margin * f) / (sigma * math.sqrt(f))
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def pool_fcs(games, fbs=None):
    """Rename non-FBS teams to "FCS" so they share one rating. FCS opponents mostly have one or
    two games, too few to rate on their own (shrinking each one toward average credits FBS
    blowouts to home field). fbs: set of FBS names, else guessed from games played."""
    if fbs is None:
        cnt = pd.Series([t for g in games for t in g[:2]]).value_counts()
        fbs = set(cnt[cnt >= max(1, (cnt.max() + 1) // 2)].index)
    return [tuple(t if t in fbs else "FCS" for t in g[:2]) + tuple(g[2:]) for g in games]


def walk_forward(games, lines, fpi_by_week, fbs, hfa=2.5, start_week=3):
    """Predict each week using only what was known before it: points ratings fit on earlier
    games, and the FPI snapshot from the previous week. games: DataFrame of completed games
    (id, week, home, away, home_id, away_id, home_pts, away_pts, neutral);
    lines: {id: (closing home line, opening home line)};
    fpi_by_week: {week: {team id: fpi}}. Returns one row per FBS-vs-FBS game with a line."""
    rows = []
    for w in sorted(games.loc[games.week >= start_week, "week"].unique()):
        train = games[games.week < w]
        fit = list(train[["home", "away", "home_pts", "away_pts", "neutral"]].itertuples(index=False, name=None))
        r = fit_ratings(pool_fcs(fit, fbs))[0].set_index("team")
        fpi = fpi_by_week.get(w - 1, {})
        for g in games[games.week == w].itertuples():
            line, open_line = lines.get(g.id, (None, None))
            if g.home not in fbs or g.away not in fbs or line is None or pd.isna(line):
                continue
            p = project(g.home, g.away, r, g.neutral, hfa)
            pts = None if p is None else p[0] - p[1]
            f = None
            if g.home_id in fpi and g.away_id in fpi:
                f = fpi[g.home_id] - fpi[g.away_id] + (0 if g.neutral else hfa)
            if pts is None or f is None:
                continue
            rows.append(dict(id=g.id, week=w, game=f"{g.away} @ {g.home}", line=line, open_line=open_line,
                             final_margin=g.home_pts - g.away_pts, points=pts, fpi=f, blend=(pts + f) / 2))
    return pd.DataFrame(rows)


ANCHOR_FEATURES = ["const", "line", "fpi", "points"]


def fit_anchor(res):
    """Weights for the market-anchored projection: final margin regressed on the opening line
    (as a home margin), FPI and adjusted points, by least squares on backtest rows. The line
    does most of the work; the ratings only shift it where they disagree."""
    d = res.dropna(subset=["open_line", "fpi", "points"])
    X = np.column_stack([np.ones(len(d)), -d["open_line"], d["fpi"], d["points"]])
    return dict(zip(ANCHOR_FEATURES, np.linalg.lstsq(X, d["final_margin"], rcond=None)[0].round(4)))


def anchored_margin(w, home_line, fpi, pts):
    """Projected home margin from fit_anchor weights; home_line is the (opening) home spread."""
    return w["const"] - w["line"] * home_line + w["fpi"] * fpi + w["points"] * pts


def add_anchored(res, first_train_season=2023):
    """Adds an "anchored" column, each season predicted with weights fit only on earlier seasons
    in res (from first_train_season on). Seasons with no earlier season to learn from get NaN."""
    res = res.copy()
    res["anchored"] = np.nan
    for s in sorted(res["season"].unique()):
        train = res[(res["season"] < s) & (res["season"] >= first_train_season)]
        if train["open_line"].notna().sum() < 200:
            continue
        w, m = fit_anchor(train), res["season"] == s
        res.loc[m, "anchored"] = anchored_margin(w, res.loc[m, "open_line"].fillna(res.loc[m, "line"]),
                                                 res.loc[m, "fpi"], res.loc[m, "points"])
    return res


def score_backtest(res, min_edge=0.0, against="close"):
    """Per-source against-the-spread record and accuracy. against="open" grades picks made at the
    opening line and adds closing line value (CLV): how far the line moved toward the pick by
    kickoff. Sharp bettors aim for positive CLV, which shows edge long before win rates do.
    Picks with edge below min_edge are skipped. RMSE vs result is the right value for the
    margin std dev setting."""
    col_line = "open_line" if against == "open" else "line"
    res = res.dropna(subset=[col_line])
    out = []
    sources = [("Adjusted points", "points"), ("ESPN FPI", "fpi"), ("Blend", "blend")]
    if "anchored" in res.columns and res["anchored"].notna().any():
        sources.append(("Market-anchored", "anchored"))
    for name, col in sources:
        edge = res[col] + res[col_line]  # NaN for games a source has no projection for: never picked
        pick = res[edge.abs() >= min_edge]
        side = np.sign(edge[pick.index])
        ats = (pick["final_margin"] + pick[col_line]) * side
        w, l = int((ats > 0).sum()), int((ats < 0).sum())
        err = res[col] - res["final_margin"]
        row = dict(source=name, picks=w + l, wins=w, losses=l, pushes=int((ats == 0).sum()),
                   hit_rate=w / (w + l) if w + l else None,
                   mae_vs_result=err.abs().mean(), rmse_vs_result=np.sqrt((err ** 2).mean()),
                   mae_vs_line=edge.abs().mean())
        if against == "open":
            # home line falling (home more favored) is movement toward a home pick
            clv = (pick["open_line"] - pick["line"]) * side
            moved = clv[clv != 0]
            row.update(avg_clv=clv.mean(), clv_beat_rate=(moved > 0).mean() if len(moved) else None)
        out.append(row)
    err = -res[col_line] - res["final_margin"]
    out.append(dict(source=("Opening" if against == "open" else "Closing") + " line (baseline)",
                    mae_vs_result=err.abs().mean(), rmse_vs_result=np.sqrt((err ** 2).mean()), mae_vs_line=0.0))
    return pd.DataFrame(out).set_index("source")
