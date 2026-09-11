"""Crawl the signals directory.

mql5 paginates every listing by PATH - `/en/signals/mt4/list/page2`,
`/en/signals/mt4/forex/page2` - ~48 rows per page, and `.paginatorEx` links the
last page.

The catch: **every listing is hard-capped at 40 pages (MT4) / 55 pages (MT5)**,
so a platform's `/list` exposes only its top ~1,900 (MT4) / ~2,600 (MT5) signals -
and measurement shows that IS the whole discoverable set. Both the `?orderby=`
re-sorts and the category tabs (`/forex`, `/gold`, ...) turned out to be strict
subsets of `/list` at full page depth: sweeping all 5 MT4 category tabs (>1,300
signals each) added 0 new ids over `/list`'s 1,876. So `mode="full"` == `"list"`
in practice; the category / orderby facets are kept opt-in only (`"full+cats"` /
`"full+orderby"`) for the record. mql5 does not publish a wider index.

The sweep is longer than one run can last, so `discover()` checkpoints per facet
(`facet_done` / `finish_facet`) and mid-facet (`checkpoint_ids`), and honours a
wall-clock `deadline`; a re-run skips finished facets. Returns True iff every
facet completed.
"""

import time

from parser.directory import parse_list_page, last_page_number

# re-sorts of the flat list. NOT swept by default - see module docstring.
FACET_ORDERBYS = [
    "gain", "balance", "subscribers", "subscribersdepositstotal", "weeks",
    "trades", "experts", "inplus", "activity", "pf", "expextedpayoff",
    "drawdown", "leverage", "quality", "price",
]
# category tabs (paginate as /<slug>/pageN, not /<slug>/list/pageN)
FACET_CATEGORIES = ["forex", "gold", "crypto", "trusted", "live"]


class DirectoryCrawler:
    def __init__(self, http, base_url, mt_version):
        self.http = http
        self.base_url = base_url.rstrip("/")
        self.mt = int(mt_version)
        self.root = f"/en/signals/mt{self.mt}"

    # -- facet plan --------------------------------------------------------

    def _facets(self, mode):
        """(label, path_prefix, orderby) tuples to sweep. `full` == `list`:
        the extra facets are empirically subsets, kept opt-in only."""
        facets = [("list", f"{self.root}/list", None)]
        if mode in ("full+cats", "full+orderby"):
            facets += [(f"cat:{c}", f"{self.root}/{c}", None)
                       for c in FACET_CATEGORIES]
        if mode == "full+orderby":
            facets += [(f"list?orderby={k}", f"{self.root}/list", k)
                       for k in FACET_ORDERBYS]
        return facets

    @staticmethod
    def _page_url(prefix, orderby, page):
        url = prefix if page <= 1 else f"{prefix}/page{page}"
        return f"{url}?orderby={orderby}" if orderby else url

    # -- crawl ------------------------------------------------------------

    def discover(self, mode="full", max_pages=0, facet_done=None, finish_facet=None,
                 checkpoint_ids=None, deadline=None, empty_streak_stop=2,
                 safety_cap=200, checkpoint_every=5):
        """Sweep the facet plan. `facet_done(key)` -> skip that facet;
        `finish_facet(key, recs)` -> persist a completed facet's rows;
        `checkpoint_ids(recs)` -> persist ids mid-facet (every `checkpoint_every`
        pages) so a kill loses no data, only the facet-done marker; `deadline` is
        a time.time() value past which we stop cleanly. Returns True iff every
        facet in the plan is now done."""
        all_done = True

        for label, prefix, orderby in self._facets(mode):
            key = f"mt{self.mt}:{label}"
            if facet_done and facet_done(key):
                continue
            if deadline and time.time() > deadline:
                all_done = False
                break

            print(f"[directory] === facet {key} ===", flush=True)
            facet = {}
            empty_streak = 0
            page = 1
            total_pages = None
            timed_out = False

            while page <= safety_cap:
                if deadline and time.time() > deadline:
                    timed_out = True
                    break
                url = self._page_url(prefix, orderby, page)
                try:
                    status, html = self.http.get_text(url)
                    signals = (parse_list_page(html, self.base_url, self.mt)
                               if status == 200 else [])
                except Exception as exc:  # one bad page must not abort discovery
                    print(f"[directory] {key} p{page}: ERROR {exc!r} - skipping")
                    signals, html = [], ""

                if total_pages is None:
                    total_pages = last_page_number(html)

                before = len(facet)
                for s in signals:
                    facet.setdefault(s["signal_id"], s)
                added = len(facet) - before
                if added or page == 1:
                    print(f"[directory] {key} p{page}: {len(signals)} rows, "
                          f"+{added} new in facet ({len(facet)})", flush=True)

                if checkpoint_ids and page % checkpoint_every == 0:
                    checkpoint_ids(list(facet.values()))

                empty_streak = empty_streak + 1 if len(signals) == 0 else 0
                if empty_streak >= empty_streak_stop:
                    break
                if max_pages and page >= max_pages:
                    break
                if total_pages and page >= total_pages:
                    break
                page += 1

            if timed_out:
                if checkpoint_ids:
                    checkpoint_ids(list(facet.values()))
                all_done = False
                break                       # leave this facet unmarked; redo next run

            if finish_facet:
                finish_facet(key, list(facet.values()))
            print(f"[directory] facet {key} done: {len(facet)} signals", flush=True)

        return all_done
