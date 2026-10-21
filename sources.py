"""Data downloads shared by the Streamlit app and the website builder: ESPN scores, lines and FPI,
and past seasons from CollegeFootballData. Nothing here depends on Streamlit."""
import datetime as dt
import json
import os
import re
import tomllib
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import requests

from model import fit_ratings, pool_fcs, walk_forward

DATA = Path(__file__).parent / "data"
RATINGS = DATA / "team_ratings.csv"
CLOSING = DATA / "closing_lines.csv"
ANCHOR = DATA / "anchor_weights.json"
CFBD_DIR = DATA / "cfbd"
SECRETS = Path(__file__).parent / ".streamlit" / "secrets.toml"
CFBD = "https://api.collegefootballdata.com"
# sportsbooks to take lines from, in order of preference (CFBD's provider names)
BOOKS = ["DraftKings", "ESPN Bet", "Bovada", "William Hill (New Jersey)", "consensus"]
ESPN = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/scoreboard"
FPI = "https://site.web.api.espn.com/apis/fitt/v3/sports/football/college-football/powerindex"
FPI_WEEKLY = "https://sports.core.api.espn.com/v2/sports/football/leagues/college-football"
SUMMARY = "https://site.api.espn.com/apis/site/v2/sports/football/college-football/summary"


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


def season_ratings(season):
    """Opponent-adjusted points scored/allowed per game from this season's completed games,
    plus ESPN FPI. Returns (ratings, fitted home-field edge, FPI error or None)."""
    games = season_games(season)
    if games.empty:
        return pd.DataFrame(columns=["team", "ppg", "papg", "games", "fpi", "id"]), None, None
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
    df["id"] = df["team"].map({n: i for i, n in names.items()})
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
    """CollegeFootballData key from the CFBD_API_KEY environment variable or .streamlit/secrets.toml."""
    if key := os.environ.get("CFBD_API_KEY", ""):
        return key
    try:
        return tomllib.loads(SECRETS.read_text()).get("CFBD_API_KEY", "")
    except (OSError, tomllib.TOMLDecodeError):
        return ""


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
            home_id=h["team"]["id"], away_id=a["team"]["id"],
            home_score=int(h.get("score") or 0), away_score=int(a.get("score") or 0),
            status=c["status"]["type"]["shortDetail"], state=c["status"]["type"]["state"],
            neutral=c.get("neutralSite", False), line=line, open_line=open_line, total=total,
            period=c["status"].get("period", 0), clock=float(c["status"].get("clock") or 0)))
    return pd.DataFrame(rows)
