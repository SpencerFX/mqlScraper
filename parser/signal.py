"""Parse one mql5 signal page (`/en/signals/<id>`).

Sources, all in the one public HTML document:
  * identity   -> <h1 class="s-line-card__title">, the author link, the account badge
  * headline   -> the two `.s-list-info` blocks
  * statistics -> the `.s-data-columns` grid (rendered in #tab_content_stats)
  * top card   -> broker/server, leverage
  * growth     -> window.renderMiniChart(..., "W1", [epoch, growth%, ...])   (weekly)
  * balance/eq -> var equityData = [epoch, balance, equity, ...]             (per event)
  * monthly    -> window.growthChart(..., {table:{years:[{year,yearly,months:{}}]}})
  * symbols    -> table.signals-chart-dist  (deals / buy / sell per symbol)
"""

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from parser.stats import (
    clean_text, number, percent, money, compact, integer,
    parse_pct_pair, parse_amount_paren, parse_usd_pips, parse_leverage,
    parse_mql_ts, parse_duration_seconds,
)


# --------------------------------------------------------------------- identity

def _broker_of(server):
    """Trade-server tag -> brokerage name: the segment before the first '-'
    ("HFMarketsGlobal-Live1" -> "HFMarketsGlobal", "XMGlobal-Real 44" -> "XMGlobal")."""
    if not server:
        return None
    head = server.split("-", 1)[0].strip()
    return head or None


def parse_identity(html):
    out = {"name": None, "authorLogin": None, "authorName": None,
           "accountType": None, "mtVersion": None, "server": None, "broker": None}

    m = re.search(r'/en/signals/mt([45])["/?]', html) \
        or re.search(r'source=Site\+Signals\+MT([45])', html)
    if m:
        out["mtVersion"] = int(m.group(1))

    m = re.search(r'<h1[^>]*class="[^"]*s-line-card__title[^"]*"[^>]*>(.*?)</h1>',
                  html, re.S)
    if m:
        out["name"] = clean_text(re.sub(r"<[^>]+>", " ", m.group(1)))

    block = ""
    b = re.search(r's-line-card__author(.*?)</div>\s*</div>', html, re.S)
    if b:
        block = b.group(1)
    m = re.search(r'/en/users/([\w.\-]+?)(?:/seller)?"[^>]*>([^<]+)<', block)
    if not m:
        m = re.search(r'/en/users/([\w.\-]+?)(?:/seller)?"[^>]*>([^<]+)<', html)
    if m:
        out["authorLogin"] = m.group(1)
        out["authorName"] = clean_text(m.group(2))
    if not out["authorLogin"]:
        a = re.search(r'/en/signals/author/([\w.\-]+)', html)
        if a:
            out["authorLogin"] = a.group(1)

    m = re.search(r'icons-ux_shield"[^>]*title="([^"]*Account)"', html) \
        or re.search(r'ico_state\s+(real|demo)\b', html) \
        or re.search(r'>\s*(Real|Demo) Account\s*<', html)
    if m:
        tok = m.group(1).lower()
        out["accountType"] = "Demo" if "demo" in tok else "Real"

    # top card: the signal account's own trade server (needs a logged-in fetch;
    # the anonymous page omits it). "<broker>-<Live|Real|Demo|...>" - the broker
    # company is the leading segment.
    m = re.search(r's-plain-card__broker.*?name="substring_filter"\s+value="([^"]+)"',
                  html, re.S) \
        or re.search(r'name="substring_filter"\s+value="([^"]+)"', html)
    if m:
        out["server"] = clean_text(m.group(1))
        out["broker"] = _broker_of(out["server"])
    return out


# --------------------------------------------------------------------- headline
# label (lower-cased, ':' stripped) -> handler(value_text, out_dict)

def _set(field, coerce):
    return lambda v, o: o.__setitem__(field, coerce(v))


def _pct_pair(count_field, pct_field):
    def h(v, o):
        c, p = parse_pct_pair(v)
        if c is not None:
            o[count_field] = int(c)
        if p is not None:
            o[pct_field] = p
    return h


def _count_usd(count_field, usd_field):
    def h(v, o):
        c, u = parse_amount_paren(v)
        if c is not None:
            o[count_field] = int(c)
        if u is not None:
            o[usd_field] = u
    return h


def _usd_pct(usd_field, pct_field):
    def h(v, o):
        u, p = parse_amount_paren(v)
        if u is not None:
            o[usd_field] = u
        if p is not None:
            o[pct_field] = p
    return h


def _pct_usd(pct_field, usd_field):
    def h(v, o):
        p, u = parse_amount_paren(v)
        if p is not None:
            o[pct_field] = p
        if u is not None:
            o[usd_field] = u
    return h


def _usd_pips(usd_field, pips_field):
    def h(v, o):
        u, p = parse_usd_pips(v)
        if u is not None:
            o[usd_field] = u
        if p is not None:
            o[pips_field] = p
    return h


S_LIST_INFO = {
    "growth": _set("growthPct", percent),
    "profit": _set("profitUsd", money),
    "equity": _set("equityUsd", money),
    "balance": _set("balanceUsd", money),
    "initial deposit": _set("initialDepositUsd", money),
    "withdrawals": _set("withdrawalsUsd", money),
    "deposits": _set("depositsUsd", money),
    "trading days": _pct_pair("tradingDays", "tradingDaysPct"),
    "latest trade": _set("latestTradeText", clean_text),
    "trades per week": _set("tradesPerWeek", number),
    "avg holding time": _set("avgHoldingSec", parse_duration_seconds),
    "subscribers": _set("subscribers", integer),
    "weeks": _set("weeks", integer),
    "started": _set("startedAt", parse_mql_ts),
}

S_DATA_COLUMNS = {
    "trades": _set("trades", integer),
    "profit trades": _pct_pair("profitTrades", "winRatePct"),
    "loss trades": _pct_pair("lossTrades", "lossRatePct"),
    "best trade": _set("bestTradeUsd", money),
    "worst trade": _set("worstTradeUsd", money),
    "gross profit": _usd_pips("grossProfitUsd", "grossProfitPips"),
    "gross loss": _usd_pips("grossLossUsd", "grossLossPips"),
    "maximum consecutive wins": _count_usd("maxConsecWins", "maxConsecWinsUsd"),
    "maximum consecutive losses": _count_usd("maxConsecLosses", "maxConsecLossesUsd"),
    "maximal consecutive profit": _set("maxConsecProfitUsd", money),
    "maximal consecutive loss": _set("maxConsecLossUsd", money),
    "sharpe ratio": _set("sharpeRatio", number),
    "trading activity": _set("tradingActivityPct", percent),
    "max deposit load": _set("maxDepositLoadPct", percent),
    "recovery factor": _set("recoveryFactor", number),
    "long trades": _pct_pair("longTrades", "longPct"),
    "short trades": _pct_pair("shortTrades", "shortPct"),
    "profit factor": _set("profitFactor", number),
    "expected payoff": _set("expectedPayoffUsd", money),
    "average profit": _set("avgProfitUsd", money),
    "average loss": _set("avgLossUsd", money),
    "monthly growth": _set("monthlyGrowthPct", percent),
    "annual forecast": _set("annualForecastPct", percent),
    "algo trading": _set("algoTradingPct", percent),
    "absolute": _set("drawdownAbsUsd", money),
    "maximal": _usd_pct("drawdownMaxUsd", "drawdownMaxPct"),
    "by balance": _pct_usd("drawdownBalancePct", "drawdownBalanceUsd"),
    "by equity": _pct_usd("drawdownEquityPct", "drawdownEquityUsd"),
}


def _pairs(soup, item_cls, label_cls, value_cls):
    out = []
    for item in soup.find_all("div", class_=lambda c: c and item_cls in c):
        lbl = item.find("div", class_=lambda c: c and label_cls in c)
        val = item.find("div", class_=lambda c: c and value_cls in c)
        if lbl and val:
            out.append((clean_text(lbl.get_text(" ")), clean_text(val.get_text(" "))))
    return out


def parse_stats(html):
    soup = BeautifulSoup(html, "lxml")
    out = {}

    def apply(pairs, table):
        for label, value in pairs:
            if not label or value in (None, "", "-"):
                continue
            key = label.lower().rstrip(":").strip()
            handler = table.get(key)
            if not handler:
                continue
            try:
                handler(value, out)
            except Exception:
                pass

    apply(_pairs(soup, "s-list-info__item", "s-list-info__label", "s-list-info__value"),
          S_LIST_INFO)
    apply(_pairs(soup, "s-data-columns__item", "s-data-columns__label",
                 "s-data-columns__value"), S_DATA_COLUMNS)

    # top card: the signal account's own server tag + leverage.
    # (The `broker` column is left for a real broker-company source; the
    #  slippage section only lists the brokers *subscribers* use.)
    m = re.search(r'name="substring_filter"\s+value="([^"]+)"', html)
    if m:
        out["server"] = clean_text(m.group(1))
    m = re.search(r's-plain-card__leverage"[^>]*>\s*(1\s*:\s*\d+)', html)
    if m:
        out["leverage"] = parse_leverage(m.group(1))

    # subscriber funds ("Total funds of real accounts ...">46K USD)
    m = re.search(r'Total funds of real accounts[^"]*"\s*>\s*([\d.,\s]*\d[KkMmBb]?)\s*USD',
                  html)
    if m:
        out["subscriberFundsUsd"] = compact(m.group(1))

    # clean acc{...} bootstrap as a fallback for a few headline numbers
    a = re.search(r'var\s+acc\s*=\s*\{([^}]*)\}', html)
    if a:
        acc = a.group(1)
        for field, key in (("balanceUsd", "balance"), ("equityUsd", "equity"),
                           ("depositsUsd", "deposits"), ("withdrawalsUsd", "withdrawals")):
            if out.get(field) is None:
                mm = re.search(rf'\b{key}:\s*(-?[0-9.]+)', acc)
                if mm:
                    out[field] = float(mm.group(1))
        mm = re.search(r'currency:\s*"([^"]+)"', acc)
        if mm:
            out["currency"] = mm.group(1)

    if out.get("currency") is None:
        mm = re.search(r'\bUSD\b|\bEUR\b|\bGBP\b|\bJPY\b|\bCHF\b|\bAUD\b|\bCAD\b', html)
        if mm:
            out["currency"] = mm.group(0)
    return out


# --------------------------------------------------------------------- growth

def _floats(csv):
    out = []
    for tok in csv.replace(" ", "").split(","):
        if not tok:
            continue
        try:
            out.append(float(tok))
        except ValueError:
            return []
    return out


def parse_growth(html):
    """window.renderMiniChart(el, "W1", [epoch, growth%, epoch, growth%, ...])."""
    m = re.search(r'renderMiniChart\([^,]+,\s*"[^"]*"\s*,\s*\[([-0-9.,\s]+)\]\s*\)', html)
    if not m:
        return []
    nums = _floats(m.group(1))
    rows, seen = [], set()
    for i in range(0, len(nums) - 1, 2):
        epoch, val = nums[i], nums[i + 1]
        try:
            d = datetime.fromtimestamp(epoch, tz=timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            continue
        if d in seen:
            rows[-1]["growthPct"] = val          # last point on a day wins
            continue
        seen.add(d)
        rows.append({"date": d, "growthPct": val})
    return rows


def parse_equity(html):
    """var equityData = [epoch, balance, equity, epoch, balance, equity, ...]."""
    m = re.search(r'var\s+equityData\s*=\s*\[([-0-9.,\s]+)\]', html)
    if not m:
        return []
    nums = _floats(m.group(1))
    rows, seen = [], set()
    for i in range(0, len(nums) - 2, 3):
        epoch, bal, eq = nums[i], nums[i + 1], nums[i + 2]
        try:
            ts = datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            continue
        if ts in seen:
            continue
        seen.add(ts)
        rows.append({"ts": ts, "balance": bal, "equity": eq})
    return rows


def parse_monthly(html):
    """growthChart(..., {table:{years:[{year:2025,yearly:7.45,months:{"4":1.21,...}}]}}).
    Values are ratios (7.4591 == 745.91%); months keys are 0-based."""
    m = re.search(r'table:\s*\{\s*years:\s*\[(.*?)\]\s*,\s*total:', html, re.S)
    if not m:
        return []
    block = m.group(1)
    rows = []
    for ym in re.finditer(r'\{\s*year:\s*(\d+)\s*,\s*yearly:\s*(-?[0-9.]+)\s*,\s*'
                          r'months:\s*\{([^}]*)\}', block):
        year = int(ym.group(1))
        yearly_pct = float(ym.group(2)) * 100.0
        for mm in re.finditer(r'"(\d+)"\s*:\s*(-?[0-9.]+)', ym.group(3)):
            rows.append({
                "year": year,
                "month": int(mm.group(1)) + 1,
                "returnPct": float(mm.group(2)) * 100.0,
                "yearlyPct": yearly_pct,
            })
    return rows


def parse_symbols(html):
    """table.signals-chart-dist -> per-symbol deals / buy / sell."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table", class_=lambda c: c and "signals-chart-dist" in c)
    if table is None:
        return []
    body = table.find("tbody") or table
    rows = []
    for tr in body.find_all("tr"):
        if "nohl" in (tr.get("class") or []):
            continue
        sym_td = tr.find("td", class_=lambda c: c and "col-symbol" in c)
        sym = clean_text(sym_td.get_text(" ")) if sym_td else None
        if not sym:
            continue
        deals_td = tr.find("td", class_=lambda c: c and "col-buy-sell" in c)
        deals = integer(deals_td.get_text(" ")) if deals_td else None
        row_html = str(tr)
        s = re.search(r"Sell trades on [^:]+:\s*([\d ,]+)", row_html)
        b = re.search(r"Buy trades on [^:]+:\s*([\d ,]+)", row_html)
        rows.append({
            "symbol": sym,
            "deals": deals,
            "buyTrades": integer(b.group(1)) if b else None,
            "sellTrades": integer(s.group(1)) if s else None,
        })
    return rows


# --------------------------------------------------------------------- combine

def build_parsed(page_html, signal_ref):
    ident = parse_identity(page_html)
    return {
        "signal_id": signal_ref["signal_id"],
        "mt_version": signal_ref.get("mt_version"),
        "url": signal_ref["url"],
        "identity": ident,
        "stats": parse_stats(page_html),
        "growth": parse_growth(page_html),
        "equity": parse_equity(page_html),
        "monthly": parse_monthly(page_html),
        "symbols": parse_symbols(page_html),
    }
