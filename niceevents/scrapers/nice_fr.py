"""Ville de Nice — via the WordPress REST API.

The city runs WordPress and leaves /wp-json open, which is far better than
scraping /agenda/. ~1500 events with structured dates.

    GET /wp-json/wp/v2/events?per_page=100&page=N

Each item:
    title.rendered, link, excerpt.rendered
    acf.event_dates[] -> {start_date: "20260718", start_time: "20:00:00",
                          end_date, ticketing}
    acf.place         -> place ID, resolvable at /wp-json/wp/v2/place/{id}
    acf.free          -> bool
    event_types[]     -> taxonomy term IDs, resolvable at /wp-json/wp/v2/event_types

NOTE: the API sorts by *post* date, not event date, so we must page through
everything and filter ourselves.

Heads-up: the old open-data "agenda temps réel" feed (data.gouv, dataset
vdn-agenda-de-la-ville-de-nice-en-temps-reel) is DEAD — it 404s and was last
touched in 2020. Don't be tempted by it.
"""
from __future__ import annotations

import html
import logging
import re
from datetime import date
from typing import Iterator, Optional

from ..models import Event, category_from_type, classify, parse_date, parse_time
from .base import HttpScraper, register

log = logging.getLogger(__name__)

API = "https://www.nice.fr/wp-json/wp/v2"

# Repetitive municipal filler that drowns the listing. Skipped unless it's the
# only thing on. (Seniors' "cool down" drop-ins, ~15 identical entries a day.)
_FILLER = re.compile(r"pause fra[îi]cheur", re.I)


def _clean(s: Optional[str]) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


@register
class NiceFr(HttpScraper):
    name = "nice_fr"
    label = "Ville de Nice"
    delay = 0.8
    #: Safety cap only. The real page count comes from the X-WP-TotalPages
    #: header — a hardcoded 25 silently truncated the feed: the live response
    #: says X-Wp-Total: 3220 / X-Wp-Totalpages: 33, so we were dropping the
    #: last 8 pages (~800 events) without a word. Never trust a guessed cap
    #: over a number the server hands you.
    MAX_PAGES = 60

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self._places: dict[int, str] = {}
        self._types: dict[int, str] = {}

    # ---------------------------------------------------------- taxonomies
    def _load_types(self) -> None:
        r = self.get(f"{API}/event_types?per_page=100")
        if r:
            try:
                self._types = {t["id"]: _clean(t.get("name")) for t in r.json()}
            except Exception:
                pass

    def _place(self, pid: Optional[int]) -> Optional[str]:
        if not pid:
            return None
        if pid in self._places:
            return self._places[pid]
        r = self.get(f"{API}/place/{pid}")
        name = None
        if r:
            try:
                j = r.json()
                name = _clean(j.get("title", {}).get("rendered"))
                acf = j.get("acf") or {}
                addr = _clean(acf.get("address") or "")
                if addr:
                    name = f"{name} · {addr}" if name else addr
            except Exception:
                pass
        self._places[pid] = name
        return name

    # -------------------------------------------------------------- fetch
    def fetch(self) -> Iterator[Event]:
        self._load_types()
        today = date.today()
        seen: set[str] = set()

        total_pages: Optional[int] = None
        for page in range(1, self.MAX_PAGES + 1):
            r = self.get(f"{API}/events?per_page=100&page={page}")
            if not r:
                break
            try:
                items = r.json()
            except Exception:
                break
            if not items:
                break

            # Let the server tell us how far to go.
            if total_pages is None:
                try:
                    total_pages = int(r.headers.get("X-WP-TotalPages", 0)) or None
                except ValueError:
                    total_pages = None
                if total_pages and total_pages > self.MAX_PAGES:
                    log.warning("%s: %d pages available, capped at %d — raise MAX_PAGES",
                                self.name, total_pages, self.MAX_PAGES)

            for item in items:
                for ev in self._events_from(item, today):
                    if ev.fingerprint in seen:
                        continue
                    seen.add(ev.fingerprint)
                    yield ev

            # WP tells us the real page count; stop when we've had them all.
            total = r.headers.get("X-WP-TotalPages")
            if total and page >= int(total):
                break

    def _events_from(self, item: dict, today: date) -> Iterator[Event]:
        title = _clean(item.get("title", {}).get("rendered"))
        if not title or _FILLER.search(title):
            return

        acf = item.get("acf") or {}
        link = item.get("link")
        note_base = _clean(item.get("excerpt", {}).get("rendered"))
        venue = self._place(acf.get("place"))
        free = bool(acf.get("free"))
        type_name = " ".join(
            self._types.get(t, "") for t in (item.get("event_types") or [])
        ).strip()
        # Trust nice.fr's OWN type first ("Exposition", "Concert", "Atelier"…).
        # Only if it's unknown do we guess — and even then from title+type, NEVER
        # the description, which name-drops other categories ("l'univers de la
        # brocante", a jazz reference) and was scattering exhibitions into the
        # wrong tabs.
        cat = category_from_type(type_name) or classify(title, type_name)

        slots = acf.get("event_dates") or []
        for slot in slots:
            start = parse_date(str(slot.get("start_date") or ""))
            if not start:
                continue
            end = parse_date(str(slot.get("end_date") or "")) if slot.get("end_date") else None
            if (end or start) < today:
                continue

            t = parse_time(slot.get("start_time"))
            bits = [b for b in (t, type_name or None, note_base or None) if b]

            yield Event(
                title=title,
                start=start,
                end=end,
                time=t,
                town="Nice",
                venue=venue,
                category=cat,
                url=slot.get("ticketing") or link,
                note=" · ".join(bits)[:400] or None,
                free=free,
                source=self.name,
            )
