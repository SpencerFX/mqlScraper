"""Collect one signal: fetch its public page.

Everything we record - headline stats, the statistics tab, the growth / balance /
equity series, the monthly-returns grid and the per-symbol distribution - is
present in that single HTML document (partly as rendered markup, partly as the
inline JS bootstrap that feeds the SVG charts). So one GET per signal.
"""

from datetime import datetime, timezone


class SignalCollector:
    def __init__(self, http, config):
        self.http = http

    def collect(self, signal):
        url = signal["url"]
        status, html = self.http.get_text(url)
        if status != 200 or not html:
            raise RuntimeError(f"signal page {url} -> HTTP {status}")
        return {
            "signal_id": signal["signal_id"],
            "url": url,
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "page_html": html,
        }
