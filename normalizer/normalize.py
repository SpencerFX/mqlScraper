"""Turn parsed signal data into flat, typed records for the CSV writers.

Column order here is authoritative - q/load.q and q/schema.q mirror these lists.
"""

import hashlib
from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc).isoformat()


def _sym(v):
    """Scrub a value bound for a kdb+ symbol column: the q CSV loader is not
    RFC-4180 aware, so drop commas / quotes / newlines from free text."""
    if v is None:
        return None
    return str(v).replace(",", " ").replace('"', "").replace("\r", " ") \
        .replace("\n", " ").strip() or None


SIGNAL_FIELDS = [
    "signalId", "mtVersion", "name", "authorLogin", "authorName", "accountType",
    "url", "firstSeen", "lastSeen", "broker", "server",
]

SNAPSHOT_FIELDS = [
    "ts", "signalId", "name", "authorLogin",
    "growthPct", "profitUsd", "equityUsd", "balanceUsd", "initialDepositUsd",
    "depositsUsd", "withdrawalsUsd", "currency",
    "subscribers", "subscriberFundsUsd", "weeks", "tradingDays", "tradingDaysPct",
    "tradesPerWeek", "avgHoldingSec", "latestTradeText", "startedAt",
    "trades", "profitTrades", "lossTrades", "winRatePct",
    "longTrades", "longPct", "shortTrades", "shortPct",
    "bestTradeUsd", "worstTradeUsd", "grossProfitUsd", "grossProfitPips",
    "grossLossUsd", "grossLossPips",
    "profitFactor", "expectedPayoffUsd", "avgProfitUsd", "avgLossUsd",
    "sharpeRatio", "recoveryFactor",
    "maxConsecWins", "maxConsecWinsUsd", "maxConsecLosses", "maxConsecLossesUsd",
    "tradingActivityPct", "maxDepositLoadPct", "algoTradingPct",
    "monthlyGrowthPct", "annualForecastPct",
    "drawdownAbsUsd", "drawdownMaxUsd", "drawdownMaxPct",
    "drawdownBalancePct", "drawdownEquityPct",
    "leverage", "server",
]

GROWTH_FIELDS = ["signalId", "date", "growthPct"]
EQUITY_FIELDS = ["signalId", "ts", "balance", "equity"]
MONTHLY_FIELDS = ["signalId", "year", "month", "returnPct", "yearlyPct"]
SYMBOL_FIELDS = ["ts", "signalId", "symbol", "deals", "buyTrades", "sellTrades"]

TRADE_FIELDS = [
    "tradeKey", "signalId", "kind", "action", "orderType", "symbol",
    "openTime", "closeTime", "openPrice", "closePrice", "sl", "tp", "volume",
    "commission", "swap", "profit", "cancelled", "comment", "collectedAt",
]


def normalize_signal_registry(signal, ident=None, now=None):
    now = now or _utcnow()
    ident = ident or {}
    return {
        "signalId": signal["signal_id"],
        "mtVersion": signal.get("mt_version") or ident.get("mtVersion"),
        "name": _sym(ident.get("name") or signal.get("name")) or str(signal["signal_id"]),
        "authorLogin": _sym(ident.get("authorLogin")),
        "authorName": _sym(ident.get("authorName") or signal.get("author_name")),
        "accountType": _sym(ident.get("accountType") or signal.get("account_type")),
        "url": signal["url"],
        "firstSeen": now,
        "lastSeen": now,
        "broker": _sym(ident.get("broker")),
        "server": _sym(ident.get("server")),
    }


def normalize_snapshot(signal, parsed, ts=None):
    ts = ts or _utcnow()
    stats = parsed.get("stats", {}) or {}
    ident = parsed.get("identity", {}) or {}
    row = {f: None for f in SNAPSHOT_FIELDS}
    row.update({k: v for k, v in stats.items() if k in row})
    for k in ("currency", "latestTradeText", "server"):
        row[k] = _sym(row.get(k))
    row["ts"] = ts
    row["signalId"] = signal["signal_id"]
    row["name"] = _sym(ident.get("name") or signal.get("name"))
    row["authorLogin"] = _sym(ident.get("authorLogin"))
    return row


def normalize_growth(signal, parsed):
    out = []
    for d in parsed.get("growth", []) or []:
        if not d.get("date"):
            continue
        out.append({"signalId": signal["signal_id"], "date": d["date"],
                    "growthPct": d.get("growthPct")})
    return out


def normalize_equity(signal, parsed):
    out = []
    for d in parsed.get("equity", []) or []:
        if not d.get("ts"):
            continue
        out.append({"signalId": signal["signal_id"], "ts": d["ts"],
                    "balance": d.get("balance"), "equity": d.get("equity")})
    return out


def normalize_monthly(signal, parsed):
    out = []
    for d in parsed.get("monthly", []) or []:
        out.append({"signalId": signal["signal_id"], "year": d.get("year"),
                    "month": d.get("month"), "returnPct": d.get("returnPct"),
                    "yearlyPct": d.get("yearlyPct")})
    return out


def normalize_symbols(signal, parsed, ts=None):
    ts = ts or _utcnow()
    out = []
    for d in parsed.get("symbols", []) or []:
        if not d.get("symbol"):
            continue
        out.append({"ts": ts, "signalId": signal["signal_id"], "symbol": _sym(d["symbol"]),
                    "deals": d.get("deals"), "buyTrades": d.get("buyTrades"),
                    "sellTrades": d.get("sellTrades")})
    return out


def _trade_key(sid, r):
    parts = [str(sid), r.get("kind") or "", r.get("openTime") or "",
             r.get("closeTime") or "", r.get("symbol") or "",
             str(r.get("type") or ""), str(r.get("openPrice") or ""),
             str(r.get("closePrice") or ""), str(r.get("volume") or ""),
             str(r.get("profit") or ""), str(r.get("comment") or "")]
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()


def normalize_trades(signal_id, rows, collected_at=None):
    collected_at = collected_at or _utcnow()
    out = []
    for r in rows or []:
        out.append({
            "tradeKey": _trade_key(signal_id, r),
            "signalId": int(signal_id),
            "kind": r.get("kind"),
            "action": r.get("action"),
            "orderType": _sym(r.get("type")),
            "symbol": _sym(r.get("symbol")),
            "openTime": r.get("openTime"),
            "closeTime": r.get("closeTime"),
            "openPrice": r.get("openPrice"),
            "closePrice": r.get("closePrice"),
            "sl": r.get("sl"),
            "tp": r.get("tp"),
            "volume": r.get("volume"),
            "commission": r.get("commission"),
            "swap": r.get("swap"),
            "profit": r.get("profit"),
            "cancelled": 1 if r.get("cancelled") else 0,
            "comment": _sym(r.get("comment")),
            "collectedAt": collected_at,
        })
    return out
