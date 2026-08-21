"""Département des Alpes-Maritimes — the official 06 cultural agenda.

Drupal 10 site at departement06.fr/agenda. This is where the department's own
free programme lives: the Soirées Estivales (a different open-air concert in a
different village nearly every summer night), Jazz Art Lympia, Le Festival des
Mots, planetarium shows and more. One of the biggest event sources in the 06,
and every single night is its own listing with a real date, place and act.

The listing pages carry everything we need, so we never fetch the ~200 detail
pages: each card has the title, the festival + genre (as category chips), the
place, and machine-readable <time datetime> for the date(s) and start time.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, canon_town, classify, is_nonevent, strip_accents
from .base import HttpScraper, register

log = logging.getLogger(__name__)

BASE = "https://www.departement06.fr"
AGENDA = BASE + "/agenda"

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_HHMM = re.compile(r"^\d{1,2}:\d{2}$")

# Category chips that are service/accessibility tags, not a genre. Kept out of
# the note so it reads "festival · genre", not "... · Accessible PMR".
_SKIP_CHIPS = {"accessible pmr", "gratuit"}

# A few departmental venues publish only the venue name in the "Lieu :" line,
# with no commune, so the town field would otherwise carry venue text. Map the
# venue (matched as an accent-folded substring) to its commune. Keep this small
# and only add entries whose commune is certain.
_VENUE_COMMUNE = {
    "maison departementale de l'environnement": "Nice",  # the DOME, Parc Phoenix
    "dome": "Nice",
    # 50 bd Saint-Roch, 06300 Nice — confirmed against the departement's own
    # directory. The agenda page for these events names the hall and no commune,
    # so without this its ~9 events land under a town called "Espace Laure Ecard".
    "espace laure ecard": "Nice",
}


def _commune_from_lieu(lieu: str) -> str:
    """Resolve the commune for the town field, keeping venue text out of it.

    The "Lieu :" line is one of: "Commune - Venue" (take the commune), a bare
    commune, or — for a handful of departmental venues — only the venue name.
    Take the part before " - " as the commune candidate, map the venue-only names
    explicitly, and canon the rest. canon_town echoes an unknown string
    unchanged, which is right for a real commune we simply have not listed but
    would re-pollute town for a pure venue name, so those must live in the map.
    """
    if not lieu:
        return "Alpes-Maritimes"
    low = strip_accents(lieu).lower()
    for key, commune in _VENUE_COMMUNE.items():
        if key in low:
            return commune
    return canon_town(lieu.split(" - ", 1)[0].strip())


@register
class Departement06(HttpScraper):
    name = "departement06"
    label = "Département 06"
    delay = 0.6
    #: Safety cap. There are ~18 pages today; we stop as soon as a page is
    #: empty or brings nothing new, so the cap almost never bites.
    MAX_PAGES = 30

    def fetch(self) -> Iterator[Event]:
        today = date.today()
        seen: set[str] = set()
        for page in range(self.MAX_PAGES):
            r = self.get(f"{AGENDA}?page={page}")
            if not r:
                break
            cards = HTMLParser(r.text).css(".event-item__wrap")
            if not cards:
                break
            any_new = False
            for card in cards:
                ev = self._event_from(card, today)
                if ev is None:
                    continue
                key = ev.url or f"{ev.title}|{ev.start.isoformat()}"
                if key in seen:
                    continue
                seen.add(key)
                any_new = True
                yield ev
            if not any_new:            # a page of only-seen / past events: done
                break

    def _event_from(self, card, today: date) -> Optional[Event]:
        a = card.css_first("a.event-item__title-link")
        if not a:
            return None
        title = re.sub(r"\s+", " ", a.text()).strip()
        if not title or is_nonevent(title):
            return None
        href = a.attributes.get("href") or ""
        url = BASE + href if href.startswith("/") else (href or None)

        # Dates + start time come from <time datetime="...">: ISO dates for the
        # day(s), HH:MM for the start hour. A range renders two date elements.
        dts = [t.attributes.get("datetime") or "" for t in card.css("time")]
        dates = [d for d in dts if _ISO_DATE.match(d)]
        times = [d for d in dts if _HHMM.match(d)]
        if not dates:
            return None
        start = date.fromisoformat(dates[0])
        end = date.fromisoformat(dates[-1]) if len(dates) > 1 and dates[-1] != dates[0] else None
        if (end or start) < today:                 # season passed
            return None
        t = times[0] if times else None

        # "Lieu :" line. For the Soirées Estivales it's the village (a real
        # commune); for a few departmental venues it's the venue name.
        place_el = card.css_first(".time-place__item.is-place")
        lieu = ""
        if place_el:
            lieu = re.sub(r"\s+", " ", place_el.text()).replace("Lieu :", "").strip()

        # Category chips: festival name(s) + genre. First ones name the festival
        # ("Les Soirées Estivales", "Jazz Art Lympia", "Le Festival des Mots"),
        # which is exactly the context a reader wants on the row.
        raw_chips = [re.sub(r"[,\s]+$", "", c.text().strip())
                     for c in card.css("a.event-item__category")]
        low = " ".join(raw_chips).lower()
        free = ("gratuit" in low) or ("soir" in low and "estival" in low)
        chips = [c for c in raw_chips if c and c.lower() not in _SKIP_CHIPS]
        note = " · ".join(chips[:2]) or None

        return Event(
            title=title,
            start=start,
            end=end,
            time=t,
            town=_commune_from_lieu(lieu),
            venue=lieu or None,
            category=classify(title, " ".join(chips)),
            url=url,
            note=note,
            free=free,
            source=self.name,
        )
