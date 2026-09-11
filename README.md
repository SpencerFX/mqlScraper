# mqlScraper

Crawl the public [mql5.com](https://www.mql5.com/en/signals) trading-signals
directories - both [MT4](https://www.mql5.com/en/signals/mt4) and
[MT5](https://www.mql5.com/en/signals/mt5) - and record each signal's monitored
trading behaviour into CSVs and a standalone kdb+ HDB. Every row is tagged with
its `mtVersion`.

Sibling of [`fxBookScraper`](../fxBookScraper) - same pipeline (collector ->
parser -> normalizer -> CSV -> `q/load.q` -> partitioned HDB), same resumable
crawl state, same raw-archive-for-replay. Only the transport differs: mql5 serves
the whole signal page - headline stats, the statistics grid, and every chart
series - to a plain HTTP GET, so this uses a throttled `requests.Session` rather
than a real browser.

Captured per signal:

| output | grain | contents |
|---|---|---|
| `data/csv/signals.csv`   | one row per signal          | id, mt version, name, author login/name, account type, url, first/last seen |
| `data/csv/snapshots.csv` | one row per signal per run  | ~55 headline + statistics fields: growth, profit, equity, balance, deposits/withdrawals, subscribers & funds, weeks, trades, win %, long/short split, gross P/L (money & pips), profit factor, expected payoff, sharpe, recovery factor, consecutive win/loss runs, activity, deposit load, algo-trading %, monthly growth, annual forecast, the four drawdown figures, leverage, account server |
| `data/csv/growth.csv`    | one row per signal per day  | cumulative growth % (weekly `W1` points from the avatar chart) |
| `data/csv/equity.csv`    | one row per signal per event| balance and equity at each account event (the balance/equity chart feed) |
| `data/csv/monthly.csv`   | one row per signal per month| monthly return % and the year's total % (the growth chart's year/month grid) |
| `data/csv/symbols.csv`   | one row per signal per symbol per run | deals, buy trades, sell trades (the trade-distribution table) |

Per-trade history is behind an mql5 login and is **out of scope** - the growth,
equity, monthly and symbol tables are what mql5 exposes publicly about how a
signal actually traded.

## Setup

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
```

## Run

```powershell
.\.venv\Scripts\python main.py --discovery list --max-pages 3   # smoke test
.\.venv\Scripts\python main.py                                  # EVERYTHING: MT4 + MT5, every facet (resumable)
.\.venv\Scripts\python main.py --load                           # then build data/hdb
.\.venv\Scripts\python main.py --mt 4 --discovery list          # just MT4's plain 40-page listing
```

Flags: `--signals 2306053,2327790` (skip discovery), `--mt {4,5,both}`,
`--discovery {full,list}`, `--limit N`, `--force` (ignore `min_recheck_hours`),
`--rediscover` (re-run discovery instead of resuming the pending queue),
`--reset-progress`, `--probe URL ...` (dump raw HTML to `data/probe/`), `--debug`.

### Discovery depth

mql5 **hard-caps every listing at 40 pages (MT4) / 55 pages (MT5)** - the plain
`/list` only ever shows its top ~1,900 / ~2,600 signals. `--discovery full` (the
default) works around that by sweeping the *same* directory through all 15 column
re-sorts (`?orderby=gain|balance|subscribers|weeks|trades|pf|drawdown|...`) plus
the 5 category tabs (`/forex`, `/gold`, `/crypto`, `/trusted`, `/live`), and
unions the ids. Each is a different 40-page window into the population, so the
union is far larger than any single view.

This is a **big** crawl: ~20 facets x up to 40 pages x 2 platforms is ~1,500
list-page fetches for discovery, then one page fetch per unique signal (tens of
thousands). At the default 1.5 s throttle a full run is measured in hours. It is
fully resumable and checkpointed after every signal - stop and re-run `main.py`
with the same args to continue. Per-signal history (growth / equity / monthly)
already reaches back to each account's inception, so one pass captures the whole
history of every signal it discovers.

Resume state: `data/state/crawl_progress.json` (pending / done signal ids),
`data/state/seen_signals.json` (last-collected time per signal).

Config: `config.yaml` - `mt_version` (`4` / `5` / `both`), `discovery`
(`full` / `list`), request delay, page caps, output paths, q exe.

## kdb+

`q/load.q` rebuilds an on-disk, date-partitioned HDB under `data/hdb/` from the
six CSVs. Idempotent - every touched partition is rewritten from the CSV each run.

```powershell
C:\q\w64\q.exe q\load.q -hdb data\hdb -csv data\csv
```

Tables: `sig` (registry splay), `snap` (partitioned by snapshot date), `growth`
(by date), `equity` (by event date), `monthly` (splay), `symdist` (splay - not
`sym`, which is the HDB's own enumeration file). Explore:

```q
q)\l q/query.q            / self-loads data/hdb
q).mq.leaderboard 20
q).mq.growth 2306053      / weekly growth curve for a signal
q).mq.curve 2306053       / balance / equity curve
q).mq.monthly 2306053     / month-by-month returns
q).mq.bySymbol 2306053    / latest per-symbol trade distribution
q).mq.byServer[]          / aggregate the latest snapshots by account server
```

`q/ingest.q` has in-memory upsert helpers for tests / a future live feed.

## Layout

```
collector/  http.py      (throttled requests.Session + retries)
            directory.py (facet sweep: /list + ?orderby=* + category tabs, MT4 & MT5)
            signal.py    (fetch one /en/signals/<id> page)
parser/     directory.py (the `div.row.signal` list rows)
            stats.py     (mql5 number/duration/timestamp coercion + label maps)
            signal.py    (stats blocks + the inline chart-bootstrap arrays + distribution)
normalizer/ normalize.py (typed records; column order == q schema)
storage/    csv_store.py, state.py, raw.py
q/          schema.q, load.q, query.q, ingest.q
```

## Limits

- Even `--discovery full` only reaches signals that appear in *some* mql5 listing
  (active / ranked / categorised). Signals that mql5 has fully de-listed are not
  linked anywhere public and cannot be discovered by crawling; feed their ids to
  `--signals` if you have them from elsewhere.
- Directory pagination is by path (`/list/pageN`, `/forex/pageN`); each view is
  capped at 40 (MT4) / 55 (MT5) pages, which is the reason for the facet sweep.
- `growth.csv` / `monthly.csv` cover the **account's** lifetime, which usually
  predates the day it became a monitored signal (`weeks` and `startedAt` on the
  snapshot mark the monitoring start).
- Monthly figures are mql5's own growth-chart percentages (verified against the
  chart's `total`); they compound differently from a simple sum of daily growth.
- Per-trade history, open positions, live streaming and scheduled runs are out of
  scope.
