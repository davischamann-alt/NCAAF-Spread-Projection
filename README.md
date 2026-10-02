# 🏈 College Football Edge Dashboard

A local Streamlit dashboard that compares a simple scoring model to the Vegas spread, shows how likely each pick is to cover (before and during the game), and tracks your picks, bets and model accuracy over time.

No API keys or paid services. Live scores and lines come from ESPN's public scoreboard feed.

## Features

| Tab | What it does |
| --- | --- |
| **Today's games** | Scores, status, line, projected margin, edge, the model's pick, pregame cover %, and a live cover % that updates with the score and clock. Auto-refreshes every 30 seconds. |
| **Team ratings** | Editable table of points scored and allowed per game for each team. This is what drives the model. |
| **Bet tracker** | Log your bets (date, game, side, line, odds, stake, result) and see net profit and ROI. |
| **Backtest** | Logged picks are graded automatically when games go final, then broken out by confidence bucket (50-54%, 55-59%, and so on). |

## Quick start (Mac)

```bash
cd ~/Downloads/cfb_edge
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

The dashboard opens at `http://localhost:8501`. Stop it with `Ctrl + C`.

Next time, you only need:

```bash
cd ~/Downloads/cfb_edge
source venv/bin/activate
streamlit run app.py
```

On Windows, activate the environment with `venv\Scripts\activate` instead.

## Before you rely on it

1. **Replace the placeholder ratings.** `data/team_ratings.csv` ships with eight teams and made-up numbers. Add real points-per-game (`ppg`) and points-allowed-per-game (`papg`) for every team you want rated, ideally all of FBS. The league average used by the model is calculated from the teams in this file, so a short list skews the projections.
2. **Match team names to ESPN.** Names must match the school name ESPN uses (for example `Ohio State`, `Notre Dame`). If a game shows no pick, check the name in the Game column against your CSV.
3. **Open the app before kickoff on game day.** The app saves each game's pregame line when it first sees it. Live probabilities are measured against that line, because live odds already include the score. If you open the app after kickoff, it falls back to ESPN's current line, which makes the live % less reliable.

A game only gets a pick when both teams are in the ratings file and a line is available.

## How the model works

**Projection.** Each team's expected points are its own scoring plus the opponent's points allowed, minus the league average, with a home-field bump (split between the two teams, none at neutral sites):

```
home_pts = home.ppg + away.papg - league_avg + HFA/2
away_pts = away.ppg + home.papg - league_avg - HFA/2
projected margin = home_pts - away_pts
```

**Pregame cover probability.** The margin is treated as a normal distribution around the projection. The line is from the home team's view, so a negative number means the home team is favored.

```
P(home covers) = Normal CDF( (projected margin + home line) / sigma )
edge (pts)     = |projected margin + home line|
```

**Live cover probability.** As the game goes on, the expected final margin is the current margin plus the projected margin scaled by the share of the game left, and the uncertainty shrinks with the square root of the time left.

```
expected final margin = current margin + projected margin x (time left / 60 min)
sigma_live            = sigma x sqrt(time left / 60 min)
```

Final games resolve to 100% or 0% (50% on a push). Overtime is treated as roughly two minutes left.

## Settings (sidebar)

- **Date:** which day's games to show.
- **Margin std dev:** spread of game outcomes around the projection (default 14 points).
- **Home-field advantage:** points added for the home team (default 2.5).
- **Refresh now / Auto-refresh:** clear the cache and reload, or toggle the 30-second refresh.

## Files

```
cfb_edge/
├── app.py                  # Streamlit dashboard
├── model.py                # projection, cover probability, live probability
├── requirements.txt
└── data/
    ├── team_ratings.csv    # you edit this (also editable in the app)
    ├── history.csv         # created when you log picks; graded automatically
    ├── lines.csv           # pregame lines the app has saved
    └── bets.csv            # created when you save in the Bet tracker
```

## Logging and backtesting

1. On the **Today's games** tab, click **Log these pregame picks to history** before the games start. Only pregame picks are logged, so mid-game picks don't skew the results.
2. Keep the app running after games finish, or reopen it later and pick that game day in the sidebar. Logged picks are graded automatically as covered (Y), not covered (N) or push.
3. Open the **Backtest** tab to see the overall hit rate and the hit rate by confidence bucket. Reload the page to pick up newly graded results.

## Bet tracker notes

- Results are `W`, `L` or `Push`. Blank odds default to -110.
- Winnings use American odds: a win at -110 on a 110 stake pays 100.
- Click **Save bets** to write your changes to `data/bets.csv`.

## Limitations

- The model is deliberately simple (scoring averages only). It doesn't account for injuries, weather, pace, strength of schedule or line movement.
- ESPN's feed is unofficial and may change, rate-limit you, or omit lines for some games.
- Backtest results need a decent sample before they mean much.
- This is an analysis tool, not betting advice, and a high cover probability is not a guarantee.

## Ideas for next steps

- Pull team stats from the CFBD API instead of typing them in.
- Track opening vs. current lines and line movement.
- Replace the formula with logistic regression or gradient boosting and compare them in the backtest.
- Add strength-of-schedule, rest and injury adjustments.

## Troubleshooting

- **`streamlit: command not found`:** activate the environment with `source venv/bin/activate`.
- **"Couldn't load scores":** check your internet connection and click **Refresh now**.
- **No games or no picks:** confirm the date, then check that both team names exist in `team_ratings.csv`.
- **Browser didn't open:** go to `http://localhost:8501` manually.
