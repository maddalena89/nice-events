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
import re
import shutil
import sqlite3
import unicodedata
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db
from .models import CATEGORIES, _title_key

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


def _canonical_host() -> str:
    """Production host for absolute short links (whatsonnice.com/<slug>).

    Env override wins; otherwise read it from static/CNAME so the printed link and
    QR are correct even when the site is built and previewed somewhere else.
    """
    h = os.environ.get("SITE_HOST", "").strip()
    if h:
        return h
    cname = Path(__file__).resolve().parent.parent / "static" / "CNAME"
    if cname.is_file():
        lines = cname.read_text(encoding="utf-8").strip().splitlines()
        return lines[0].strip() if lines else ""
    return ""


def _collapse_overlaps(events: list[dict]) -> list[dict]:
    """Merge same-title, same-town events whose dates overlap into one row.

    Two sources describing the same run — a curated multi-day entry (e.g. a
    festival "19–26 Jul") and a scraper that lists it once per night — have
    different start dates, so they get different fingerprints and survive as
    separate rows: the exact "why is this doubled?" the DB-level dedup can't
    catch. Here, at render time, we group by normalised title + town, sweep the
    date ranges, and fold any overlapping cluster into a single event spanning
    their union. Non-overlapping repeats (a weekly class on separate nights)
    keep their own rows — they don't overlap, so they're left alone.
    """
    def d(s: str) -> date:
        return date.fromisoformat(s)

    groups: dict[tuple, list[dict]] = {}
    for e in events:
        groups.setdefault((_title_key(e.get("title", "")), e.get("town", "")), []).append(e)

    out: list[dict] = []
    for evs in groups.values():
        if len(evs) == 1:
            out.append(evs[0])
            continue
        evs.sort(key=lambda e: (e["start"], e.get("end") or e["start"]))
        cluster: list[dict] = []
        c_start = c_end = None
        for e in evs:
            s, en = d(e["start"]), d(e.get("end") or e["start"])
            if cluster and s <= c_end:                 # overlaps the open cluster
                cluster.append(e)
                c_end = max(c_end, en)
            else:
                if cluster:
                    out.append(_merge_cluster(cluster, c_start, c_end))
                cluster, c_start, c_end = [e], s, en
        if cluster:
            out.append(_merge_cluster(cluster, c_start, c_end))

    out.sort(key=lambda e: (e["start"], e.get("title", "")))
    return out


def _merge_cluster(members: list[dict], start: date, end: date) -> dict:
    """One event out of an overlapping cluster: earliest entry wins the copy,
    missing fields filled from the rest, date range widened to the union."""
    base = dict(members[0])                              # earliest start (already sorted)
    for m in members[1:]:
        for f in ("venue", "note", "url", "time", "category", "image"):
            if not base.get(f) and m.get(f):
                base[f] = m[f]
        base["free"] = bool(base.get("free") or m.get("free"))
        base["outdoor"] = bool(base.get("outdoor") or m.get("outdoor"))
    base["start"] = start.isoformat()
    if end > start:
        base["end"] = end.isoformat()
    else:
        base.pop("end", None)
    return base


# Short, human-friendly slug for a card's real short link (whatsonnice.com/<slug>).
# Drops event-type filler and articles, keeps the first couple of distinctive
# words: "Vernissage de l'artiste Jasmine" -> "jasmine". MUST match the JS
# fallback in the template (cardSlug) so a card built before the next scrape and
# one built after point at the same place.
_CARD_STOP = set((
    "vernissage exposition expo concert soiree spectacle atelier festival brocante "
    "marche visite balade projection l la le les de des du au aux un une et the a of "
    "at in on and with avec artiste artist en fete"
).split())


# No em/en dashes in any displayed title — collapse them to a plain " - ". Source
# titles occasionally carry them ("Ellsworth Kelly — At the Edge of Water"); this
# normalises everything the site shows (listing, feed, cards) in one place.
_DASH_RE = re.compile(r"\s*[—–]\s*")


def _clean_title(t: str) -> str:
    return _DASH_RE.sub(" - ", t or "")


def _card_slug(title: str) -> str:
    t = unicodedata.normalize("NFD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    words = re.sub(r"[^a-z0-9\s]", " ", t).split()
    keep = [w for w in words if w not in _CARD_STOP and len(w) > 1]
    return "-".join((keep or words)[:2])


def _assign_slugs(events: list[dict]) -> None:
    """Give every event a unique `slug` in place. Collisions get -2, -3, … in a
    stable order (by start then title) so a given event keeps its slug run to run."""
    seen: dict[str, int] = {}
    for e in sorted(events, key=lambda e: (e.get("start", ""), e.get("title", ""))):
        base = _card_slug(e.get("title", "")) or (e.get("fingerprint", "") or "event")[:8]
        n = seen.get(base, 0) + 1
        seen[base] = n
        e["slug"] = base if n == 1 else f"{base}-{n}"


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
    events = _collapse_overlaps([_row_to_dict(r) for r in rows])
    for e in events:                      # no em dashes in any displayed title
        e["title"] = _clean_title(e.get("title", ""))
    _assign_slugs(events)                 # stable, unique short link per event
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

    # AI poster reader endpoint. Explicit POSTER_AI_URL wins; otherwise, if
    # Supabase is configured, default to its read-poster function so deploying the
    # function is all it takes to switch the snap-a-flyer from on-device OCR to AI.
    # Empty string -> the form keeps using in-browser OCR only.
    poster_ai_url = os.environ.get("POSTER_AI_URL", "")
    poster_ai_key = os.environ.get("POSTER_AI_KEY", "")
    if not poster_ai_url and SUPABASE_URL and SUPABASE_ANON_KEY:
        poster_ai_url = f"{SUPABASE_URL}/functions/v1/read-poster"
        poster_ai_key = SUPABASE_ANON_KEY

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
        canonical_host=_canonical_host(),
        poster_ai_url=poster_ai_url,
        poster_ai_key=poster_ai_key,
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
