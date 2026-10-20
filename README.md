# 🏈 College Football Edge Dashboard

A local Streamlit dashboard that compares a simple scoring model to the Vegas spread, shows how likely each pick is to cover (before and during the game), and tracks your picks, bets and model accuracy over time.

No API keys or paid services. Live scores, lines (current and opening, plus totals) and ESPN's FPI power ratings come from ESPN's public feeds.

## Features

| Tab | What it does |
| --- | --- |
| **Today's games** | Scores, status, current and opening line, total, projected margin, edge, the model's pick, pregame cover %, and a live cover % that updates with the score and clock. Auto-refreshes every 30 seconds. |
| **Team ratings** | Editable table of opponent-adjusted points scored and allowed per game plus ESPN FPI for each team, with an **Auto-fill from ESPN results** button that fills it from this season's completed games. This is what drives the model. |
| **Bet tracker** | Log your bets (date, game, side, line, odds, stake, result) and see net profit and ROI. |
| **Backtest** | Logged picks are graded automatically when games go final, then broken out by confidence bucket (50-54%, 55-59%, and so on). A **season backtest** replays every FBS game this season against its pregame line and compares the projection sources. |

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

1. **Replace the placeholder ratings.** `data/team_ratings.csv` ships with eight teams and made-up numbers. On the **Team ratings** tab, click **Auto-fill from ESPN results** to load opponent-adjusted points scored (`ppg`) and allowed (`papg`) per game and ESPN's FPI (`fpi`) for every FBS team, or type your own. Auto-fill overwrites teams it finds and keeps the rest. The league average used by the model is calculated from the teams in this file, so a short list skews the projections.
2. **Match team names to ESPN.** Names must match the school name ESPN uses (for example `Ohio State`, `Notre Dame`). If a game shows no pick, check the name in the Game column against your CSV.
3. **Open the app before kickoff on game day.** The app saves each game's pregame line when it first sees it. Live probabilities are measured against that line, because live odds already include the score. If you open the app after kickoff, it falls back to ESPN's current line, which makes the live % less reliable.

A game only gets a pick when both teams are in the ratings file and a line is available. When a game has no pick, the **Note** column says why (for example `Add to ratings: Virginia Tech` or `No line yet`), and the line is shown whenever ESPN has one.

## How the model works

**Ratings.** Auto-fill fits every completed game this season at once: each team's points = league average + its offense rating + the opponent's defense rating, with home field estimated too (ridge regression, so teams with few games are pulled toward average). That way 40 points against a top defense counts for more than 40 against a weak one. FCS opponents share a single "FCS" rating. `ppg` and `papg` are those ratings on the normal points scale.

**FPI.** ESPN's Football Power Index is the expected margin against an average FBS team on a neutral field. The FPI projection is `home.fpi - away.fpi + HFA` (no HFA at neutral sites). FPI includes preseason priors, so it's steadier than scoring data early in the season.

**Projection source** (sidebar): *Adjusted points* uses the formula below, *ESPN FPI* uses the FPI projection, and *Blend* (default) averages the two, using whichever one exists when a team lacks the other. Logged picks record which source they came from, and the Backtest tab breaks results out by source.

**Points projection.** Each team's expected points are its own scoring plus the opponent's points allowed, minus the league average, with a home-field bump (split between the two teams, none at neutral sites):

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
- **Projection source:** Blend, Adjusted points, or ESPN FPI (see above).
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
    ├── closing_lines.csv   # pregame lines for finished games, fetched by the season backtest
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

## Season backtest

On the **Backtest** tab, click **Run season backtest**. Starting at week 3, it predicts each week's FBS-vs-FBS games using only what was known beforehand: points ratings refit on earlier games, and ESPN's FPI snapshot from the previous week (ESPN saves one the day after each week's games). Every prediction is graded against ESPN's final pregame line, which is fetched from the game summary feed once and cached in `data/closing_lines.csv`.

The table shows each source's against-the-spread record and hit rate, plus how far its projections landed from the final margin. The **Vegas line** row is the baseline. Use the slider to bet only when the edge is at least a given number of points. At -110 odds you need 52.4% to break even. **RMSE vs result** is the value to use for the margin std dev setting with that source.

## Limitations

- The points model only uses final scores. It doesn't account for injuries, weather, pace or line movement (the Open column shows movement but the model doesn't use it).
- FPI comes from an unofficial ESPN endpoint and may change or disappear; the points model keeps working without it.
- ESPN's feed is unofficial and may change, rate-limit you, or omit lines for some games.
- Backtest results need a decent sample before they mean much.
- This is an analysis tool, not betting advice, and a high cover probability is not a guarantee.

## Ideas for next steps

- Pull team stats from the CFBD API instead of typing them in.
- Replace the formula with logistic regression or gradient boosting and compare them in the backtest.
- Add rest and injury adjustments.

## Troubleshooting

- **`streamlit: command not found`:** activate the environment with `source venv/bin/activate`.
- **"Couldn't load scores":** check your internet connection and click **Refresh now**.
- **No games or no picks:** confirm the date, then check that both team names exist in `team_ratings.csv`.
- **Browser didn't open:** go to `http://localhost:8501` manually.
