/ ============================================================
/ mqlScraper - kdb+ schema
/ Empty typed templates. Column order matches the CSV headers
/ written by normalizer/normalize.py (SIGNAL_FIELDS / SNAPSHOT_FIELDS
/ / GROWTH_FIELDS / EQUITY_FIELDS / MONTHLY_FIELDS / SYMBOL_FIELDS).
/ One-line literals on purpose: multi-line / indented top-level
/ table literals do not load reliably.
/ ============================================================

/ signal registry (splayed, non-partitioned; upserted each run)
sig:([] signalId:`long$(); mtVersion:`long$(); name:`$(); authorLogin:`$(); authorName:`$(); accountType:`$(); url:`$(); firstSeen:`timestamp$(); lastSeen:`timestamp$(); broker:`$(); server:`$())

/ headline + statistics snapshot - one row per signal per crawl (partition: date of ts)
snap:([] ts:`timestamp$(); signalId:`long$(); name:`$(); authorLogin:`$(); growthPct:`float$(); profitUsd:`float$(); equityUsd:`float$(); balanceUsd:`float$(); initialDepositUsd:`float$(); depositsUsd:`float$(); withdrawalsUsd:`float$(); currency:`$(); subscribers:`long$(); subscriberFundsUsd:`float$(); weeks:`long$(); tradingDays:`long$(); tradingDaysPct:`float$(); tradesPerWeek:`float$(); avgHoldingSec:`long$(); latestTradeText:`$(); startedAt:`timestamp$(); trades:`long$(); profitTrades:`long$(); lossTrades:`long$(); winRatePct:`float$(); longTrades:`long$(); longPct:`float$(); shortTrades:`long$(); shortPct:`float$(); bestTradeUsd:`float$(); worstTradeUsd:`float$(); grossProfitUsd:`float$(); grossProfitPips:`float$(); grossLossUsd:`float$(); grossLossPips:`float$(); profitFactor:`float$(); expectedPayoffUsd:`float$(); avgProfitUsd:`float$(); avgLossUsd:`float$(); sharpeRatio:`float$(); recoveryFactor:`float$(); maxConsecWins:`long$(); maxConsecWinsUsd:`float$(); maxConsecLosses:`long$(); maxConsecLossesUsd:`float$(); tradingActivityPct:`float$(); maxDepositLoadPct:`float$(); algoTradingPct:`float$(); monthlyGrowthPct:`float$(); annualForecastPct:`float$(); drawdownAbsUsd:`float$(); drawdownMaxUsd:`float$(); drawdownMaxPct:`float$(); drawdownBalancePct:`float$(); drawdownEquityPct:`float$(); leverage:`long$(); server:`$())

/ weekly growth curve (partition: date)
growth:([] signalId:`long$(); date:`date$(); growthPct:`float$())

/ balance / equity curve, one point per account event (partition: date of ts)
equity:([] signalId:`long$(); ts:`timestamp$(); balance:`float$(); equity:`float$())

/ monthly returns grid (splay; small)
monthly:([] signalId:`long$(); year:`long$(); month:`long$(); returnPct:`float$(); yearlyPct:`float$())

/ per-symbol trade distribution, snapshotted each run (splay; carries ts)
symdist:([] ts:`timestamp$(); signalId:`long$(); symbol:`$(); deals:`long$(); buyTrades:`long$(); sellTrades:`long$())

/ per-trade history from the logged-in Trading-history tab (partition: date of closeTime, else openTime)
trade:([] tradeKey:`$(); signalId:`long$(); kind:`$(); action:`$(); orderType:`$(); symbol:`$(); openTime:`timestamp$(); closeTime:`timestamp$(); openPrice:`float$(); closePrice:`float$(); sl:`float$(); tp:`float$(); volume:`float$(); commission:`float$(); swap:`float$(); profit:`float$(); cancelled:`long$(); comment:`$(); collectedAt:`timestamp$())
