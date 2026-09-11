"""Parse a signals listing page.

The flat "list" view (`/en/signals/mt4/list`) renders each signal as a
`<div class="row signal">` with `col-*` child divs. The category tabs
(`/en/signals/mt4/forex`) render the same signals as `<div class="signal-card">`
tiles instead. `parse_list_page` handles both, table rows first.
"""

import re

from bs4 import BeautifulSoup

from parser.stats import clean_text, integer, number, LIST_COLS


_ID_RE = re.compile(r"/signals/(\d+)")


def _row_signal(tr, base_url, mt_version):
    btn = tr.find(attrs={"data-id": True})
    sid = None
    name = None
    mt = mt_version
    if btn:
        sid = integer(btn.get("data-id"))
        name = clean_text(btn.get("data-name")) or None
        mt = integer(btn.get("data-mt")) or mt_version

    a = tr.find("a", class_="signal-avatar") or tr.find("a", href=_ID_RE)
    if sid is None and a and a.get("href"):
        m = _ID_RE.search(a["href"])
        if m:
            sid = int(m.group(1))
    if sid is None:
        return None
    if not name and a:
        nm = a.find("span", class_="name")
        name = clean_text(nm.get_text(" ")) if nm else None
    title = clean_text(a.get("title")) if a else None            # "'ATong' by Dinh Van Hung"
    author = None
    if title:
        m = re.search(r"\bby\s+(.+)$", title)
        if m:
            author = m.group(1).strip()

    acct = None
    st = tr.find("span", class_=lambda c: c and "ico_state" in c)
    if st:
        cls = " ".join(st.get("class") or [])
        acct = "Demo" if "demo" in cls else ("Real" if "real" in cls else None)

    row = {
        "signal_id": sid,
        "mt_version": mt,
        "name": name or str(sid),
        "author_name": author,
        "account_type": acct,
        "url": f"{base_url}/en/signals/{sid}",
    }
    for div in tr.find_all("div", class_=True):
        for cls in div.get("class"):
            hint = LIST_COLS.get(cls)
            if hint:
                field, coerce = hint
                if field not in row:
                    row[field] = coerce(div.get_text(" "))
    return row


def _card_signal(card, base_url, mt_version):
    a = card.find("a", class_="signal-card__wrapper") or card.find("a", href=_ID_RE)
    if not a or not a.get("href"):
        return None
    m = _ID_RE.search(a["href"])
    if not m:
        return None
    sid = int(m.group(1))

    nm = card.find("span", class_="signal-card__title-wrapper") \
        or card.find("span", class_="signal-card__title")
    au = card.find("span", class_="signal-card__author__item")
    login = None
    ac = card.find(onclick=re.compile(r"/en/users/"))
    if ac:
        mm = re.search(r"/en/users/([\w.\-]+)", ac.get("onclick", ""))
        if mm:
            login = mm.group(1)
    acct = None
    sh = card.find("span", class_=lambda c: c and "icons-ux_shield" in c)
    if sh and sh.get("title"):
        acct = "Demo" if "demo" in sh["title"].lower() else "Real"
    gv = card.find("span", class_="signal-card__growth-value")

    return {
        "signal_id": sid,
        "mt_version": mt_version,
        "name": clean_text(nm.get_text(" ")) if nm else str(sid),
        "author_name": clean_text(au.get_text(" ")) if au else None,
        "author_login": login,
        "account_type": acct,
        "url": f"{base_url}/en/signals/{sid}",
        "list_growth": number(gv.get_text(" ")) if gv else None,
    }


def parse_list_page(html, base_url, mt_version):
    soup = BeautifulSoup(html, "lxml")
    base = base_url.rstrip("/")
    out = {}
    for tr in soup.find_all("div", class_="row"):
        if "signal" not in (tr.get("class") or []):
            continue
        rec = _row_signal(tr, base, mt_version)
        if rec:
            out.setdefault(rec["signal_id"], rec)

    if not out:  # category tabs / the dashboard render tiles, not table rows
        for card in soup.find_all("div", class_="signal-card"):
            rec = _card_signal(card, base, mt_version)
            if rec:
                out.setdefault(rec["signal_id"], rec)
    return list(out.values())


def last_page_number(html):
    """Highest .../pageN in the paginator (works for /list and category tabs)."""
    if not html:
        return None
    nums = [int(m.group(1))
            for m in re.finditer(r"/signals/mt\d+/[a-z]+(?:/list)?/page(\d+)", html)]
    return max(nums) if nums else None
