"""Append-oriented CSV sinks for the output tables.

  signals.csv    upsert by signalId               (rewritten on flush; small)
  snapshots.csv  append-only (one row per signal per run)
  growth.csv     insert-once by (signalId, date)   -- delete the file to force a refresh
  equity.csv     insert-once by (signalId, ts)     -- delete the file to force a refresh
  monthly.csv    insert-once by (signalId, year, month)
  symbols.csv    append-only (one block per signal per run, carries ts)
  trades/<signalId>.csv  one file per signal, insert-once by tradeKey -- keeps any
                 one file small and avoids re-scanning the whole trade history (now
                 several million rows) just to dedup a single signal's new page.

Column order is fixed by the *_FIELDS lists in normalizer.normalize.
"""

import csv
import os
import time
from pathlib import Path

from normalizer.normalize import (
    SIGNAL_FIELDS, SNAPSHOT_FIELDS, GROWTH_FIELDS, EQUITY_FIELDS,
    MONTHLY_FIELDS, SYMBOL_FIELDS, TRADE_FIELDS,
)


def _fmt(v):
    if v is None:
        return ""
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


class CsvStore:
    def __init__(self, csv_dir):
        self.dir = Path(csv_dir)
        self.dir.mkdir(parents=True, exist_ok=True)

        self.paths = {name: self.dir / f"{name}.csv" for name in
                      ("signals", "snapshots", "growth", "equity", "monthly",
                       "symbols")}
        self.fields = {
            "signals": SIGNAL_FIELDS, "snapshots": SNAPSHOT_FIELDS,
            "growth": GROWTH_FIELDS, "equity": EQUITY_FIELDS,
            "monthly": MONTHLY_FIELDS, "symbols": SYMBOL_FIELDS,
        }
        self.trades_dir = self.dir / "trades"
        self.trades_dir.mkdir(parents=True, exist_ok=True)

        self._signals = self._load_signals()
        self._growth_keys = self._load_keys("growth", lambda r: (r["signalId"], r["date"]))
        self._equity_keys = self._load_keys("equity", lambda r: (r["signalId"], r["ts"]))
        self._monthly_keys = self._load_keys(
            "monthly", lambda r: (r["signalId"], r["year"], r["month"]))
        self._trade_keys = {}  # signalId(str) -> set of tradeKeys, lazily loaded per-signal

        self._appended = {"snapshots": 0, "growth": 0, "equity": 0,
                          "monthly": 0, "symbols": 0, "trades": 0}

    # -- load existing -----------------------------------------------------------

    def _load_signals(self):
        p = self.paths["signals"]
        if not p.exists():
            return {}
        with p.open("r", encoding="utf-8", newline="") as f:
            return {row["signalId"]: row for row in csv.DictReader(f)}

    def _load_keys(self, name, keyfn):
        p = self.paths[name]
        if not p.exists():
            return set()
        keys = set()
        with p.open("r", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    keys.add(keyfn(row))
                except KeyError:
                    pass
        return keys

    # -- append helpers -------------------------------------------------------

    def _append(self, name, rows):
        if not rows:
            return
        fields = self.fields[name]
        p = self.paths[name]
        new_file = not p.exists() or p.stat().st_size == 0
        with p.open("a", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(fields)
            for r in rows:
                w.writerow([_fmt(r.get(k)) for k in fields])
        self._appended[name] = self._appended.get(name, 0) + len(rows)

    # -- public API ---------------------------------------------------------

    def get_signal(self, signal_id):
        return self._signals.get(str(signal_id))

    def upsert_signal(self, rec):
        sid = str(rec["signalId"])
        existing = self._signals.get(sid)
        if existing:
            for k in ("name", "authorLogin", "authorName", "accountType", "url",
                      "mtVersion", "broker", "server"):
                if rec.get(k):
                    existing[k] = _fmt(rec[k])
            existing["lastSeen"] = _fmt(rec["lastSeen"])
        else:
            self._signals[sid] = {k: _fmt(rec.get(k)) for k in SIGNAL_FIELDS}

    def add_snapshot(self, row):
        self._append("snapshots", [row])

    def _add_once(self, name, rows, keyset, keyfn):
        fresh = []
        for r in rows:
            key = keyfn(r)
            if key in keyset:
                continue
            keyset.add(key)
            fresh.append(r)
        self._append(name, fresh)
        return len(fresh)

    def add_growth(self, rows):
        return self._add_once("growth", rows, self._growth_keys,
                              lambda r: (str(r["signalId"]), str(r["date"])))

    def add_equity(self, rows):
        return self._add_once("equity", rows, self._equity_keys,
                              lambda r: (str(r["signalId"]), str(r["ts"])))

    def add_monthly(self, rows):
        return self._add_once("monthly", rows, self._monthly_keys,
                              lambda r: (str(r["signalId"]), str(r["year"]),
                                         str(r["month"])))

    def add_symbols(self, rows):
        self._append("symbols", rows)
        return len(rows)

    def _trade_path(self, signal_id):
        return self.trades_dir / f"{signal_id}.csv"

    def _trade_keys_for(self, signal_id):
        sid = str(signal_id)
        keys = self._trade_keys.get(sid)
        if keys is None:
            keys = set()
            p = self._trade_path(sid)
            if p.exists():
                with p.open("r", encoding="utf-8", newline="") as f:
                    for row in csv.DictReader(f):
                        tk = row.get("tradeKey")
                        if tk:
                            keys.add(tk)
            self._trade_keys[sid] = keys
        return keys

    def add_trades(self, rows):
        by_signal = {}
        for r in rows:
            by_signal.setdefault(str(r["signalId"]), []).append(r)
        fresh_total = 0
        for sid, rs in by_signal.items():
            keys = self._trade_keys_for(sid)
            fresh = [r for r in rs if r["tradeKey"] not in keys]
            if not fresh:
                continue
            keys.update(r["tradeKey"] for r in fresh)
            p = self._trade_path(sid)
            new_file = not p.exists() or p.stat().st_size == 0
            with p.open("a", encoding="utf-8", newline="") as f:
                w = csv.writer(f)
                if new_file:
                    w.writerow(TRADE_FIELDS)
                for r in fresh:
                    w.writerow([_fmt(r.get(k)) for k in TRADE_FIELDS])
            fresh_total += len(fresh)
        self._appended["trades"] = self._appended.get("trades", 0) + fresh_total
        return fresh_total

    def flush(self):
        """Rewrite signals.csv from memory (atomic)."""
        p = self.paths["signals"]
        tmp = p.with_suffix(".csv.tmp")
        with tmp.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(SIGNAL_FIELDS)
            for rec in self._signals.values():
                w.writerow([_fmt(rec.get(k)) for k in SIGNAL_FIELDS])
        for i in range(10):                       # Windows: dst can be briefly locked
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if i == 9:
                    raise
                time.sleep(0.3 * (i + 1))

    @property
    def counts(self):
        return dict(self._appended, signals=len(self._signals))
