# Saarthi: NSE Trade Cockpit

A **paper-only** trading cockpit for the NSE. It runs two open-source skill packs,
[nse-trader-skill](https://github.com/ogmanojdev/nse-trader-skill) and
[claude-trading-skills-india](https://github.com/Shubhamkumartrichy/claude-trading-skills-india),
without modifying them. Every number they produce is kept in an append-only evidence ledger, so
each future trade idea can show exactly why it was made.

> **Saarthi never places a real order.** It has no broker code and no broker dependencies, and the
> only order gateway is a simulated exchange. `tests/test_no_broker.py` enforces this.

**Status: all seven phases built.** The full design is in [docs/IMPLEMENTATION_PLAN.md](docs/IMPLEMENTATION_PLAN.md).

## Run it

```bash
make setup     # submodules, Python and web dependencies
make run       # builds the UI and serves the whole app at http://127.0.0.1:8000
make test      # both upstream suites + Saarthi's tests + the UI build
make docker    # or: docker compose up --build  (same app on :8000, data in a volume)
```

For development, run `make api` and `make web` and open http://localhost:5173 (hot reload).

## Phase 7: polish

- **Learn:** a glossary of 22 terms in plain words. Each term links to the repository skill that explains it
  (pinned to the vendored commit) and to an example from your own data. Also covers how Saarthi decides,
  what it is not, and credits.
- **Onboarding:** a three-step first-run tour that ends with a not-advice acknowledgement. You can reopen it from Learn.
- **Simple / Pro:** Simple hides the plan variants, the score maths and the raw command details in the evidence
  drawer. Pro shows all of them.
- **हिं / EN:** Hindi labels for navigation, the header and key controls.
- **Optional Claude narrator** (`SAARTHI_NARRATOR=1`, uses your Anthropic credentials): explains an idea's
  recorded evidence in plain English using `claude-opus-5-5` through the official SDK, with server-side refusal
  fallbacks on. It decides nothing and is off by default.
- **One process, one port:** the API serves the built UI. There is a `Dockerfile` and a `docker-compose.yml`
  (scheduler on, narrator off, bound to 127.0.0.1).

## Phase 6: swing mode

- **Swing scan:** after the close, the India repo's breakout planner scans daily charts for Stage-2 stocks with
  tight bases. For each candidate it records:
  - the plan: GTT trigger, chase limit, stop, 2R/3R targets, size and the planner's order text;
  - its own backtest of breakouts on that stock, after costs;
  - event risk inside the holding window;
  - a climax check and the market regime.
- **Point-in-time decisions:** the planner has no as-of flag, so each daily CSV is cut at the decision date.
  The demo decides on the evening of Fri 18 Sep 2026 using the repository's fixtures.
- **Daily GTT/CNC engine** (`backend/sim/daily.py`): a gap past the chase limit goes unfilled; a DAY stop on
  the buy day, then OCO stop/target; time exit after the holding period; delivery costs including the DP charge.
  Covered by property tests.
- **Paper GTT** from any swing idea, shown on the Paper Desk with a daily chart.

## Phase 5: replay simulator

- **Replay** a past session bar by bar with play/pause (1×, 4×, 15×), +5 min, +30 min, next event and jump to close.
  "Surprise me" hides the date and the stock name until the close.
- **Nothing ahead of the clock:** only completed bars, ideas whose decision moment has passed, and fills
  simulated up to the clock reach the screen. A test advances the clock at random and checks this throughout.
- **Trade inside the replay:** use an idea's plan or your own ticket. Replay trades never touch your account.
- **Scorecard at the close:** you, every TAKE as planned, every idea as planned, and the perfect-hindsight best
  move after costs.

## Phase 4: history and performance

- **Batch replay** (`POST /api/replay/batch`, History → Replay) re-runs past sessions exactly as the scheduler would:
  1. The pre-market brief runs as of 08:30.
  2. Each breakout is decided when its confirming bar closes. Every tool is told that moment, so the Time Machine only
     draws on earlier sessions.
  3. Every idea is then ghost-traded as planned.

  The demo replays 40 sessions of the synthetic DEMO instrument in about 35 s.
- **Three books:** your paper trades; every TAKE as planned; every idea as planned. Ghosts are hindsight, never seen by
  a decision, and never part of your account.
- **History:** a calendar coloured by day P&L, and a day timeline showing the brief, decisions, your fills and ghost
  outcomes.
- **Performance:**
  - Net, expectancy, win rate, profit factor, drawdown and costs.
  - The equity curve and the R distribution.
  - Breakdowns by entry time, weekday, exit, regime, verdict and plan adherence.
  - Calibration: the Time Machine's predicted P(target first) against what happened. It is judged on a no-trail twin
    of each ghost (the model's own rules), with 95% ranges and a Brier score compared with always guessing the average.
  - **What each check saved or cost**: the ghost P&L of the ideas each check stopped.
- Charts use the dataviz method. P&L is a polarity job, so it uses a diverging blue/red pair validated in both modes
  against the app's surfaces. Every chart has a hover tooltip and a table view.

## Phase 3: paper trading

- **Fill engine** ([backend/sim/engine.py](backend/sim/engine.py)): pure and deterministic. Each paper trade is
  re-simulated from its order over the completed 5-minute bars, so a live trade and its replay always agree.
  - **Order types:** limit, buy-stop (SL-M) or market entry, plus a bracket stop and target.
  - **Optional breakeven trail** at +1R.
  - **Pessimistic where a bar hides the order of events:** gaps fill at the open; limits fill only when price
    trades through by a tick; if stop and target are both touched in one bar, the stop wins; slippage is
    max(1 tick, 3 bps).
  - **Session rules:** entries expire at 14:30; intraday (MIS) positions square off at the 15:15 bar's open.
  - **Costs** come from nse-trader-skill's `charges.round_trip`.
- **Property tests** ([tests/test_sim_engine.py](tests/test_sim_engine.py)) run 1,200 random sessions and check:
  - No fill falls outside its bar, and costs match `charges.round_trip` exactly.
  - Every position is flat by 15:15, and no entry happens after the cutoff.
  - Runs are deterministic, and a partial (live) run never contradicts the final one.
- **Account rules:**
  - ₹2,00,000 paper capital, a 2% daily loss cap and 4 trades a day (nse-trader-skill's config defaults).
  - Orders that would breach the cap, sit off the tick grid, arrive after 14:30 or land on a closed market are
    rejected with a plain-language reason.
- **Ghost trades** (`POST /api/paper/ghosts`): after a session, every idea (TAKE, WATCH or SKIP) is traded as
  planned in a separate book. Phase 4 uses these to show what each gate saved or cost.
- **Paper Desk:** account bar, a ticket prefilled from an idea (with live risk and cost preview), a trades table,
  and per-trade chart, timeline and costs. The idea page's "Paper trade" button opens it.

## Phase 2: trade ideas

After each completed 5-minute bar in the entry window (09:35–14:30 IST), the scheduler runs
nse-trader-skill's opening-range scan. Each breakout becomes an idea in the append-only ledger:

1. **Gates G0–G6**: session and entry cutoff, market regime, event risk, ASM/price band, results
   day, a 5-minute close above the opening-range high, and a buying-climax check.
2. **Plan**:
   - Entry is the breakout bar's close.
   - Stop is the opening-range midpoint or low, and target is 1.5R, 2R or 3R. All six combinations are tested.
   - Prices are rounded to NSE ticks using the India repo's slab table.
   - Size comes from `risk.py size`.
3. **Odds**: the Time Machine runs each variant 2,000 times, then the chosen plan 10,000 times,
   after costs. Costs are calculated by both repos and cross-checked.
4. **When**: the same plan simulated at every 15-minute entry time, giving the best entry
   window. The exit ladder comes from `risk.py trail`.
5. **Verdict**: TAKE, WATCH or SKIP under a written rule shown on screen. The score only ranks ideas.

Live intraday charts are fetched once per symbol through the repo's own fetcher and saved
under `data/bars/<day>/`. Every tool reads them with `--offline`, which keeps each decision
reproducible and avoids Yahoo's rate limit.

The demo session is Mon 9 Nov 2026. DEMO is nse-trader-skill's **synthetic** test instrument:
a random walk, so the honest verdict is SKIP.

## Phase 1: the Today screen

```bash
uv run uvicorn backend.api.app:app --host 127.0.0.1 --port 8000   # API
npm --prefix web install && npm --prefix web run dev                # UI on http://localhost:5173
```

- **Demo data:** the real tools running on each repository's own archived NSE data, frozen at the
  pre-market of Wed 11 Nov 2026. Works offline.
- **Live data:** the tools fetch from NSE and Yahoo themselves. The India repo's `--symbol` uses
  `yfinance`. Breadth needs NSE's advance/decline CSV at `data/uploads/breadth_ad.csv`.
- **Scheduler:** `SAARTHI_SCHEDULER=1` runs the evening scan at 18:30 IST and the pre-market brief
  at 08:30 IST, on NSE session days only. The session days come from the nse-trader-skill calendar.
- **Market mood:** taken from the regime tool's label, then stepped down once for weak breadth
  (below 30) and once for a high-impact event on the session day. The rule is shown on screen.
- Every number on screen opens an **evidence drawer** showing the exact command, repo commit,
  point-in-time stamp, input fingerprints and the tool's raw output.

| Endpoint | Purpose |
|---|---|
| `GET /api/today?mode=demo\|live` | Assembled brief: clock, mood, events, watchlist, sectors, breadth, filings, data notes |
| `POST /api/jobs/{evening_scan\|premarket_brief}/run` | Run a job now (`{"mode": "demo"}`) |
| `GET /api/jobs` | Job history |
| `GET /api/session?at=YYYY-MM-DD HH:MM` | NSE clock: phase, holiday, square-off, next session |

## What Phase 0 delivers

| Piece | Where |
|---|---|
| Both repos vendored, pinned and unmodified | `vendor/` (git submodules) |
| Tool registry: 23 tools, with flags, point-in-time support and an offline smoke invocation for each | `backend/skills/registry.yaml` |
| Skill Runner: isolated working directory per run, no shell, JSON capture, rejects paths outside the project, records repo commit and input hashes | `backend/skills/runner.py` |
| Evidence ledger: SQLite in WAL mode, append-only triggers on `tool_runs`, `decisions` and `evidence` | `backend/ledger/db.py` |
| API: list tools, run a tool, read runs, smoke-run everything | `backend/api/app.py` |
| Paper-only guard and the order gateway seam | `backend/sim/gateway.py`, `tests/test_no_broker.py` |
| CI: both upstream suites, then Saarthi's own tests | `.github/workflows/ci.yml` |

## Quick start

```bash
git submodule update --init
uv sync
uv run pytest -q                                            # 92 tests, offline
uv run uvicorn backend.api.app:app --host 127.0.0.1 --port 8000
```

Then open <http://127.0.0.1:8000/docs> for the interactive API.

```bash
curl -s localhost:8000/api/health
curl -s -X POST localhost:8000/api/smoke -H 'content-type: application/json' -d '{}'
curl -s -X POST localhost:8000/api/tools/nse.timemachine.run/run \
     -H 'content-type: application/json' -d '{"use_smoke_args": true}'
curl -s -X POST localhost:8000/api/tools/india.risk.size/run -H 'content-type: application/json' \
     -d '{"args": ["--capital","200000","--risk-pct","0.5","--entry","912.35","--stop","905.10"]}'
```

### Running a tool as of an earlier moment

Tools that support it take an `as_of` value. The runner turns it into the tool's own flag:
`--now` for the NSE tools, and `--as-of` or `--today` for the India tools.

```bash
curl -s -X POST localhost:8000/api/tools/nse.scan.daily/run -H 'content-type: application/json' \
     -d '{"args": ["--offline","{nse_fx}/nse-scanner","--min-turnover","0"], "as_of": "2026-11-09 18:30"}'
```

`{nse_fx}` and `{india_fx}` expand to each repo's test-fixture folder, which is handy for working offline.

### Live data

Leave out `--offline` and the tools fetch from NSE and Yahoo themselves. Saarthi adds no data
sources of its own. The India tools' `--symbol` option needs `uv pip install yfinance`, as that
repo documents.

## Upgrading a vendored repo

1. `git -C vendor/<repo> fetch && git -C vendor/<repo> checkout <new-sha>`
2. `uv run pytest -q`. The registry tests catch renamed scripts, and the smoke test catches changed command-line options or output.
3. Review the upstream changelog before committing the new pinned commit.

## Credits and disclaimer

See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). This is educational software for simulated
trading only, not investment advice. Most intraday traders lose money.
