"""Parse the mql5 signal "Trading history" tab (needs a logged-in session).

Anonymous, `/en/signals/<id>/history` returns only a "please log in" stub. With a
valid session cookie it returns the history table fragment:

    <table class="responsive-table signal-info-table">
      <thead> Time | Type | Volume | Symbol | Price | S/L | T/P | Time | Price |
              Commission | Swap | Profit | Comment </thead>
      <tbody> <tr> <td data-label="Time">..</td> ... </tr> ... </tbody>
    </table>
    <div class="paginatorEx"> ... Signals.BottomTabClick('history',<N>,'en',<id>) ... </div>

Each <td> carries a `data-label`; "Time" and "Price" appear twice (open, close).
Rows are trades (Type Buy/Sell[ Stop|Limit], Comment '' or 'cancelled') or
balance operations (Type "Balance", Comment Deposit/Withdrawal, amount in Profit).
Pagination is PATH: /history, /history/page2, ...
"""

import re

from bs4 import BeautifulSoup

from parser.stats import clean_text, number, parse_mql_ts


_NEEDS_LOGIN = re.compile(r"auth_login", re.I)
_PAGE_RE = re.compile(r"BottomTabClick\('history',\s*(\d+)\s*,")
_TRADE_TYPES = ("buy", "sell")


def needs_login(fragment_html):
    if not fragment_html:
        return True
    low = fragment_html.lower()
    return "auth_login" in low and "auth_logout" not in low and "paginatorex" not in low


def last_page_number(fragment_html):
    nums = [int(m.group(1)) for m in _PAGE_RE.finditer(fragment_html or "")]
    return max(nums) if nums else None


def _history_table(soup):
    return (soup.find("table", class_=lambda c: c and "signal-info-table" in c)
            or soup.find("table"))


def parse_history_fragment(fragment_html):
    """-> list of row dicts. Trade rows have `kind='trade'`; deposit/withdrawal
    rows have `kind='balance'` with `action` in {deposit, withdrawal} and the
    amount in `profit`."""
    if not fragment_html or needs_login(fragment_html):
        return []
    soup = BeautifulSoup(fragment_html, "lxml")
    table = _history_table(soup)
    if table is None:
        return []
    body = table.find("tbody") or table

    out = []
    for tr in body.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 12:
            continue  # the "latest day deals are hidden" notice row, headers, etc.

        # collect by data-label; Time/Price repeat -> keep both in order
        times, prices = [], []
        d = {}
        for td in tds:
            lbl = (td.get("data-label") or "").strip().lower()
            val = clean_text(td.get_text(" "))
            if lbl == "time":
                times.append(val)
            elif lbl == "price":
                prices.append(val)
            elif lbl:
                d[lbl] = val

        typ = (d.get("type") or "").strip()
        typ_l = typ.lower()
        comment = d.get("comment") or None

        row = {
            "openTime": parse_mql_ts(times[0]) if len(times) > 0 else None,
            "closeTime": parse_mql_ts(times[1]) if len(times) > 1 else None,
            "type": typ or None,
            "action": None,
            "volume": number(d.get("volume")),
            "symbol": d.get("symbol") or None,
            "openPrice": number(prices[0]) if len(prices) > 0 else None,
            "closePrice": number(prices[1]) if len(prices) > 1 else None,
            "sl": number(d.get("s/l")),
            "tp": number(d.get("t/p")),
            "commission": number(d.get("commission")),
            "swap": number(d.get("swap")),
            "profit": number(d.get("profit")),
            "comment": comment,
            "kind": "trade",
        }

        if typ_l == "balance" or (comment or "").lower() in ("deposit", "withdrawal"):
            row["kind"] = "balance"
            row["action"] = ((comment or "").lower()
                             if (comment or "").lower() in ("deposit", "withdrawal")
                             else "balance")
            row["symbol"] = None
            out.append(row)
            continue

        # trade: normalise action to buy/sell, keep the raw order type in `type`
        for t in _TRADE_TYPES:
            if typ_l.startswith(t):
                row["action"] = t
                break
        row["cancelled"] = (comment or "").lower() == "cancelled"
        out.append(row)
    return out
