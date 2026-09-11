"""mqlScraper - crawl mql5.com/en/signals/mt4 into CSVs (and then a kdb+ HDB).

mql5 serves the whole signal page - headline stats, the statistics grid, and every
chart series - to a plain HTTP GET, so no browser is needed. Per-trade history is
behind an mql5 login and is deliberately out of scope; what is captured is the
headline snapshot, the weekly growth curve, the balance/equity curve, the
monthly-returns grid and the per-symbol trade distribution.

Typical use:

    python main.py --max-pages 3       # smoke test (3 directory pages)
    python main.py                     # full directory crawl (resumable)
    python main.py --load              # crawl, then load the CSVs into data/hdb
    python main.py --mt 5              # crawl the MT5 signals directory instead

The crawl is resumable: progress is recorded under data/state/ and re-running with
the same args picks up where it left off.
"""

import argparse
import subprocess
import sys
import time
import traceback
from pathlib import Path

import yaml

from collector.http import Http
from collector.directory import DirectoryCrawler
from collector.signal import SignalCollector
from collector.history import HistoryCollector
from parser.signal import build_parsed, parse_identity
from normalizer.normalize import (
    normalize_signal_registry, normalize_snapshot, normalize_growth,
    normalize_equity, normalize_monthly, normalize_symbols, normalize_trades,
)
from storage.csv_store import CsvStore
from storage.raw import save_raw_bundle
from storage.state import CrawlState

ROOT = Path(__file__).resolve().parent


def _deep_merge(base, over):
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


def load_config(path="config.yaml"):
    with open(ROOT / path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # config.local.yaml (gitignored) overlays secrets like source.cookie
    local = ROOT / "config.local.yaml"
    if local.exists():
        with open(local, "r", encoding="utf-8") as f:
            _deep_merge(cfg, yaml.safe_load(f) or {})
    return cfg


def run_load(config):
    q_exe = config.get("kdb", {}).get("q_exe", "q")
    hdb = str(ROOT / config["storage"]["hdb_dir"])
    csv_dir = str(ROOT / config["storage"]["csv_dir"])
    cmd = [q_exe, str(ROOT / "q" / "load.q"), "-hdb", hdb, "-csv", csv_dir, "-q"]
    print("[load]", " ".join(cmd))
    return subprocess.call(cmd)


def cmd_probe(config, args):
    out = ROOT / "data" / "probe"
    out.mkdir(parents=True, exist_ok=True)
    with Http(config) as http:
        for url in args.probe:
            status, html = http.get_text(url)
            tag = url.rstrip("/").split("/")[-1].split("?")[0] or "page"
            (out / f"{tag}.html").write_text(html, encoding="utf-8")
            print(f"{url}  -> data/probe/{tag}.html  (HTTP {status}, {len(html)} bytes)")
    return 0


def crawl(config, args):
    mt_cfg = str(args.mt if args.mt is not None
                 else config["source"].get("mt_version", "both"))
    mt_list = [4, 5] if mt_cfg == "both" else [int(mt_cfg)]
    disc_mode = args.discovery or config["source"].get("discovery", "full")
    base = config["source"]["base_url"]

    state = CrawlState(ROOT / config["storage"]["state_dir"])
    store = CsvStore(ROOT / config["storage"]["csv_dir"])
    raw_dir = ROOT / config["storage"]["raw_dir"]
    min_recheck = config["collector"]["min_recheck_hours"]

    if args.reset_progress:
        state.reset_progress()
    if args.rediscover:
        state.reset_discovery()
        state.reset_progress()

    budget = float(args.budget_min or config["collector"].get("budget_min", 0) or 0)
    deadline = (time.time() + budget * 60) if budget > 0 else None

    with Http(config) as http:
        collector = SignalCollector(http, config)

        def blind(signal_id):
            row = store.get_signal(signal_id)
            if row:
                return {"signal_id": int(signal_id), "mt_version": row.get("mtVersion") or None,
                        "name": row.get("name"), "author_name": row.get("authorName"),
                        "account_type": row.get("accountType"), "url": row["url"]}
            return {"signal_id": int(signal_id), "mt_version": None, "name": str(signal_id),
                    "url": f"{base}/en/signals/{signal_id}"}

        # -- discovery (resumable, per-facet) ------------------------------
        if args.signals:
            work = [blind(int(x)) for x in args.signals.split(",") if x.strip()]
        else:
            if not state.discovery_complete():
                max_pages = args.max_pages if args.max_pages is not None \
                    else config["collector"]["max_pages"]

                def _finish_facet(key, recs):
                    try:
                        state.finish_facet(key, recs)
                        for s in recs:
                            store.upsert_signal(normalize_signal_registry(s))
                        store.flush()
                    except Exception as exc:  # noqa: BLE001
                        print(f"[crawl] facet checkpoint warning: {exc}")

                all_done = True
                for mt in mt_list:
                    crawler = DirectoryCrawler(http, base, mt)
                    print(f"[crawl] discovering MT{mt} ({disc_mode}) - "
                          f"{len(state.discovery.get('facets_done', []))} facets done, "
                          f"{len(state.discovered_records())} signals so far", flush=True)
                    try:
                        done = crawler.discover(mode=disc_mode, max_pages=max_pages,
                                                facet_done=state.facet_done,
                                                finish_facet=_finish_facet,
                                                checkpoint_ids=state.checkpoint_discovered,
                                                deadline=deadline)
                    except Exception as exc:  # noqa: BLE001
                        print(f"[crawl] MT{mt} discovery error ({exc!r})")
                        if args.debug:
                            traceback.print_exc()
                        done = False
                    all_done = all_done and done
                    if not done:
                        break

                if all_done:
                    state.mark_discovery_complete()
                    state.set_pending([r["signal_id"]
                                       for r in state.discovered_records()])
                    print(f"[crawl] discovery COMPLETE: "
                          f"{len(state.discovered_records())} signals")
                else:
                    print(f"[crawl] discovery paused (budget) - "
                          f"{len(state.discovered_records())} signals found so far; "
                          f"re-run to continue")
                    store.flush()
                    return 0

            work = [blind(i) for i in state.next_pending()]
            print(f"[crawl] {len(work)} signals pending collection")

        if args.limit:
            work = work[:args.limit]

        # -- per-signal collection -----------------------------------------
        ok = err = skipped = 0
        stopped_early = False
        for n, signal in enumerate(work, 1):
            if deadline and time.time() > deadline:
                stopped_early = True
                print(f"[crawl] time budget reached after {n - 1} signals this run; "
                      f"re-run to continue")
                break
            sid = signal["signal_id"]
            if not args.force and not args.signals and \
                    state.recently_collected(sid, min_recheck):
                skipped += 1
                state.mark_done(sid)
                continue

            print(f"[{n}/{len(work)}] signal {sid} {signal.get('name', '')}")
            try:
                snap = collector.collect(signal)
                save_raw_bundle(raw_dir, sid, snap)

                parsed = build_parsed(snap["page_html"], signal)
                ident = parsed["identity"]

                store.upsert_signal(normalize_signal_registry(signal, ident))
                store.add_snapshot(normalize_snapshot(signal, parsed,
                                                      ts=snap["collected_at"]))
                g = store.add_growth(normalize_growth(signal, parsed))
                e = store.add_equity(normalize_equity(signal, parsed))
                m = store.add_monthly(normalize_monthly(signal, parsed))
                y = store.add_symbols(normalize_symbols(signal, parsed,
                                                        ts=snap["collected_at"]))
                store.flush()
                state.mark_collected(sid)
                state.mark_done(sid)
                ok += 1
                print(f"      stats={len(parsed['stats'])} fields, "
                      f"+{g} growth, +{e} equity, +{m} monthly, +{y} symbols")
            except Exception as exc:  # noqa: BLE001 - keep the crawl going
                err += 1
                print(f"      ERROR {sid}: {exc}")
                if args.debug:
                    traceback.print_exc()

        store.flush()
        remaining = len(state.next_pending())
        print(f"\n[crawl] {'paused' if stopped_early else 'done'}: {ok} ok, "
              f"{skipped} skipped (recent), {err} errors; {remaining} still pending")
        print(f"[crawl] csv counts: {store.counts}")

    if args.load and not stopped_early:
        rc = run_load(config)
        if rc != 0:
            print(f"[load] q exited {rc}")
            return rc
    return 0


def crawl_trades(config, args):
    """Second pass: per-signal Trading history -> trades.csv. Resumable, budgeted."""
    state = CrawlState(ROOT / config["storage"]["state_dir"])
    store = CsvStore(ROOT / config["storage"]["csv_dir"])
    if args.reset_trades:
        state.reset_hist()

    budget = float(args.budget_min or config["collector"].get("budget_min", 0) or 0)
    deadline = (time.time() + budget * 60) if budget > 0 else None

    with Http(config) as http:
        if not http.authed:
            print("[trades] no source.cookie set (config.local.yaml) - the history "
                  "tab needs a logged-in mql5 session. Aborting.")
            return 2
        hd = config["collector"].get("history_delay_s")
        if hd:
            http.delay = float(hd)
        hc = HistoryCollector(http, config)

        if args.signals:
            ids = [int(x) for x in args.signals.split(",") if x.strip()]
        else:
            ids = sorted(int(s) for s in store._signals) if store._signals else []
        done = state.hist_done_ids()
        work = [i for i in ids if i not in done]
        if args.limit:
            work = work[:args.limit]
        print(f"[trades] {len(work)} signals to do "
              f"({len(done)} already done/gated of {len(ids)} total)")

        ok = gated = err = ntr = 0
        stopped_early = False
        for n, sid in enumerate(work, 1):
            if deadline and time.time() > deadline:
                stopped_early = True
                print(f"[trades] budget reached after {n - 1} signals this run")
                break
            start = state.hist_cursor(sid)
            counts = {"pages": 0, "rows": 0, "fresh": 0}

            def _on_batch(rows, page, _sid=sid):
                fresh = store.add_trades(normalize_trades(_sid, rows))
                counts["pages"] += 1
                counts["rows"] += len(rows)
                counts["fresh"] += fresh
                state.hist_advance(_sid, page)

            try:
                meta = hc.collect(sid, start_page=start, on_batch=_on_batch)
                ntr += counts["fresh"]
                if meta["gated"]:
                    gated += 1
                    state.hist_mark(sid, gated=True)
                    print(f"[{n}/{len(work)}] {sid}: gated")
                elif meta["done"]:
                    ok += 1
                    state.hist_mark(sid)
                    print(f"[{n}/{len(work)}] {sid}: {counts['pages']}p from {start}, "
                          f"{counts['rows']} rows (+{counts['fresh']} new)")
                else:
                    print(f"[{n}/{len(work)}] {sid}: partial ({counts['pages']}p) - "
                          f"will resume from p{state.hist_cursor(sid)}")
            except Exception as exc:  # noqa: BLE001
                err += 1
                print(f"[{n}/{len(work)}] {sid}: ERROR {exc}")
                if args.debug:
                    traceback.print_exc()

        rem = len([i for i in ids if i not in state.hist_done_ids()])
        print(f"\n[trades] {'paused' if stopped_early else 'done'}: {ok} ok, "
              f"{gated} gated, {err} errors, +{ntr} trade rows; {rem} signals left")

    if args.load and not stopped_early:
        rc = run_load(config)
        if rc != 0:
            return rc
    return 0


def crawl_brokers(config, args):
    """Auth pass: re-visit each signal page for its trade-server / broker tag
    (the anonymous population crawl cannot see it). Fills signals.csv
    broker/server. Resumable, budgeted."""
    state = CrawlState(ROOT / config["storage"]["state_dir"])
    store = CsvStore(ROOT / config["storage"]["csv_dir"])
    base = config["source"]["base_url"]
    if args.reset_brokers:
        state.reset_brokers()

    budget = float(args.budget_min or config["collector"].get("budget_min", 0) or 0)
    deadline = (time.time() + budget * 60) if budget > 0 else None

    with Http(config) as http:
        if not http.authed:
            print("[brokers] no source.cookie set (config.local.yaml) - the trade "
                  "server tag needs a logged-in mql5 session. Aborting.")
            return 2
        bd = config["collector"].get("broker_delay_s")
        if bd:
            http.delay = float(bd)

        if args.signals:
            ids = [int(x) for x in args.signals.split(",") if x.strip()]
        else:
            ids = sorted(int(s) for s in store._signals) if store._signals else []
        done = state.broker_done_ids()
        work = [i for i in ids if i not in done]
        if args.limit:
            work = work[:args.limit]
        print(f"[brokers] {len(work)} signals to do "
              f"({len(done)} already resolved of {len(ids)} total)")

        ok = miss = err = 0
        stopped_early = False
        for n, sid in enumerate(work, 1):
            if deadline and time.time() > deadline:
                stopped_early = True
                print(f"[brokers] budget reached after {n - 1} signals this run")
                break
            try:
                status, html = http.get_text(f"/en/signals/{sid}")
                if status != 200:
                    err += 1
                    print(f"[{n}/{len(work)}] {sid}: HTTP {status}")
                    continue
                ident = parse_identity(html)
                srv, brk = ident.get("server"), ident.get("broker")
                store.upsert_signal(normalize_signal_registry(
                    {"signal_id": sid, "url": f"{base}/en/signals/{sid}"}, ident))
                store.flush()
                if srv:
                    ok += 1
                    state.broker_mark(sid)
                    print(f"[{n}/{len(work)}] {sid}: {brk}  ({srv})")
                else:
                    miss += 1
                    state.broker_mark(sid, gated=True)
                    print(f"[{n}/{len(work)}] {sid}: no trade-server tag "
                          f"(private / delisted)")
            except Exception as exc:  # noqa: BLE001
                err += 1
                print(f"[{n}/{len(work)}] {sid}: ERROR {exc}")
                if args.debug:
                    traceback.print_exc()

        rem = len([i for i in ids if i not in state.broker_done_ids()])
        print(f"\n[brokers] {'paused' if stopped_early else 'done'}: {ok} ok, "
              f"{miss} missing, {err} errors; {rem} signals left")

    if args.load and not stopped_early:
        rc = run_load(config)
        if rc != 0:
            return rc
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mt", choices=("4", "5", "both"), default=None,
                    help="signals directory to crawl (default: config, 'both')")
    ap.add_argument("--discovery", choices=("full", "list", "full+cats",
                                            "full+orderby"), default=None,
                    help="'full'/'list' = the plain 40/55-page listing per platform "
                         "(this IS the whole discoverable set); 'full+cats' / "
                         "'full+orderby' additionally sweep category tabs / re-sorts "
                         "(measured to add 0 new signals - opt-in for auditing only)")
    ap.add_argument("--probe", nargs="+", metavar="URL",
                    help="fetch URL(s), dump HTML to data/probe/")
    ap.add_argument("--max-pages", type=int, default=None,
                    help="limit directory pages crawled (default: config, 0 = all)")
    ap.add_argument("--limit", type=int, default=None,
                    help="only collect the first N signals this run")
    ap.add_argument("--budget-min", type=float, default=None,
                    help="stop cleanly after N minutes (discovery and collection "
                         "both resume on the next run); 0 = unlimited")
    ap.add_argument("--signals", type=str, default=None,
                    help="comma-separated signal IDs to collect (skips discovery)")
    ap.add_argument("--force", action="store_true",
                    help="re-collect even if collected within min_recheck_hours")
    ap.add_argument("--rediscover", action="store_true",
                    help="wipe discovery + pending progress and start discovery over")
    ap.add_argument("--reset-progress", action="store_true",
                    help="clear the resumable-crawl progress file first")
    ap.add_argument("--load", action="store_true",
                    help="after crawling, load the CSVs into data/hdb via q/load.q")
    ap.add_argument("--trades", action="store_true",
                    help="second pass: pull each signal's full Trading history "
                         "(needs source.cookie in config.local.yaml). Resumable.")
    ap.add_argument("--reset-trades", action="store_true",
                    help="clear the trade-history pass progress first")
    ap.add_argument("--brokers", action="store_true",
                    help="auth pass: re-fetch each signal page for its trade-server "
                         "/ broker tag (needs source.cookie). Resumable.")
    ap.add_argument("--reset-brokers", action="store_true",
                    help="clear the broker pass progress first")
    ap.add_argument("--debug", action="store_true", help="print tracebacks on errors")
    args = ap.parse_args(argv)

    config = load_config()
    if args.probe:
        return cmd_probe(config, args)
    if args.trades:
        return crawl_trades(config, args)
    if args.brokers:
        return crawl_brokers(config, args)
    return crawl(config, args)


if __name__ == "__main__":
    sys.exit(main())
