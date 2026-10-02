import math
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
