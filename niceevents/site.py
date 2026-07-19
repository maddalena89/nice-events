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
import shutil
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

# Supabase. Both of these are baked into the published HTML on purpose — the
# anon key is an identifier, not a password, and Row Level Security is what
# actually guards the table (see supabase/schema.sql). The service_role key is
# a different animal entirely: it bypasses RLS, is read only by the scrape step
# from a GitHub *secret*, and must never reach this module or the template.
SUPABASE_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["free"] = bool(d.get("free"))
    d["outdoor"] = bool(d.get("outdoor"))
    d["online"] = bool(d.get("online"))
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

    # Supabase first: it's the only mode a passer-by can use without an account.
    # GITHUB_REPO is always set in CI, so without this ordering the github mode
    # would quietly win and keep asking strangers to sign up for GitHub.
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        submit_mode = "supabase"
    elif SUBMIT_ENDPOINT:
        submit_mode = "endpoint"
    elif GITHUB_REPO:
        submit_mode = "github"
    else:
        submit_mode = "none"

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
        supabase_url=SUPABASE_URL,
        supabase_anon_key=SUPABASE_ANON_KEY,
        source_count=len({(r["source"] or "").split(":")[0] for r in rows}),
    )
    (out / "index.html").write_text(html, encoding="utf-8")

    # PWA + static assets: manifest, service worker, icons. Copied verbatim from
    # static/ so the site is installable to a phone home screen and opens offline.
    # Missing static dir is not an error — the site works fine without the PWA.
    static = Path(__file__).resolve().parent.parent / "static"
    if static.is_dir():
        for f in static.iterdir():
            if f.is_file():
                shutil.copy2(f, out / f.name)

    return len(events), str(out)
