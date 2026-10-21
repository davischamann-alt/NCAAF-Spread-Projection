"""Builds the data files the website reads (site/data/*.json): team ratings, model settings and the
track record from the season backtest. Run by the GitHub job every night, or by hand:

    python build_site.py

Past seasons are added to the track record when a CollegeFootballData key is available
(CFBD_API_KEY environment variable or .streamlit/secrets.toml)."""
import datetime as dt
import json
import math
from pathlib import Path

import pandas as pd

import sources
from model import add_anchored, fit_anchor, score_backtest

OUT = Path(__file__).parent / "site" / "data"
HFA = 2.5
PAST = [2023, 2024, 2025]  # seasons with reliable FPI history (see README)
SOURCE_NAMES = {"Adjusted points": "points", "ESPN FPI": "fpi", "Blend": "blend", "Market-anchored": "anchored"}


def clean(x):
    """JSON-safe values: NaN becomes null, numpy numbers become plain floats."""
    if isinstance(x, dict):
        return {k: clean(v) for k, v in x.items()}
    if isinstance(x, list):
        return [clean(v) for v in x]
    if isinstance(x, float) or hasattr(x, "item"):
        x = float(x)
        return None if math.isnan(x) else round(x, 4)
    return x


def write(name, data):
    (OUT / name).write_text(json.dumps(clean(data), indent=1))
    print(f"wrote site/data/{name}")


def table(res, edge, against):
    t = score_backtest(res, edge, against).reset_index()
    return t.rename(columns={"source": "name"}).to_dict("records")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    season = sources.season_of(now.date())

    ratings, fitted_hfa, fpi_err = sources.season_ratings(season)
    write("ratings.json", {"updated": now.isoformat(), "season": season, "fitted_hfa": fitted_hfa,
                           "fpi_error": fpi_err, "teams": ratings.to_dict("records")})

    seasons = [y for y in PAST if y < season] if sources.cfbd_key() else []
    old = OUT / "track_record.json"
    if not seasons and old.exists() and len(json.loads(old.read_text())["seasons"]) > 1:
        # Without a key only this season can be tested, so keep the fuller multi-season record
        print("No CollegeFootballData key: keeping the existing track record and model settings")
        return
    res = pd.concat([sources.season_backtest(y, HFA, now.date().isoformat()) for y in seasons + [season]],
                    ignore_index=True)
    res = add_anchored(res)
    done = res[res["season"].isin(seasons)]
    anchor = ({"weights": fit_anchor(done), "seasons": seasons} if len(done)
              else json.loads(sources.ANCHOR.read_text()) if sources.ANCHOR.exists() else None)

    # typical miss in points for each source: the right margin std dev for its cover percentages
    close = score_backtest(res, 0, "close")
    sigma = {SOURCE_NAMES[n]: round(close.at[n, "rmse_vs_result"] * 2) / 2 for n in close.index if n in SOURCE_NAMES}
    write("model.json", {"updated": now.isoformat(), "hfa": HFA, "anchor": anchor, "sigma": sigma})

    write("track_record.json", {
        "updated": now.isoformat(), "seasons": sorted(res["season"].unique().tolist()), "games": len(res),
        "tables": {f"{against}_{edge}": table(res, edge, against) for against in ("open", "close") for edge in (0, 2, 3)},
        "by_season": [{"season": int(s), "games": len(d), **{r["name"]: r["hit_rate"] for r in table(d, 0, "open")}}
                      for s, d in res.groupby("season")],
    })


if __name__ == "__main__":
    main()
