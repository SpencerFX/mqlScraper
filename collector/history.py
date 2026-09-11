"""Collect one signal's full Trading history (needs Http.authed).

Walks /en/signals/<id>/history, /history/page2, ... to the last page the paginator
advertises. Emits each page's rows through an `on_batch` callback so the caller
can persist incrementally - big signals run to 60+ pages and a kill mid-signal
must not throw the work away. `start_page` lets a re-run resume.
"""

from parser.history import parse_history_fragment, last_page_number, needs_login


class HistoryCollector:
    def __init__(self, http, config):
        self.http = http
        ccfg = config.get("collector", {}) or {}
        self.max_pages = int(ccfg.get("history_max_pages", 1000))

    def _url(self, sid, page):
        base = f"/en/signals/{sid}/history"
        return base if page <= 1 else f"{base}/page{page}"

    def collect(self, sid, start_page=1, on_batch=None):
        """-> meta {pages_fetched, last_page, gated, done}.  `done` is False if a
        page failed (so the caller keeps the signal pending)."""
        status, html = self.http.get_text(self._url(sid, max(start_page, 1)))
        if status != 200 or needs_login(html):
            return {"pages_fetched": 0, "last_page": None, "gated": True, "done": True}

        last = last_page_number(html) or start_page
        if on_batch:
            on_batch(parse_history_fragment(html), start_page)
        fetched = 1
        cap = min(last, self.max_pages)

        page = max(start_page, 1) + 1
        done = True
        while page <= cap:
            try:
                st, frag = self.http.get_text(self._url(sid, page))
            except Exception:
                done = False
                break
            if st != 200 or needs_login(frag):
                done = False
                break
            batch = parse_history_fragment(frag)
            if on_batch:
                on_batch(batch, page)
            fetched += 1
            if not batch:      # ran past the real end
                break
            page += 1

        return {"pages_fetched": fetched, "last_page": last, "gated": False,
                "done": done}
