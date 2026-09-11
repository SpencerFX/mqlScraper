"""Coercion helpers for mql5 signal values.

mql5 formats numbers with a space (often a thin / non-breaking space) as the
thousands separator - "3 543.06%", "5 932.43 USD", "586 744 pips" - and uses
compact "1.4K" / "46K USD" on the directory list. Timestamps are "2025.04.28
22:52:09". These helpers normalise all of that.
"""

import re

from dateutil import parser as _dateparser


_WS = "      \t"


def clean_text(value):
    if value is None:
        return None
    value = value.translate({ord(c): " " for c in _WS})
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def number(value):
    """First numeric token as float, sign-aware. Strips spaces, commas, %, $, units."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = clean_text(str(value))
    if text is None:
        return None
    text = text.replace(",", "").replace(" ", "")
    m = re.search(r"-?\d+(?:\.\d+)?", text)
    return float(m.group(0)) if m else None


def percent(value):
    """Percentages are stored as their bare numeric value (12.3 == 12.3%)."""
    return number(value)


def money(value):
    """Prefer a leading amount before a currency word ('3 114.61 USD' -> 3114.61)."""
    if value is None:
        return None
    text = clean_text(str(value))
    if text is None:
        return None
    m = re.search(r"-?[\d ,]*\d(?:\.\d+)?(?=\s*(?:USD|EUR|GBP|JPY|CHF|AUD|CAD|\$)?)", text)
    return number(m.group(0)) if m else number(text)


def compact(value):
    """'1.4K' -> 1400.0, '46K USD' -> 46000.0, '2.1M' -> 2100000.0."""
    if value is None:
        return None
    text = clean_text(str(value))
    if text is None:
        return None
    m = re.search(r"(-?[\d ,]*\d(?:\.\d+)?)\s*([KkMmBbTt])?", text.replace(",", ""))
    if not m:
        return number(text)
    base = number(m.group(1))
    if base is None:
        return None
    mult = {"k": 1e3, "m": 1e6, "b": 1e9, "t": 1e12}.get((m.group(2) or "").lower(), 1.0)
    return base * mult


def integer(value):
    n = number(value)
    return int(n) if n is not None else None


def parse_pct_pair(value):
    """'515 (62.42%)' -> (515.0, 62.42).  '170 (34.27%)' -> (170.0, 34.27)."""
    if value is None:
        return None, None
    text = clean_text(str(value)) or ""
    nums = re.findall(r"-?[\d ,]*\d(?:\.\d+)?", text.replace(",", ""))
    count = number(nums[0]) if nums else None
    pct = None
    m = re.search(r"\(\s*(-?[\d .]*\d(?:\.\d+)?)\s*%", text)
    if m:
        pct = number(m.group(1))
    return count, pct


def parse_amount_paren(value):
    """'25 ( 539.19 USD)' -> (25.0, 539.19).  '311.25 USD (28.16%)' -> (311.25, 28.16)."""
    if value is None:
        return None, None
    text = clean_text(str(value)) or ""
    lead = re.match(r"\s*(-?[\d ,]*\d(?:\.\d+)?)", text.replace(",", ""))
    inner = re.search(r"\(\s*(-?[\d ,]*\d(?:\.\d+)?)", text.replace(",", ""))
    return (number(lead.group(1)) if lead else None,
            number(inner.group(1)) if inner else None)


def parse_usd_pips(value):
    """'5 932.43 USD ( 586 744 pips)' -> (5932.43, 586744.0)."""
    if value is None:
        return None, None
    text = clean_text(str(value)) or ""
    usd = money(text)
    m = re.search(r"\(\s*(-?[\d ,]*\d(?:\.\d+)?)\s*pips", text.replace(",", ""))
    return usd, (number(m.group(1)) if m else None)


def parse_leverage(value):
    """'1:500' -> 500."""
    if value is None:
        return None
    m = re.search(r"1\s*:\s*(\d+)", clean_text(str(value)) or "")
    return int(m.group(1)) if m else integer(value)


def parse_mql_ts(value):
    """'2025.04.28 22:52:09' / '2025.04.28' -> ISO 8601 string, or None."""
    if not value:
        return None
    text = clean_text(str(value))
    if not text:
        return None
    m = re.match(r"(\d{4})\.(\d{2})\.(\d{2})(.*)$", text)
    if m:
        text = f"{m.group(1)}-{m.group(2)}-{m.group(3)}{m.group(4)}"
    try:
        return _dateparser.parse(text).isoformat()
    except Exception:
        return None


_DUR_RE = re.compile(
    r"(?:(\d+)\s*year)?\D*(?:(\d+)\s*month)?\D*(?:(\d+)\s*week)?\D*(?:(\d+)\s*day)?\D*"
    r"(?:(\d+)\s*hour)?\D*(?:(\d+)\s*min)?\D*(?:(\d+)\s*sec)?",
    re.I,
)
_DUR_UNITS = (365 * 86400, 30 * 86400, 7 * 86400, 86400, 3600, 60, 1)


def parse_duration_seconds(value):
    """'3 hours' / '1 day 4 hours' / '45 minutes' -> seconds (int), or None."""
    if not value:
        return None
    text = clean_text(str(value))
    if not text:
        return None
    hms = re.match(r"^(\d+):(\d{2}):(\d{2})$", text)
    if hms:
        h, m, s = map(int, hms.groups())
        return h * 3600 + m * 60 + s
    m = _DUR_RE.match(text.lower())
    if not m or not any(m.groups()):
        return None
    total = sum(int(g) * u for g, u in zip(m.groups(), _DUR_UNITS) if g)
    return total or None


# ---- directory-list column -> registry / snapshot hints ----------------------
# (the per-signal page is authoritative; these are only used to seed rows)
LIST_COLS = {
    "col-growth": ("list_growth", percent),
    "col-subscribers": ("list_subscribers", integer),
    "col-facilities": ("list_funds", compact),
    "col-balance": ("list_balance", compact),
    "col-weeks": ("list_weeks", integer),
    "col-experts": ("list_algo_pct", percent),
    "col-trades": ("list_trades", integer),
    "col-plus": ("list_win_pct", percent),
    "col-activity": ("list_activity_pct", percent),
    "col-pf": ("list_profit_factor", number),
    "col-ep": ("list_expected_payoff", money),
    "col-drawdown": ("list_drawdown_pct", percent),
    "col-leverage": ("list_leverage", parse_leverage),
}
