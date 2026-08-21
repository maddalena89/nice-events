"""Town and category landing pages.

WHY THESE EXIST
---------------
The site is one page. That page is good at being a page and hopeless at being
found: there is exactly one URL, so there is exactly one thing Google can rank,
and it has to rank for everything at once. Nobody searches "what's on in Nice
and the Alpes-Maritimes" — they search "brocante Antibes", "que faire à Nice ce
week-end", "milonga Nice". A query like that needs a page *about* that, and
until now none existed.

So: one page per town and one per category, each with its own title, heading,
description, canonical URL and structured data, listing the real events and
linking back to the app. They are rendered as plain server-side HTML rather than
the app's JavaScript feed — a crawler reads the listings on the first visit
without having to execute anything.

Deliberately NOT a page per town-and-category pair. That is 33 x 11 = 363 mostly
empty combinations, and a wall of near-identical thin pages is the classic
doorway-page pattern search engines penalise. Towns and categories separately
are real pages with real content on them.

The whole thing is derived from the same event dicts the home page renders, so
a listing can never say one thing here and another there.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .models import DISPLAY_CATEGORIES, slugify

#: A town needs at least this many upcoming events to earn a page. Below it the
#: page would be two lines of content — thin, unrankable, and a slightly spammy
#: signal in bulk. Those towns stay findable via the home page filter.
MIN_TOWN_EVENTS = 5

#: Landing pages cover the near future only. "What's on in Antibes" answering
#: with something 18 months out is not what the question meant, and the whole
#: page stays small enough to load instantly.
WINDOW_DAYS = 90

#: Hard ceiling per page, after the window. Only Nice ever reaches it.
MAX_ROWS = 250

#: How many of those rows get schema.org markup. Marking up all 250 put 149KB of
#: JSON-LD on the Nice page — more bytes than the page itself, for diminishing
#: return: search engines surface a handful of events from any one page. The
#: capped set is the FIRST rows, i.e. the soonest events, which are the ones
#: worth surfacing. Marking up a subset of what is visible is fine; the rule
#: that matters is never marking up something that is NOT on the page.
MAX_JSONLD = 100

#: Words that mean "this is a building, not a commune". Some sources publish only
#: a venue in their location line, so a venue name reaches us in `town` and would
#: otherwise earn a landing page headed "What's on in Espace Laure Ecard".
#: Scrapers fix this at source where they can (see scrapers/departement06.py);
#: this is the backstop, and it only ever costs a landing page, never a listing.
_VENUE_WORDS = {
    "espace", "salle", "theatre", "théâtre", "centre", "center", "parc", "musee",
    "musée", "chateau", "château", "palais", "stade", "mediatheque", "médiathèque",
    "bibliotheque", "bibliothèque", "complexe", "halle", "gymnase", "chapelle",
    "eglise", "église", "ecole", "école", "villa", "domaine", "hotel", "hôtel",
    "cinema", "cinéma", "galerie", "conservatoire", "auditorium", "forum", "stand",
}


def _looks_like_commune(town: str) -> bool:
    """True unless the name is obviously a building rather than a place.

    Only the FIRST word is tested. Communes here really are called things like
    "Villeneuve-Loubet" and "La Colmiane", and a commune whose name merely
    contains one of these words mid-string ("Saint-Martin-du-Var") must not be
    thrown away — but nothing in the 06 is a commune *beginning* with "Salle" or
    "Espace".
    """
    first = slugify(town).split("-")[0]
    return bool(first) and first not in {slugify(w) for w in _VENUE_WORDS}

#: The French phrasing for each category — the words people round here actually
#: type. These go in the visible copy and the meta description, not into a
#: hidden keyword dump: same words, honest placement.
CAT_FR = {
    "marche": "brocantes, vide-greniers et fêtes de village",
    "danse": "tango, milongas et soirées danse",
    "concert": "concerts et musique live",
    "expo": "expositions et musées",
    "scene": "théâtre et spectacles",
    "visite": "visites guidées et patrimoine",
    "atelier": "ateliers et stages",
    "business": "conférences tech, IA et business",
    "social": "rencontres et soirées expat",
    "sport": "sport et courses",
    "autre": "clubs, soirées et le reste",
}

#: URL slug per category. Fixed and readable rather than derived, because these
#: are public URLs: renaming a category label must not silently move a page that
#: search engines have already indexed.
CAT_SLUG = {
    "marche": "brocantes-and-fetes",
    "danse": "tango-and-dance",
    "concert": "concerts",
    "expo": "exhibitions",
    "scene": "stage-and-theatre",
    "visite": "guided-visits",
    "atelier": "workshops",
    "business": "business-tech-and-ai",
    "social": "social-and-expat",
    "sport": "sport",
    "autre": "clubs-and-other",
}

#: Path segments a generated page owns. Event short links (whatsonnice.com/<slug>)
#: live in the same root namespace, so an event whose title slugified to
#: "concerts" would be shadowed by the category page and its short link would
#: quietly stop working. site.py feeds this to _assign_slugs to keep them apart.
RESERVED_SLUGS = set(CAT_SLUG.values()) | {"in", "privacy", "sitemap", "robots"}


def _fmt_day(d: date) -> str:
    day = d.strftime("%-d") if hasattr(d, "strftime") else str(d.day)
    return f"{d.strftime('%A')} {day} {d.strftime('%B')}"


def _fmt_until(end: str | None) -> str:
    """"until 5 Oct" for a run with a closing date, "on now" for an open-ended
    one. A bare "until" with nothing after it is what the column showed before,
    and it reads like a truncated sentence."""
    if not end:
        return "on now"
    d = date.fromisoformat(end)
    day = d.strftime("%-d") if os.name != "nt" else d.strftime("%d")
    return f"until {day} {d.strftime('%b')}"


def _display_cat(e: dict) -> str:
    """Home page folds "brocante" into "marche"; _row_to_dict has already done
    that remap by the time we see these dicts, but be defensive — a stray
    "brocante" here would silently vanish from every category page."""
    c = e.get("category") or "autre"
    return "marche" if c == "brocante" else c


def _split_ongoing(events: list[dict], today: str) -> tuple[list[dict], list[dict]]:
    """Separate "already running" from "starts later".

    A three-week exhibition that opened in June is still on today, but bucketing
    it under its start date puts a June heading at the top of a page about what
    is on now — which reads as a stale page, and buries the things that have not
    started yet. The home page solves this with its own standing-exhibitions
    section; this is the same idea in a plainer shape.
    """
    ongoing = [e for e in events if e["start"] < today]
    # Soonest to close first: "catch it before it goes" is the useful order for
    # a run that is already open. Copied, never mutated — these dicts are the
    # same objects the home page renders.
    ongoing.sort(key=lambda e: (e.get("end") or e["start"], e.get("title", "")))
    ongoing = [{**e, "until": _fmt_until(e.get("end"))} for e in ongoing]
    return ongoing, [e for e in events if e["start"] >= today]


def _group_by_day(events: list[dict]) -> list[tuple[dict, list[dict]]]:
    """Group into (day, events) in date order, using each event's start date.

    Multi-day runs are listed once, on the day they open — not stamped onto
    every date they cover. A three-week exhibition repeated across 21 headings
    is what made the old feed unreadable.
    """
    buckets: dict[str, list[dict]] = {}
    for e in events:
        buckets.setdefault(e["start"], []).append(e)
    out = []
    for iso in sorted(buckets):
        d = date.fromisoformat(iso)
        items = sorted(buckets[iso], key=lambda e: (e.get("time") or "99:99", e.get("title", "")))
        out.append(({"label": _fmt_day(d), "year": d.strftime("%Y")}, items))
    return out


def _event_ld(e: dict, base: str) -> dict:
    """One schema.org Event. Mirrors site._event_ld's shape deliberately: two
    different descriptions of the same event in two different vocabularies is
    how you end up with Google trusting neither."""
    ld: dict = {
        "@type": "Event",
        "name": e.get("title", ""),
        "startDate": e["start"],
        "eventStatus": "https://schema.org/EventCancelled" if e.get("cancelled")
                       else "https://schema.org/EventScheduled",
        "eventAttendanceMode": "https://schema.org/OfflineEventAttendanceMode",
        "location": {
            "@type": "Place",
            "name": e.get("venue") or e.get("town") or "Alpes-Maritimes",
            "address": {
                "@type": "PostalAddress",
                "addressLocality": e.get("town") or "Nice",
                "addressRegion": "Alpes-Maritimes",
                "addressCountry": "FR",
            },
        },
    }
    if e.get("end") and e["end"] != e["start"]:
        ld["endDate"] = e["end"]
    if e.get("note"):
        ld["description"] = e["note"]
    if e.get("free"):
        ld["isAccessibleForFree"] = True
    if base and e.get("slug"):
        ld["url"] = f"{base}/?e={e['slug']}"
    return ld


def _page_ld(page_url: str, name: str, description: str, events: list[dict], base: str) -> str:
    """An ItemList describing this page, with the events inline as list items.

    ItemList rather than a bare array of Events because that is what this page
    IS — an ordered list of things, in a stated order. It also gives the events
    a position, which is the difference between "here are some events" and "here
    is the 3rd of 40 events on this page".
    """
    doc = {
        "@context": "https://schema.org",
        "@type": "ItemList",
        "name": name,
        "description": description,
        "url": page_url,
        "numberOfItems": len(events),
        "itemListOrder": "https://schema.org/ItemListOrderAscending",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "item": _event_ld(e, base)}
            for i, e in enumerate(events, 1)
        ],
    }
    blob = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
    # Same escaping as site.py: a "</script>" inside any title would otherwise
    # close this block early and spill JSON onto the page.
    return blob.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _plural(n: int, one: str, many: str) -> str:
    return one if n == 1 else many


def collect(events: list[dict]) -> tuple[list[dict], list[dict]]:
    """Work out which town and category pages to build, biggest first.

    Only non-online events count towards a town: "Online" is a format, not a
    place, and a town page for it would be nonsense.
    """
    horizon = (date.today() + timedelta(days=WINDOW_DAYS)).isoformat()
    live = [e for e in events if e.get("start", "") <= horizon]

    towns: dict[str, list[dict]] = {}
    for e in live:
        if e.get("online"):
            continue
        towns.setdefault(e["town"], []).append(e)

    cats: dict[str, list[dict]] = {}
    for e in live:
        cats.setdefault(_display_cat(e), []).append(e)

    town_pages = [
        {"kind": "town", "key": t, "name": t, "path": f"/in/{slugify(t)}/", "events": evs}
        for t, evs in towns.items()
        if len(evs) >= MIN_TOWN_EVENTS and slugify(t) and _looks_like_commune(t)
    ]
    town_pages.sort(key=lambda p: (-len(p["events"]), p["name"]))

    cat_pages = [
        {"kind": "cat", "key": k, "name": DISPLAY_CATEGORIES.get(k, k),
         "path": f"/{CAT_SLUG[k]}/", "events": evs}
        for k, evs in cats.items()
        if k in CAT_SLUG
    ]
    cat_pages.sort(key=lambda p: (-len(p["events"]), p["name"]))
    return town_pages, cat_pages


#: How many town links to show in a cross-link block. A footer listing all 31
#: dilutes every one of them and starts to read as a link farm; the busiest
#: dozen are the ones anyone actually wants, and the rest stay one hop away via
#: any landing page's own "By town" list.
NAV_TOWNS = 12


def nav_links(town_pages: list[dict], cat_pages: list[dict], limit: int = NAV_TOWNS):
    """The cross-link lists, shared by the home page and every landing page.

    Returned rather than rendered so the home page can link to these pages too:
    a page nothing links to is one search engines discover late and value little,
    and a sitemap entry alone is a weak substitute for a real link.
    """
    towns = [{"path": p["path"], "name": p["name"], "count": len(p["events"])}
             for p in town_pages[:limit]]
    cats = [{"path": p["path"], "name": p["name"], "count": len(p["events"])}
            for p in cat_pages]
    return towns, cats


def _copy_for(page: dict, total_towns: int) -> dict:
    """Title, heading and description. Written per kind rather than from one
    template string, because "Concerts in Nice & the 06" and "What's on in
    Antibes" are different sentences and a shared format makes both worse."""
    n = len(page["events"])
    if page["kind"] == "town":
        town = page["name"]
        return {
            "title": f"What's on in {town} · events, concerts & brocantes · What's on in Nice",
            "description": (
                f"{n} {_plural(n, 'event', 'events')} coming up in {town} — concerts, "
                f"brocantes, exhibitions, markets and more. Que faire à {town} : "
                f"l'agenda complet, mis à jour chaque jour."
            ),
            "h1_pre": "What's on in ", "h1_em": town,
            "lede": (
                f"Everything happening in {town} over the next {WINDOW_DAYS} days — "
                f"gathered daily from the places that actually list it, and always "
                f"linked back to the source."
            ),
            "lede_fr": f"Que faire à {town} ? L'agenda des événements, sorties et brocantes.",
        }
    label = page["name"]
    fr = CAT_FR.get(page["key"], "")
    return {
        "title": f"{label} in Nice & the Alpes-Maritimes · What's on in Nice",
        "description": (
            f"{n} upcoming {label.lower()} across Nice, Antibes and the 06 "
            f"({fr}) — updated daily, always linked to the source."
        ),
        "h1_pre": "", "h1_em": label,
        "lede": (
            f"{label} across Nice and the Alpes-Maritimes over the next "
            f"{WINDOW_DAYS} days, gathered daily from {total_towns} towns."
        ),
        "lede_fr": f"Les {fr} à Nice et dans les Alpes-Maritimes.",
    }


def _env(tpl_dir: Path) -> Environment:
    """A Jinja environment with autoescape genuinely ON.

    Not shared with site.py's, which builds the app page and must NOT autoescape:
    that template injects a JSON blob and a pile of inline JavaScript, and
    escaping those breaks the page. Note site.py asks for
    select_autoescape(["html"]) and does not get it — that helper reads the LAST
    extension, which for "index.html.jinja" is "jinja", so it resolves to False.
    Easy to misread as "escaping is on here", so it is worth being explicit:
    these pages interpolate scraped titles, venue names and descriptions straight
    into HTML, and that text is third-party input. It gets escaped.
    """
    return Environment(loader=FileSystemLoader(str(tpl_dir)), autoescape=True)


def render_all(tpl_dir: Path, town_pages: list[dict], cat_pages: list[dict],
               base: str, updated: str, og_image: str, out: Path) -> list[str]:
    """Write every landing page. Returns the site-root paths written.

    Takes the page lists rather than calling collect() itself so the caller can
    use the same lists for the home page's cross-links — computing them twice
    invites the two from drifting apart.
    """
    if not town_pages and not cat_pages:
        return []

    tpl = _env(tpl_dir).get_template("landing.html.jinja")
    # Landing pages link to more towns than the home page footer does: someone
    # already on /in/vence/ is browsing by place, so a fuller list is useful
    # there rather than noise.
    town_links, cat_links = nav_links(town_pages, cat_pages, limit=24)

    written = []
    for page in town_pages + cat_pages:
        evs = sorted(page["events"], key=lambda e: (e["start"], e.get("time") or "99:99",
                                                    e.get("title", "")))
        truncated = len(evs) > MAX_ROWS
        shown = evs[:MAX_ROWS]
        ongoing, upcoming = _split_ongoing(shown, date.today().isoformat())
        copy = _copy_for(page, len(town_pages))
        url = f"{base}{page['path']}" if base else page["path"]
        ctx = {
            **copy,
            "path": page["path"],
            "url": url,
            "count": len(page["events"]),
            "window_note": f"next {WINDOW_DAYS} days",
            "window_days": WINDOW_DAYS,
            "truncated": truncated,
            "ongoing": ongoing,
            "days": _group_by_day(upcoming),
            # Structured data covers exactly the rows rendered below, never the
            # ones trimmed off — marking up events a visitor cannot see on the
            # page is precisely what "structured data mismatch" penalties are for.
            "jsonld": _page_ld(url, copy["title"], copy["description"],
                               shown[:MAX_JSONLD], base),
        }
        html = tpl.render(page=ctx, town_links=town_links, cat_links=cat_links,
                          updated=updated, og_image=og_image)
        dest = out / page["path"].strip("/") / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(html, encoding="utf-8")
        written.append(page["path"])
    return written
