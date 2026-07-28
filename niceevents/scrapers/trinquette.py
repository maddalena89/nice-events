"""La Trinquette Jazz Club — the Villefranche-sur-Mer jazz club.

A real jazz club that programmes a different act nearly every night from
February to November: 18 to 20 concerts a month, each its own date, act and
ticket. Maddalena used to copy these off the printed monthly flyer by hand;
this scraper does exactly that job automatically.

The site is built with Nicepage. The homepage lists the upcoming programme in
static markup — one block per night, a French date line ("VENDREDI 31 JUILLET
2026 21H") followed by the artist name and, for most nights, a Billetweb
reservation link. Rather than lean on Nicepage's generated CSS classes (which
change whenever the club re-exports the site), we read the date lines by their
printed pattern and pair each act to its ticket link by slug. That survives a
redesign as long as the club keeps writing the dates the French way.

The club rolls the homepage forward, so this always reflects what is coming up
next; there is no need to page back through the season.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Iterator, List, Optional, Tuple

from selectolax.parser import HTMLParser

from ..models import Event, classify, is_nonevent, slugify
from .base import BrowserScraper, register

log = logging.getLogger(__name__)

HOME = "https://www.trinquettejazzclub.com/"
AGENDA = "https://www.trinquettejazzclub.com/AGENDA"

TOWN = "Villefranche-sur-Mer"
VENUE = "La Trinquette Jazz Club"
# Printed on every flyer: entrée 18€, tarif réduit 12€, moins de 25 ans 8€.
PRICE = "18€/12€"

_MONTHS = {
    "janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "septembre": 9, "octobre": 10, "novembre": 11,
    "decembre": 12,
}
_MONTH_ALT = "|".join(_MONTHS)

# "VENDREDI 31 JUILLET 2026 21H" — the weekday word is ignored (the site has
# had English typos like "SATURDAY"), the hour is optional.
_DATE_RE = re.compile(
    rf"\b(\d{{1,2}})\s+({_MONTH_ALT})\s+(20\d\d)(?:\s*(\d{{1,2}})\s*h)?",
    re.I,
)

# Lines that are buttons/labels, not an act name.
_SKIP_LINE = re.compile(
    r"^(je\s+reserve|reserver|reservation|billetterie|billetweb|infos?|"
    r"bar|restauration|entree|tarif|concert|agenda|accueil|contact)\b",
    re.I,
)


def _norm(s: str) -> str:
    """Accent-fold + lowercase + collapse spaces, for pattern matching."""
    import unicodedata
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", s).strip()


@register
class Trinquette(BrowserScraper):
    name = "trinquette"
    label = "La Trinquette Jazz Club"

    def fetch(self) -> Iterator[Event]:
        today = date.today()
        horizon = today + timedelta(days=400)
        seen: set[Tuple[str, str]] = set()
        for url in (HOME, AGENDA):
            html = self._page_text(url, scroll=3)
            if not html:
                continue
            for ev in self._parse(html):
                if ev.start < today or ev.start > horizon:
                    continue
                key = (_norm(ev.title).lower(), ev.start.isoformat())
                if key in seen:
                    continue
                seen.add(key)
                yield ev

    # -- parsing -----------------------------------------------------------

    def _parse(self, html: str) -> Iterator[Event]:
        tree = HTMLParser(html)
        body = tree.body or tree
        # Ordered, de-tagged lines of the page.
        text = body.text(separator="\n") if body else ""
        lines = [ln.strip() for ln in text.split("\n")]
        lines = [ln for ln in lines if ln]

        tickets = self._ticket_links(tree)

        i = 0
        n = len(lines)
        while i < n:
            m = _DATE_RE.search(_norm(lines[i]))
            if not m:
                i += 1
                continue
            start = self._to_date(m)
            if not start:
                i += 1
                continue
            hour = m.group(4)
            time = f"{int(hour):02d}:00" if hour else ("20:00" if start.weekday() == 6 else "21:00")

            # Title: the next line that isn't a button or another date line.
            title = ""
            j = i + 1
            while j < n and j <= i + 4:
                cand = lines[j]
                cn = _norm(cand)
                if _DATE_RE.search(cn):
                    break
                if _SKIP_LINE.match(cn) or len(cand) < 2:
                    j += 1
                    continue
                title = cand
                break
            if not title or is_nonevent(title):
                i += 1
                continue

            url = self._match_ticket(title, tickets) or HOME
            yield Event(
                title=re.sub(r"\s+", " ", title).strip(),
                start=start,
                time=time,
                town=TOWN,
                venue=VENUE,
                category=classify(title, "jazz concert"),
                url=url,
                note=f"{VENUE} · {PRICE}",
                free=False,
                source=self.name,
            )
            i = j + 1 if j > i else i + 1

    def _to_date(self, m) -> Optional[date]:
        try:
            day = int(m.group(1))
            month = _MONTHS[m.group(2).lower()]
            year = int(m.group(3))
            return date(year, month, day)
        except (ValueError, KeyError):
            return None

    def _ticket_links(self, tree) -> List[str]:
        out: List[str] = []
        for a in tree.css("a"):
            href = a.attributes.get("href") or ""
            if "billetweb" in href.lower():
                out.append(href)
        return out

    def _match_ticket(self, title: str, tickets: List[str]) -> Optional[str]:
        """Pair an act to its Billetweb link by comparing the title slug to the
        URL path. The club slugs the act name into the URL
        (e.g. 'Nina Papa Quartet' -> billetweb.fr/nina-papa-quartet-aout-2026)."""
        if not tickets:
            return None
        tslug = slugify(title)
        if not tslug:
            return None
        words = tslug.split("-")
        # Use the first few words as the fingerprint; short titles use all.
        stem = "-".join(words[: max(2, min(4, len(words)))])
        for href in tickets:
            hslug = slugify(href.split("billetweb")[-1])
            if stem and stem in hslug:
                return href
        # Fall back to a looser 2-word stem.
        stem2 = "-".join(words[:2])
        for href in tickets:
            if stem2 and stem2 in slugify(href):
                return href
        return None
