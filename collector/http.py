"""HTTP access for the mql5.com signals crawler.

mql5.com serves the whole signal page - headline stats, the statistics tab, and
every chart series - to a plain HTTP GET. No Cloudflare, no browser, no session.

BUT: at population scale mql5 rate-limits hard. After a few thousand rapid
requests it firewalls the client IP and every connection to mql5.com is reset
(curl reports HTTP 000) for anywhere from minutes to hours. So this client:

  * throttles every request (`request_delay_seconds` + jitter),
  * retries a failed request with exponential backoff,
  * and - the important bit - when failures pile up (a block), it enters a long
    `cooldown_seconds` sleep, rebuilds the session, and resumes the *same*
    request. A mid-crawl block becomes a pause, not a wave of lost work. The
    crawl is checkpointed after every signal, so it can also just be re-run.
"""

import random
import time

import requests

_DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")


class HttpError(RuntimeError):
    """A request that kept failing across every retry and every cooldown."""


class Http:
    def __init__(self, config):
        bcfg = config.get("source", {}) or {}
        ccfg = config.get("collector", {}) or {}
        self.base_url = bcfg.get("base_url", "https://www.mql5.com").rstrip("/")
        self.delay = float(ccfg.get("request_delay_seconds", 3.0))
        self.timeout = int(ccfg.get("nav_timeout_s", 30))
        self.retries = int(ccfg.get("retries", 4))
        # block handling
        self.cooldown = int(ccfg.get("cooldown_seconds", 900))
        self.block_threshold = int(ccfg.get("block_threshold", 5))
        self.max_cooldowns = int(ccfg.get("max_cooldowns", 8))

        self._ua = bcfg.get("user_agent", _DEFAULT_UA)
        self._accept_lang = bcfg.get("accept_language", "en-US,en;q=0.9")
        # optional raw "Cookie:" header string for authenticated (logged-in) fetches
        self._cookie = (bcfg.get("cookie") or "").strip() or None
        self._s = None
        self._new_session()
        self._last = 0.0
        self._consec_fail = 0

    # -- session -----------------------------------------------------------

    def _new_session(self):
        if self._s is not None:
            try:
                self._s.close()
            except Exception:
                pass
        s = requests.Session()
        s.headers.update({
            "User-Agent": self._ua,
            "Accept-Language": self._accept_lang,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": f"{self.base_url}/en/signals",
            "Connection": "keep-alive",
        })
        if self._cookie:
            s.headers["Cookie"] = self._cookie
        self._s = s

    @property
    def authed(self):
        return bool(self._cookie)

    def start(self):
        return self

    def close(self):
        try:
            self._s.close()
        except Exception:
            pass

    def __enter__(self):
        return self.start()

    def __exit__(self, *exc):
        self.close()
        return False

    # -- throttle --------------------------------------------------------

    def _throttle(self):
        target = self.delay + random.uniform(0.0, self.delay * 0.5)
        elapsed = time.time() - self._last
        if elapsed < target:
            time.sleep(target - elapsed)
        self._last = time.time()

    # -- fetch --------------------------------------------------------------

    def _abs(self, path):
        if path.startswith("http://") or path.startswith("https://"):
            return path
        return self.base_url + ("" if path.startswith("/") else "/") + path

    def _cooldown(self, url, round_no):
        mins = self.cooldown / 60.0
        print(f"\n[http] mql5 looks rate-limited ({self._consec_fail} failures in a "
              f"row). Cooling down {mins:.0f} min (round {round_no}/{self.max_cooldowns}) "
              f"then resuming.\n       last url: {url}", flush=True)
        time.sleep(self.cooldown)
        self._new_session()
        self._consec_fail = 0

    def get(self, path, params=None, headers=None):
        """GET -> (status_code, text). An HTTP 4xx/5xx *body* is returned to the
        caller; only a total transport failure (after retries + cooldowns) raises
        HttpError."""
        url = self._abs(path)
        blocked_rounds = 0

        while True:
            last_exc = None
            for attempt in range(self.retries):
                self._throttle()
                try:
                    r = self._s.get(url, params=params, headers=headers,
                                    timeout=self.timeout)
                except requests.RequestException as exc:
                    last_exc = exc
                    self._consec_fail += 1
                    if self._consec_fail >= self.block_threshold:
                        break
                    time.sleep(2 ** attempt + random.uniform(0, 1))
                    continue
                if r.status_code in (403, 429, 503):
                    self._consec_fail += 1
                    if self._consec_fail >= self.block_threshold:
                        break
                    time.sleep(2 ** attempt + random.uniform(0, 2))
                    continue
                if r.status_code in (500, 502, 504) and attempt < self.retries - 1:
                    time.sleep(2 ** attempt + random.uniform(0, 1))
                    continue
                self._consec_fail = 0
                return r.status_code, r.text

            # exhausted retries for this request
            if self._consec_fail >= self.block_threshold and \
                    blocked_rounds < self.max_cooldowns:
                blocked_rounds += 1
                self._cooldown(url, blocked_rounds)
                continue
            raise HttpError(f"{url}: {last_exc or 'blocked'}")

    def get_text(self, path, params=None):
        return self.get(path, params=params)

    def get_json(self, path, params=None):
        import json
        status, body = self.get(path, params=params,
                                headers={"X-Requested-With": "XMLHttpRequest"})
        try:
            return status, json.loads(body)
        except Exception:
            return status, None
