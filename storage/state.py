"""Resumable-crawl bookkeeping under data/state/."""

import json
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path


def _replace_retry(src, dst, tries=10):
    """Path.replace, retried - on Windows an AV / indexer can briefly lock dst."""
    for i in range(tries):
        try:
            src.replace(dst)
            return
        except PermissionError:
            if i == tries - 1:
                raise
            time.sleep(0.3 * (i + 1))


class CrawlState:
    def __init__(self, state_dir):
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.seen_path = self.dir / "seen_signals.json"
        self.progress_path = self.dir / "crawl_progress.json"
        self.disc_path = self.dir / "discovery.json"
        self.hist_path = self.dir / "hist_progress.json"
        self.broker_path = self.dir / "broker_progress.json"
        self.seen = self._load(self.seen_path, {})
        self.progress = self._load(self.progress_path, {"pending": [], "done": []})
        self.discovery = self._load(self.disc_path,
                                    {"facets_done": [], "complete": False, "ids": {}})
        self.hist = self._load(self.hist_path,
                               {"done": [], "gated": [], "cursor": {}})
        self.broker = self._load(self.broker_path, {"done": [], "gated": []})

    @staticmethod
    def _load(path, default):
        if path.exists():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                pass
        return json.loads(json.dumps(default))

    def _save(self, path, obj):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, indent=1), encoding="utf-8")
        _replace_retry(tmp, path)

    # -- signal recency --------------------------------------------------------

    def recently_collected(self, signal_id, min_recheck_hours):
        ts = self.seen.get(str(signal_id))
        if not ts:
            return False
        try:
            when = datetime.fromisoformat(ts)
        except ValueError:
            return False
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - when < timedelta(hours=min_recheck_hours)

    def mark_collected(self, signal_id):
        self.seen[str(signal_id)] = datetime.now(timezone.utc).isoformat()
        self._save(self.seen_path, self.seen)

    # -- crawl queue --------------------------------------------------------

    def set_pending(self, signal_ids):
        done = set(self.progress.get("done", []))
        self.progress["pending"] = [s for s in signal_ids if s not in done]
        self._save(self.progress_path, self.progress)

    def next_pending(self):
        return list(self.progress.get("pending", []))

    def mark_done(self, signal_id):
        self.progress["pending"] = [s for s in self.progress.get("pending", [])
                                    if s != signal_id]
        done = self.progress.get("done", [])
        if signal_id not in done:
            done.append(signal_id)
        self.progress["done"] = done
        self._save(self.progress_path, self.progress)

    def reset_progress(self):
        self.progress = {"pending": [], "done": []}
        self._save(self.progress_path, self.progress)

    # -- resumable discovery ------------------------------------------------
    # Full-population discovery (the ?orderby / category facet sweep) is far
    # longer than one run, so each facet's ids are persisted and a re-run
    # skips facets already done.

    def facet_done(self, key):
        return key in self.discovery.get("facets_done", [])

    def add_discovered(self, recs):
        ids = self.discovery.setdefault("ids", {})
        for r in recs:
            ids.setdefault(str(r["signal_id"]), r)

    def checkpoint_discovered(self, recs):
        """Persist ids mid-facet without marking the facet done."""
        self.add_discovered(recs)
        self._save(self.disc_path, self.discovery)

    def finish_facet(self, key, recs):
        self.add_discovered(recs)
        fd = self.discovery.setdefault("facets_done", [])
        if key not in fd:
            fd.append(key)
        self._save(self.disc_path, self.discovery)

    def discovered_records(self):
        return list(self.discovery.get("ids", {}).values())

    def discovery_complete(self):
        return bool(self.discovery.get("complete"))

    def mark_discovery_complete(self):
        self.discovery["complete"] = True
        self._save(self.disc_path, self.discovery)

    def reset_discovery(self):
        self.discovery = {"facets_done": [], "complete": False, "ids": {}}
        self._save(self.disc_path, self.discovery)

    # -- trade-history pass -----------------------------------------------

    def hist_done_ids(self):
        return set(self.hist.get("done", [])) | set(self.hist.get("gated", []))

    def hist_cursor(self, signal_id):
        """Next history page to fetch for this signal (1 if untouched)."""
        return int(self.hist.get("cursor", {}).get(str(signal_id), 0)) + 1

    def hist_advance(self, signal_id, page):
        cur = self.hist.setdefault("cursor", {})
        if page > int(cur.get(str(signal_id), 0)):
            cur[str(signal_id)] = int(page)
            self._save(self.hist_path, self.hist)

    def hist_mark(self, signal_id, gated=False):
        bucket = "gated" if gated else "done"
        lst = self.hist.setdefault(bucket, [])
        if signal_id not in lst:
            lst.append(signal_id)
        self.hist.get("cursor", {}).pop(str(signal_id), None)
        self._save(self.hist_path, self.hist)

    def reset_hist(self):
        self.hist = {"done": [], "gated": [], "cursor": {}}
        self._save(self.hist_path, self.hist)

    # -- broker (trade-server) pass -------------------------------------------

    def broker_done_ids(self):
        return set(self.broker.get("done", [])) | set(self.broker.get("gated", []))

    def broker_mark(self, signal_id, gated=False):
        bucket = "gated" if gated else "done"
        lst = self.broker.setdefault(bucket, [])
        if signal_id not in lst:
            lst.append(signal_id)
        self._save(self.broker_path, self.broker)

    def reset_brokers(self):
        self.broker = {"done": [], "gated": []}
        self._save(self.broker_path, self.broker)
