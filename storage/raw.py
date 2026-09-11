"""Persist raw collected artefacts under data/raw/<signal_id>/ for replay/debugging."""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _safe(value):
    return (str(value).replace("/", "_").replace("\\", "_").replace(":", "_")
            .replace("?", "_").replace("*", "_"))


def _stamp(collected_at):
    return _safe(collected_at or datetime.now(timezone.utc).isoformat())


def save_raw_bundle(raw_dir, signal_id, snapshot):
    """snapshot: the dict returned by SignalCollector.collect()."""
    root = Path(raw_dir) / str(signal_id)
    root.mkdir(parents=True, exist_ok=True)
    stamp = _stamp(snapshot.get("collected_at"))

    html = snapshot.get("page_html", "") or ""
    digest = hashlib.sha1(html.encode("utf-8")).hexdigest()[:12]
    path = root / f"{stamp}_{digest}.page.html"
    path.write_text(html, encoding="utf-8")
    return str(path)


def save_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
