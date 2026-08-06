"""anthéa, Antipolis Théâtre d'Antibes — the whole season from one page.

anthéa is one of the largest theatres in the 06 and none of its programme was
reaching the site. The season calendar is server-rendered and carries all ten
months in a single document:

    <span class="enveloppe__number">2026</span>
    <span class="enveloppedate__title">septembre</span>
    ...
    <li class="card">
      <a class="card__link" href="/fr/spectacles/saison-2026-2027/tout-le-theatre/la-tresse">
      <h3 class="card__spectacle_title">La Tresse</h3>
      <p class="card__description">Un chef-d'œuvre de vie et de survie</p>
      <p class="card__dates">10, 11 et 12 septembre</p>

Three things make this worth its own file rather than a harvest URL:

1. **No JSON-LD and no .ics.** Checked on the live page: zero
   `application/ld+json` blocks and no calendar feed, so the generic harvest
   engine has nothing to read. This is a DOM scrape or nothing.

2. **One card is many nights.** "10, 11 et 12 septembre" is three performances.
   People book a night, not a run, so each date becomes its own Event and the
   build decides how to display them.

3. **The year lives in the month heading, not the card.** A season straddles New
   Year: "12 janvier" under the janvier heading is 2027 while "10 septembre" is
   2026. The card's own date line never says which. So we walk in DOCUMENT ORDER
   and carry the heading down onto the cards beneath it — see niceevents/dom.py
   for why css("span, li") would silently date the entire season to June.

Date lines are messier than they look. Real examples from the live page:

    "29 septembre"                     one night
    "1er, 2 et 3 décembre"             "1er" is the 1st
    "8, 9, 11 et 12 décembre"          a gap mid-run
    "3 et 17 avril. 22 mai. 12 juin"   three months in one line

The last shape is why days are attributed to the month that FOLLOWS them rather
than to a single month parsed from the whole string. That same card is printed
again under its later month sections, so identical events arrive twice and are
deduplicated on fingerprint before they leave the scraper.

Start times are NOT on the calendar; they sit on each show's own page (usually
20h00 or 20h30, but not always). We leave `time` unset rather than write a guess:
a missing time is honest, a wrong one sends someone an hour early.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..dom import in_order
from ..models import _safe_date, category_from_type, strip_accents
from ..models import Event
from .base import HttpScraper, register

BASE = "https://www.anthea-antibes.fr"
CALENDAR = f"{BASE}/fr/calendrier"

VENUE = "anthéa, Antipolis Théâtre d'Antibes"
TOWN = "Antibes"

_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}
#: Accent-tolerant on purpose. The page writes "décembre" and "février" with
#: accents; matching on the plain dict keys silently found no month at all and
#: the card yielded nothing — a scraper returning zero rather than crashing.
#: Matched text is accent-stripped before the dict lookup.
_MONTH_RE = re.compile(
    r"janvier|f[ée]vrier|mars|avril|mai|juin|juillet|ao[uû]t|"
    r"septembre|octobre|novembre|d[ée]cembre", re.I)

#: A season is labelled "2026-2027": September onwards is the first year, January
#: onwards the second. Used only if a card somehow has no heading above it.
_SEASON_SPLIT_MONTH = 9


def _days(segment: str) -> list[int]:
    """The day numbers in the text that precedes a month name.

    "1er, 2 et 3" -> [1, 2, 3].  "du 10 au 12" -> [10, 11, 12].
    """
    seg = re.sub(r"\b1\s*er\b", "1", segment, flags=re.I)
    m = re.search(r"\bdu\s+(\d{1,2})\s+au\s+(\d{1,2})\b", seg, re.I)
    if m and int(m[1]) <= int(m[2]):
        return list(range(int(m[1]), int(m[2]) + 1))
    return [int(n) for n in re.findall(r"\b(\d{1,2})\b", seg) if 1 <= int(n) <= 31]


def parse_dates(text: str, year: Optional[int] = None,
                season_start: Optional[int] = None) -> list[date]:
    """Every performance date in a card's date line.

    Days bind to the month that FOLLOWS them, so "3 et 17 avril. 22 mai" yields
    3 and 17 April plus 22 May instead of collapsing onto one month.
    """
    out: list[date] = []
    cursor = 0
    previous_month: Optional[int] = None
    rollover = 0
    for m in _MONTH_RE.finditer(text or ""):
        segment = text[cursor:m.start()]
        cursor = m.end()
        month = _MONTHS[strip_accents(m.group(0)).lower()]
        # "30 et 31 décembre. 2 janvier" is one run across New Year. Months only
        # ever move forward within a date line, so a month that goes BACKWARDS is
        # the next year, not a typo. Without this the January dates would be filed
        # a year early and quietly sort to the top of the site.
        if previous_month is not None and month < previous_month:
            rollover += 1
        previous_month = month
        y = (year or _season_year(month, season_start)) + rollover
        for d in _days(segment):
            got = _safe_date(y, month, d)
            if got:
                out.append(got)
    return out


def _season_year(month: int, season_start: Optional[int]) -> int:
    """Fallback year when no month heading was seen above the card."""
    if season_start is None:
        today = date.today()
        season_start = today.year if today.month >= _SEASON_SPLIT_MONTH else today.year - 1
    return season_start if month >= _SEASON_SPLIT_MONTH else season_start + 1


def _classes(node) -> set[str]:
    return set((node.attributes.get("class") or "").split())


@register
class Anthea(HttpScraper):
    name = "anthea"
    label = "anthéa (Antibes)"
    delay = 1.0
    #: The calendar page carries the entire season in one document, so a
    #: performance that vanishes from a date has been rescheduled, not paged out.
    reconciles_dates = True

    def fetch(self) -> Iterator[Event]:
        r = self.get(CALENDAR)
        if not r:
            return
        seen: set[str] = set()
        for ev in self._parse(r.text):
            if ev.fingerprint in seen:
                continue                       # a show reprinted under a later month
            seen.add(ev.fingerprint)
            yield ev

    def _parse(self, html: str) -> Iterator[Event]:
        tree = HTMLParser(html)
        year: Optional[int] = None
        season_start: Optional[int] = None

        # MUST be document order — see niceevents/dom.py. css("span, li") returns
        # every heading before the first card, which would date the whole season
        # to the last month on the page.
        for node in in_order(tree, {"span", "li"}):
            cls = _classes(node)

            if "enveloppe__number" in cls:
                text = (node.text() or "").strip()
                if re.fullmatch(r"\d{4}", text):
                    year = int(text)
                    season_start = season_start or year
                continue

            if "card" not in cls:
                continue

            yield from self._card(node, year, season_start)

    def _card(self, node, year, season_start) -> Iterator[Event]:
        title_el = node.css_first(".card__spectacle_title")
        dates_el = node.css_first(".card__dates")
        if title_el is None or dates_el is None:
            return
        title = re.sub(r"\s+", " ", (title_el.text() or "")).strip()
        if not title:
            return

        raw_dates = re.sub(r"\s+", " ", (dates_el.text() or "")).strip()
        dates = parse_dates(raw_dates, year, season_start)
        if not dates:
            return

        desc_el = node.css_first(".card__description")
        note = re.sub(r"\s+", " ", (desc_el.text() or "")).strip() if desc_el else None

        link = node.css_first("a.card__link")
        href = (link.attributes.get("href") if link else None) or CALENDAR
        url = href if href.startswith("http") else BASE + href

        # The site files each show under a section of its own ("tout-le-theatre",
        # "privilege-spectacle-vivant"). That is the venue's own type label, so it
        # beats guessing from the title. Everything here is live performance, so
        # an unrecognised section falls back to the stage category rather than to
        # the generic "autre" bucket.
        section = url.rstrip("/").split("/")[-2].replace("-", " ")
        category = category_from_type(section) or "scene"

        for when in dates:
            yield Event(
                title=title,
                start=when,
                town=TOWN,
                venue=VENUE,
                category=category,
                url=url,
                note=note or None,
                source=self.name,
            )
