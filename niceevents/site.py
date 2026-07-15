"""Static site generator.

Renders the DB into dist/index.html + dist/events.json.

The page is deliberately one self-contained file with the data inlined: no API,
no server, no build step at view time. That's what makes it hostable free on
GitHub Pages and instant to load.

Submissions: a static host can't accept a POST, so the form hands off to
whatever SUBMIT_ENDPOINT you configure (Formspree, Netlify, a Worker). With no
endpoint set it degrades to a prefilled GitHub issue link, which needs no
backend at all. See README.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db
from .models import CATEGORIES

TPL_DIR = Path(__file__).resolve().parent.parent / "templates"

SITE_TITLE = os.environ.get("SITE_TITLE", "What's on in Nice")
SUBMIT_ENDPOINT = os.environ.get("SUBMIT_ENDPOINT", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # e.g. "maddalena/nice-events"


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["free"] = bool(d.get("free"))
    d["outdoor"] = bool(d.get("outdoor"))
    for k in ("sources", "first_seen", "last_seen", "approved", "submitted_by"):
        d.pop(k, None)
    return {k: v for k, v in d.items() if v not in (None, "", 0) or k in ("start", "title", "town")}


def build(conn: sqlite3.Connection, out_dir: str = "dist") -> tuple[int, str]:
    rows = db.upcoming(conn)
    events = [_row_to_dict(r) for r in rows]
    stats = db.stats(conn)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Machine-readable feed — free to ship, useful later for the email digest
    # and for anyone who wants to build on it.
    (out / "events.json").write_text(
        json.dumps(
            {
                "generated": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "count": len(events),
                "events": events,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    env = Environment(
        loader=FileSystemLoader(TPL_DIR),
        autoescape=select_autoescape(["html"]),
    )
    tpl = env.get_template("index.html.jinja")

    submit_mode = "endpoint" if SUBMIT_ENDPOINT else ("github" if GITHUB_REPO else "none")

    html = tpl.render(
        title=SITE_TITLE,
        events_json=json.dumps(events, ensure_ascii=False, separators=(",", ":")),
        categories=CATEGORIES,
        cat_json=json.dumps(CATEGORIES, ensure_ascii=False),
        stats=stats,
        updated=date.today().strftime("%-d %B %Y") if os.name != "nt"
                else date.today().strftime("%d %B %Y"),
        submit_mode=submit_mode,
        submit_endpoint=SUBMIT_ENDPOINT,
        github_repo=GITHUB_REPO,
        source_count=len({(r["source"] or "").split(":")[0] for r in rows}),
    )
    (out / "index.html").write_text(html, encoding="utf-8")
    return len(events), str(out)
