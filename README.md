# Fourth & Value

**Only go for it when the numbers say so.**

> **New name, new address (October 24, 2026).** This project used to be called **CFB Edge**, in a repository named `NCAAF-Spread-Projection`. It's now **Fourth & Value**:
>
> - **Website:** [davischamann-alt.github.io/fourth-and-value](https://davischamann-alt.github.io/fourth-and-value/). The old address, `davischamann-alt.github.io/NCAAF-Spread-Projection`, no longer works, so update any bookmarks or links you've shared.
> - **Repository:** [github.com/davischamann-alt/fourth-and-value](https://github.com/davischamann-alt/fourth-and-value). Old repository links redirect here automatically.
> - **If you cloned the old repository,** point your copy at the new one with `git remote set-url origin https://github.com/davischamann-alt/fourth-and-value.git`.
>
> Nothing else changed: the model, the data and the forward-test pick log carried over as they were.

College football spread projections, compared with the Vegas betting line. Fourth & Value shows which side its model would pick, how likely that pick is to cover before and during the game, and how well its picks have done, including a public log of picks recorded before kickoff.

It's free. Scores, lines and ESPN's team ratings come from ESPN's public data. Testing past seasons is optional and uses a free key from CollegeFootballData.com.

**Two ways to use it:**

| | **Website** | **App on your computer** |
| --- | --- | --- |
| Where | **[davischamann-alt.github.io/fourth-and-value](https://davischamann-alt.github.io/fourth-and-value/)** | Runs in your browser from your own computer |
| Setup | None: open the link on any phone or computer | About 10 minutes ([Install and run it](#install-and-run-it)) |
| Games, picks, live cover chances | ✅ | ✅ |
| Ratings | Updated automatically every morning | Click **Auto-fill** to update |
| Your picks and bets | Saved in that browser | Saved as files on your computer |
| Run new backtests | Shows the latest results | ✅ Run any seasons and settings |

> **This is an analysis tool, not betting advice.** Testing on past seasons found no source that beats the final (closing) line. The only possible edge showed up against opening lines, and it isn't proven yet. See [What the testing found](#what-the-testing-found).

**Contents**

1. [What it does](#what-it-does) and [the website](#the-website)
2. [Terms you'll see](#terms-youll-see)
3. [Install and run it](#install-and-run-it)
4. [Using it on game day](#using-it-on-game-day)
5. [The four tabs](#the-four-tabs)
6. [Sidebar settings](#sidebar-settings)
7. [Testing on past seasons](#testing-on-past-seasons)
8. [What the testing found](#what-the-testing-found)
9. [The forward test](#the-forward-test)
10. [How the model works](#how-the-model-works)
11. [Publishing the website](#publishing-the-website)
12. [Files](#files)
13. [Troubleshooting](#troubleshooting)
14. [Limitations](#limitations)

---

## What it does

- **Predicts every game's margin** (how many points the home team wins or loses by), using one of four methods you choose.
- **Compares that prediction with the betting line** and picks the side it thinks will cover.
- **Gives a cover chance before the game** and a live one that updates with the score and clock.
- **Logs and grades your picks** automatically when games end.
- **Tracks your bets,** with profit and return on investment.
- **Tests itself on past seasons,** predicting each week with only the information available at the time.

### The website

Open **[davischamann-alt.github.io/fourth-and-value](https://davischamann-alt.github.io/fourth-and-value/)**. It works on phones, and you can add it to your home screen from the browser's Share menu.

- **Games:** one week at a time (use ‹ › to change weeks), grouped by day. Each game card shows the line and where it opened, the model's pick, an edge badge labeled like a fourth-down call (**Go for it** at 3+ points, **Lean** at 1.5–3, **Punt** under 1.5, meaning no bet), and the cover chance, which updates live during games. Filter to go-for-it edges or live games, sort by biggest edge, or search for a team.
- **Game details:** tap any game card for the full breakdown. Each game has its own link (like `#game/401858274`) that you can share.
  - **Why this pick:** what all four projections say, and whether they agree. A split is a reason to punt.
  - **Line movement:** a chart of the line through the week, from the forward test's two-hourly recordings.
  - **Matchup:** FPI rank and adjusted offense and defense, ESPN's season stats (or game stats once it starts), and each team's last five results.
  - **A second opinion:** ESPN's matchup predictor next to the model's win chance.
  - **Conditions:** venue, field surface, and the weather forecast when ESPN has one.
  - **Forward test:** when the pick was recorded, at what line, and how it graded.
  - **Live and finished games:** ESPN's play-by-play win chance and each team's leaders, updating every 30 seconds while the game is on.
  - **Not included:** injuries, because ESPN doesn't publish them for college football. Check quarterback news yourself.
- **Ratings:** every FBS team's FPI and adjusted offense and defense, sortable and searchable.
- **My picks:** tap **☆ Track pick** on a game before kickoff, and it's graded automatically when the game ends.
- **Bets:** log bets and see your record, profit and ROI, and download or import them as CSV.
- **Track record:** live results of picks recorded before kickoff ([The forward test](#the-forward-test)), then the backtest results in plain language.
- **⚙︎ Settings:** home-field advantage, std dev (it uses the tested value for each projection automatically) and light or dark theme.

Picks and bets are saved only in the browser you use, so they don't follow you between devices; use **Download as CSV** to move bets. The page gets scores and lines straight from ESPN while you have it open, and a GitHub job refreshes the ratings and track record every morning ([Publishing the website](#publishing-the-website)).

---

## Terms you'll see

| Term | Meaning |
| --- | --- |
| **Spread / line** | The betting line, shown from the home team's side. **-7** means the home team is favored by 7, and **+3** means it's a 3-point underdog. |
| **Cover** | Win against the spread. A 7-point favorite covers by winning by more than 7. Winning by exactly 7 is a **push**, and the bet is refunded. |
| **Projected margin** | The dashboard's prediction of home score minus away score. **+10** means the home team by 10. |
| **Edge** | How far the projection is from the line, in points. Bigger means the model disagrees with Vegas more. |
| **Opening line** | The first line a sportsbook posts, usually the Sunday before the game. It's the easiest line to beat. |
| **Closing line** | The final line at kickoff, after all the betting has moved it. It's the hardest line to beat. |
| **CLV (closing line value)** | How far the line moved toward your pick between open and kickoff. Lines that keep moving your way are the standard sign of a real edge. |
| **Hit rate** | The share of picks that covered. At standard -110 odds, you need **52.4%** to break even. |
| **FPI** | ESPN's Football Power Index: how many points better or worse a team is than an average FBS team on a neutral field. |
| **FBS / FCS** | The top two divisions of college football. The dashboard rates FBS teams; FCS opponents share a single rating. |

---

## Install and run it

You need about 10 minutes and an internet connection. No programming is required: you'll copy and paste a few commands.

### 1. Install Python (one time)

- **Mac:** open **Terminal** (press `Cmd + Space` and type "Terminal"), then run `python3 --version`. If it prints `Python 3.11` or higher, skip ahead. Otherwise, download the installer from [python.org/downloads](https://www.python.org/downloads/) and run it.
- **Windows:** download the installer from [python.org/downloads](https://www.python.org/downloads/). On the first screen of the installer, tick **"Add python.exe to PATH"**. Then open **Command Prompt** (press the Windows key and type "cmd").

### 2. Get the code (one time)

**Option A, no tools needed:** on the [GitHub page](https://github.com/davischamann-alt/fourth-and-value), click the green **Code** button, then **Download ZIP**. Unzip it into your **Downloads** folder, and rename the folder to `fourth-and-value` if it has a different name (GitHub usually adds `-main`).

**Option B, with git:**

```bash
cd ~/Downloads
git clone https://github.com/davischamann-alt/fourth-and-value.git
```

### 3. Set it up (one time)

Run these one at a time in Terminal or Command Prompt. They create a private Python environment for the dashboard and install the three libraries it uses (Streamlit, pandas and requests).

**Mac:**

```bash
cd ~/Downloads/fourth-and-value
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**Windows:**

```bat
cd %USERPROFILE%\Downloads\fourth-and-value
py -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 4. Start the dashboard (every time)

**Mac:**

```bash
cd ~/Downloads/fourth-and-value
source venv/bin/activate
streamlit run app.py
```

**Windows:**

```bat
cd %USERPROFILE%\Downloads\fourth-and-value
venv\Scripts\activate
streamlit run app.py
```

Your browser opens the dashboard at **http://localhost:8501**. Leave the Terminal window open while you use it. To stop it, click the Terminal window and press `Ctrl + C`.

The first time Streamlit runs, it may ask for an email address. You can press **Enter** to skip that. Notes suggesting a newer `pip` or installing `watchdog` are safe to ignore.

---

## Using it on game day

1. **Refresh the ratings once a week.** On the **Team ratings** tab, click **⚡ Auto-fill from ESPN results**. It takes about a minute and updates every FBS team from the season's results. The download comes with ratings already filled in, but they go stale as the season goes on.
2. **Open the dashboard before kickoff.** It saves each game's pregame line the first time it sees it, and the live cover chance is measured against that line. After kickoff, ESPN stops listing odds for that game.
3. **Choose a projection source** in the sidebar. If you're unsure, use **ESPN FPI** or **Market-anchored**; see [What the testing found](#what-the-testing-found).
4. **Read the board.** Each game shows its line, projected margin, edge, the pick and its cover chance. If a game has no pick, the **Note** column says why.
5. **Log your picks** (optional). Click **📌 Log these pregame picks to history** before the games start, and they're graded automatically after the games finish.

---

## The four tabs

### Today's games

One row per game on the date chosen in the sidebar. It refreshes every 30 seconds.

| Column | What it shows |
| --- | --- |
| Game, Status, Score | Matchup (away @ home), game clock and score |
| Home line | The current line, or the saved pregame line once the game has started |
| Open | The opening line; compare it with Home line to see how the line has moved |
| Total | The over/under for total points |
| Proj margin | The model's predicted home margin |
| Edge (pts) | How far the projection is from the line |
| Pick | The side the model picks, with its line |
| Pregame % | The chance the pick covers, before the game |
| Live cover % | The same chance, updated with the score and time left |
| Note | Why a game has no pick (for example, a team missing from the ratings or no line yet) |

### Team ratings

A table with one row per team, which you can edit:

- **ppg / papg:** points scored and allowed per game, adjusted for opponent strength.
- **fpi:** ESPN's power rating.
- **games:** games played.

**⚡ Auto-fill from ESPN results** rebuilds the table from this season's games. Team names have to match the names ESPN uses (for example `Ohio State`, `Miami`). If you edit the table by hand, click **Save ratings**.

### Bet tracker

Record each bet: date, game, side, line, odds, stake and result (`W`, `L` or `Push`). Blank odds count as -110. Click **Save bets** to keep them. The tab shows the number of graded bets, net profit and ROI. Bets are stored only on your computer.

### Backtest

Two sections:

1. **Your logged picks:** your logged picks, graded, with hit rates by confidence level (50–54%, 55–59% and so on) and by projection source.
2. **Season backtest:** tests every projection source on whole seasons. See [Testing on past seasons](#testing-on-past-seasons).

---

## Sidebar settings

| Setting | What it does | Default |
| --- | --- | --- |
| **Date** | Which day's games to show | Today |
| **Margin std dev** | How spread out game results are around the projection; this drives the cover percentages | 14. Testing suggests about 15.5 for FPI, Market-anchored and Blend, and 16.5 for Adjusted points. |
| **Home-field advantage** | Points given to the home team (none at neutral sites) | 2.5 |
| **Projection source** | Which prediction method to use (see below) | Blend |
| **Refresh now** | Reloads all data right away | — |
| **Auto-refresh every 30s** | Keeps the scoreboard updating on its own | On |

**Projection sources:**

- **Adjusted points:** built from each team's points scored and allowed, adjusted for who they played.
- **ESPN FPI:** built from ESPN's power ratings.
- **Blend:** the average of the two.
- **Market-anchored:** starts from the current betting line and shifts it toward what FPI and the points ratings say. It makes fewer picks but tested best. It only works once the season backtest has been run on past seasons, which saves the weights it uses (`data/anchor_weights.json`). Those saved weights are included in the download, so it works right away.

---

## Testing on past seasons

On the **Backtest** tab, choose **Seasons** and click **▶ Run season backtest**. For each week from week 3 on, it predicts the games using only what was known before that week, then grades the picks.

- **The current season** works right away, using ESPN data.
- **Past seasons (2021 on)** need a free CollegeFootballData key. Set it up once:
  1. Get a key at [collegefootballdata.com/key](https://collegefootballdata.com/key). It arrives by email.
  2. In the project folder, create a folder named `.streamlit`, and inside it a text file named `secrets.toml` containing:
     ```toml
     CFBD_API_KEY = "paste-your-key-here"
     ```
  3. In the dashboard, click **Refresh now**.

  Keep the key private. The file is set to be left out of git, so it won't be uploaded to GitHub. Each past season uses two API calls the first time and is then saved in `data/cfbd/`; the free plan allows 1,000 calls a month.

**Reading the results:**

- **Grade against:**
  - **Opening line:** picks made when lines are first posted. This view adds **CLV** columns showing how often the line moved toward the pick.
  - **Closing line:** the final line at kickoff, which is the tougher test.
- **Only bet when edge is at least:** counts only picks where the model disagrees with the line by at least this many points.
- **hit_rate:** the share of picks that covered. Compare it with 52.4%.
- **RMSE vs result:** the typical miss in points. Use it for the **Margin std dev** setting.
- **line (baseline):** how close the line itself came to the final scores, for comparison.
- **Market-anchored** predicts each season using only weights learned from earlier seasons you selected, so the first season you select has no Market-anchored picks.

2021 and 2022 have only a few usable weeks each, because ESPN overwrote most of those seasons' weekly FPI ratings later. 2023 onward is the most reliable.

---

## What the testing found

These results are from 2023–2026 (through week 7 of 2026), about 2,270 games. Market-anchored was tested on 2024–2026 because 2023 was its training data.

| Picks made at the… | Result |
| --- | --- |
| **Closing line** | No source beats it: about 50–51% for every source, below break-even. |
| **Opening line, every game** | About 53.5% for every source, just above the 52.4% break-even. |
| **Opening line, edge 3+ points** | FPI 55.6% (855 picks), Adjusted points 55.3% (1,277 picks), Market-anchored **59.5% (168 picks)**. |
| **Line movement** | After the open, lines moved toward the model's picks 60–67% of the time, and 89% of the time for Market-anchored with a 3+ point edge. |

**What this means:**

- **The Vegas closing line is more accurate than any of these sources.** Betting near kickoff shows no edge.
- **Any edge comes from betting early, right after opening lines are posted, and only on large disagreements.** Lines kept moving toward the picks, which is the most encouraging sign.
- **It isn't proven.** Even the best result is about two standard errors above break-even, and some sportsbooks post opening lines before the ESPN ratings used here were updated. Opening lines also have low betting limits.
- **Adjusted points adds little on top of FPI.** Market-anchored gives it about a tenth of the weight.

---

## The forward test

The backtest replays past seasons, and some of its biases can't be fully ruled out (see the caveats above). The forward test can't have those biases: it records picks **before** the games are played.

Every two hours, the GitHub job runs `record.py`, which:

1. **Records lines:** saves each game's line whenever it changes, with the time, to `data/live/line_history.csv`. This builds a record of how lines move through the week.
2. **Logs picks:** the first time a game has a line, saves every projection's pick at that line to `data/live/picks.csv`. Those columns are never changed afterward. Since the job checks every two hours, picks are logged within about two hours of the opening line.
3. **Grades picks:** after kickoff, fills in the closing line, the result at the logged line, the result at the closing line and the CLV (how far the line moved toward the pick).
4. **Commits** both files to the repository. Git history then shows exactly when each pick was recorded, which proves it was made before the game.

The website's **Track record** tab shows the results by projection and edge size, with a link to that history. Watch two numbers: the record at the logged line, and how often the line moved our way. A few hundred strong-edge picks are needed before the record means much.

The log started on October 21, 2026, partway through week 8, so some of that week's games were logged after their lines had already moved. Everything from week 9 on is logged close to the open.

---

## How the model works

**Adjusted points ratings.** Every completed game this season is fitted at once: a team's points scored = league average + its offense rating + its opponent's defense rating ± home field. That way 40 points against a strong defense counts for more than 40 against a weak one. Teams with few games are pulled toward average (ridge regression), and all FCS opponents share one rating. `ppg` and `papg` are those ratings on the normal points scale.

**Projected margin**, by source:

```
Adjusted points:  (home.ppg + away.papg) - (away.ppg + home.papg) + HFA
ESPN FPI:         home.fpi - away.fpi + HFA
Blend:            average of the two
Market-anchored:  const + w_line x (-home line) + w_fpi x FPI margin + w_pts x points margin
```

There's no home-field advantage (HFA) at neutral sites. Market-anchored starts from the line you'd be betting: the current line, or the pregame line once a game has started. In the backtest it started from the opening line and was graded against that same line. Starting from an older line than the one being bet would count the line's own movement as edge. The weights are learned by regression on past seasons. Learned from 2023–2025, they come out to about 0.57 × line, 0.39 × FPI and 0.12 × adjusted points.

**Pregame cover chance.** The final margin is treated as a bell curve around the projection, with spread equal to the **Margin std dev** setting (sigma):

```
P(home covers) = NormalCDF( (projected margin + home line) / sigma )
edge           = | projected margin + home line |
```

**Live cover chance.** During a game, the expected final margin is the current margin plus the share of the projection still to be played, and the uncertainty shrinks as time runs out:

```
expected final margin = current margin + projected margin x (time left / 60 min)
live sigma            = sigma x sqrt(time left / 60 min)
```

Finished games show 100% or 0% (50% for a push). Overtime counts as about two minutes left.

**Avoiding look-ahead in the backtest.** Each week's ratings use only earlier games. FPI comes from the newest ESPN snapshot taken before that week's first game, and weeks with no snapshot from the previous 10 days are skipped, because ESPN overwrote some old snapshots with later data.

---

## Publishing the website

The website is the `site/` folder, published free by GitHub Pages. The job in `.github/workflows/site.yml` runs every two hours, whenever the site's code changes on `main`, and when you click **Run workflow** on the repo's **Actions** tab. Each run records lines and picks ([The forward test](#the-forward-test)) and commits them, then runs `build_site.py` to refresh `site/data/` (ratings, Market-anchored weights, recommended std dev and track record), and publishes the site.

Because the job commits to `main` every two hours, your copy falls behind quickly. Run `git pull` before you change anything, or your push will be rejected.

**One-time setup** (repo owner only):

1. On GitHub, open the repo's **Settings → Pages**, and under **Build and deployment → Source**, choose **GitHub Actions**.
2. Optional, to keep the multi-season track record current: in **Settings → Secrets and variables → Actions**, add a repository secret named `CFBD_API_KEY` containing your CollegeFootballData key. Without it, the job still refreshes the ratings every day and leaves the track record as it was last built.

To preview the website on your own computer, run `python build_site.py` once, then `python -m http.server 8600 --directory site`, and open **http://localhost:8600**.

---

## Files

```
fourth-and-value/
├── app.py                    # the computer app: screens and buttons (Streamlit)
├── sources.py                # data downloads from ESPN and CollegeFootballData
├── model.py                  # the math: ratings, projections, cover chances, backtest scoring
├── build_site.py             # builds the website's data files
├── record.py                 # forward test: records lines and picks, grades them
├── site/                     # the website: index.html, style.css, app.js, game.js (game details), data/
├── .github/workflows/site.yml # nightly job that refreshes and publishes the website
├── requirements.txt          # Python libraries to install
├── .streamlit/secrets.toml   # your CollegeFootballData key (you create it; never uploaded)
└── data/
    ├── team_ratings.csv      # team ratings (Auto-fill or edit by hand)
    ├── lines.csv             # pregame lines the dashboard has saved
    ├── closing_lines.csv     # this season's opening and closing lines (backtest)
    ├── anchor_weights.json   # Market-anchored weights (saved by the backtest)
    ├── live/                 # forward test: line_history.csv and picks.csv (written by the GitHub job)
    ├── history.csv           # your logged picks (created when you log; kept private)
    ├── bets.csv              # your bets (created when you save; kept private)
    └── cfbd/                 # past seasons' data (downloaded; kept private)
```

"Kept private" means the file is listed in `.gitignore`, so git won't upload it to GitHub.

---

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `streamlit: command not found` or `No module named streamlit` | You're outside the environment. Run the `source venv/bin/activate` (Mac) or `venv\Scripts\activate` (Windows) line from [step 4](#4-start-the-dashboard-every-time) first. |
| `python3: command not found` (Mac) or `'py' is not recognized` (Windows) | Python isn't installed, or on Windows "Add python.exe to PATH" wasn't ticked. Reinstall it from [python.org](https://www.python.org/downloads/). |
| Browser didn't open | Go to **http://localhost:8501** yourself. |
| "Couldn't load scores" | Check your internet connection and click **Refresh now**. ESPN's feed sometimes has short outages. |
| No games listed | Check the **Date** in the sidebar. |
| A game has no pick | Read its **Note**. Usually a team name doesn't match the ratings table (run **Auto-fill**) or there's no line yet. |
| Market-anchored shows no picks | `data/anchor_weights.json` is missing. Run the season backtest with at least one finished season from 2023 on. |
| "Past seasons need a free API key" | Create `.streamlit/secrets.toml` as described in [Testing on past seasons](#testing-on-past-seasons), then click **Refresh now**. |
| Website shows old ratings | Check the repo's **Actions** tab for a failed "Update and publish site" run, then click **Run workflow** to retry. |
| Website picks or bets disappeared | They live in that browser's storage. Private/incognito windows and clearing site data erase them; download bets as CSV to keep a copy. |
| "CollegeFootballData rejected the API key" | Check that the key in `secrets.toml` is complete, with no extra spaces, and inside the quotes. |

---

## Limitations

- **Scores and ratings only.** The model doesn't know about injuries, weather, suspensions or motivation.
- **Unofficial data.** ESPN's feeds aren't official and could change or go down without notice.
- **Lines differ by sportsbook.** Lines come from one book per game (DraftKings when available), so yours may differ.
- **Small samples mislead.** A few weeks of results can look great or terrible by luck alone. Judge by hundreds of picks and by line movement.
- **No guarantees.** A high cover percentage is still not a sure thing.
