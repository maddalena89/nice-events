"""Generic venue harvester — one engine, many venues, no bespoke code.

Most venue websites already expose their programme in a machine-readable way,
they just don't advertise it:

  * schema.org/Event JSON-LD embedded in the page (Google needs it for rich
    results, so a surprising number of sites have it), or
  * an iCal (.ics) calendar feed (ticketing systems and Google-Calendar embeds
    hand these out freely).

Instead of writing a fragile scraper per venue, this reads either shape from a
plain list of URLs. Adding a venue becomes a one-line entry in VENUES — no new
code, no new tests. That is the whole point: it turns "write a scraper" into
"paste a URL".

Each URL is independent: one that 404s, changes shape, or serves junk is logged
and skipped. A broken venue can never take the others down.

Finding feeds (for whoever curates VENUES):
  * JSON-LD: view-source, search for `application/ld+json` and `"@type":"Event"`.
  * iCal:   look for a link ending .ics, or "S'abonner au calendrier".
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, canon_town, classify
from .base import HttpScraper, register

log = logging.getLogger(__name__)

# (name, url, kind). kind is "jsonld" (an HTML page to scan) or "ics" (a feed).
# Seeded thin ON PURPOSE and marked UNVERIFIED: the engine below is tested with
# fixtures, but which of these actually expose a feed can only be learned from a
# real run. Prune the ones that come back empty; add ones you find.
VENUES: list[tuple[str, str, str]] = [
    # ("Théâtre National de Nice", "https://www.tnn.fr/fr/calendrier", "jsonld"),
    # ("Opéra de Nice",            "https://www.opera-nice.org/fr/agenda", "jsonld"),
    # ("CEDAC de Cimiez",          "https://.../agenda.ics",              "ics"),
]


# ------------------------------------------------------------------ JSON-LD
def _walk_jsonld(node) -> Iterator[dict]:
    """Yield every dict in a parsed JSON-LD blob (handles @graph, arrays, nesting)."""
    if isinstance(node, list):
        for x in node:
            yield from _walk_jsonld(x)
    elif isinstance(node, dict):
        yield node
        if "@graph" in node:
            yield from _walk_jsonld(node["@graph"])


def _is_event_type(t) -> bool:
    # @type may be "Event", a subtype ("MusicEvent", "TheaterEvent", "Festival"),
    # or a list of them.
    vals = t if isinstance(t, list) else [t]
    return any(isinstance(v, str) and v.endswith("Event") or v in
               ("Festival", "ExhibitionEvent") for v in vals)


def _loc(obj: dict) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(venue_name, city, postcode) from a schema.org location, which may be a
    string, a Place, or a list of them."""
    loc = obj.get("location")
    if isinstance(loc, list):
        loc = loc[0] if loc else None
    if isinstance(loc, str):
        return loc.strip() or None, None, None
    if isinstance(loc, dict):
        name = (loc.get("name") or "").strip() or None
        addr = loc.get("address")
        if isinstance(addr, dict):
            return (name,
                    (addr.get("addressLocality") or "").strip() or None,
                    (addr.get("postalCode") or "").strip() or None)
        return name, None, None
    return None, None, None


def _clean(v) -> str:
    if isinstance(v, list):
        v = " ".join(str(x) for x in v)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", str(v or ""))).strip()


def _events_from_jsonld(html: str) -> Iterator[dict]:
    tree = HTMLParser(html)
    for tag in tree.css('script[type="application/ld+json"]'):
        raw = tag.text() or ""
        if "Event" not in raw:            # cheap pre-filter
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        for obj in _walk_jsonld(data):
            if _is_event_type(obj.get("@type")):
                yield obj


# ---------------------------------------------------------------------- iCal
def _unfold_ics(text: str) -> list[str]:
    """RFC 5545 line unfolding: a leading space/tab continues the previous line."""
    out: list[str] = []
    for line in text.replace("\r\n", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def _ics_prop(line: str) -> tuple[str, str]:
    # "DTSTART;TZID=Europe/Paris:20260718T193000" -> ("DTSTART", "20260718T193000")
    key, _, val = line.partition(":")
    return key.split(";", 1)[0].upper(), val.strip()


def _ics_date(val: str) -> Optional[date]:
    m = re.match(r"(\d{4})(\d{2})(\d{2})", val)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _ics_time(val: str) -> Optional[str]:
    m = re.match(r"\d{8}T(\d{2})(\d{2})", val)
    if m and (m[1], m[2]) != ("00", "00"):
        return f"{m[1]}:{m[2]}"
    return None


def _events_from_ics(text: str) -> Iterator[dict]:
    cur: Optional[dict] = None
    for line in _unfold_ics(text):
        u = line.strip().upper()
        if u == "BEGIN:VEVENT":
            cur = {}
        elif u == "END:VEVENT":
            if cur:
                yield cur
            cur = None
        elif cur is not None and ":" in line:
            key, val = _ics_prop(line)
            if key in ("SUMMARY", "DTSTART", "DTEND", "LOCATION", "URL", "DESCRIPTION"):
                # ICS escapes commas/semicolons/newlines with backslashes.
                cur[key] = (val.replace("\\,", ",").replace("\\;", ";")
                               .replace("\\n", " ").replace("\\N", " "))


@register
class VenueHarvest(HttpScraper):
    name = "harvest"
    label = "Venue calendars"
    delay = 1.0

    def fetch(self) -> Iterator[Event]:
        today = date.today()
        seen: set[str] = set()
        for name, url, kind in VENUES:
            try:
                yield from self._one(name, url, kind, today, seen)
            except Exception as e:                     # one venue must not sink the rest
                log.warning("%s: %s (%s) failed — %s", self.name, name, url, e)

    def _one(self, name, url, kind, today, seen) -> Iterator[Event]:
        r = self.get(url)
        if not r:
            return
        raws = (_events_from_ics(r.text) if kind == "ics"
                else _events_from_jsonld(r.text))
        for raw in raws:
            ev = (self._from_ics(raw, name, today) if kind == "ics"
                  else self._from_jsonld(raw, name, today))
            if ev and ev.fingerprint not in seen:
                seen.add(ev.fingerprint)
                yield ev

    # -- mappers -----------------------------------------------------------
    def _emit(self, *, title, start, end, time, venue, city, postcode, url, desc,
              fallback_venue, today) -> Optional[Event]:
        if not title or not start:
            return None
        if end and end < start:
            end = None
        if (end or start) < today:
            return None
        town = canon_town(city or None, postcode or None)
        if town == "Unknown":
            # No geo signal at all — assume it's the venue's town via its name,
            # else leave it out of a place-based site.
            town = canon_town(fallback_venue or None) if fallback_venue else "Unknown"
        venue = venue or fallback_venue
        return Event(
            title=title, start=start, end=end, time=time,
            town=town, venue=venue,
            category=classify(title, desc or "", venue or ""),
            url=url or None, note=(desc or None), source=self.name,
        )

    def _from_jsonld(self, o: dict, venue_name: str, today: date) -> Optional[Event]:
        from ..models import parse_date
        venue, city, pc = _loc(o)
        return self._emit(
            title=_clean(o.get("name")),
            start=parse_date(_clean(o.get("startDate"))),
            end=parse_date(_clean(o.get("endDate"))) if o.get("endDate") else None,
            time=_jsonld_time(o.get("startDate")),
            venue=venue, city=city, postcode=pc,
            url=_clean(o.get("url")), desc=_clean(o.get("description"))[:400],
            fallback_venue=venue_name, today=today,
        )

    def _from_ics(self, o: dict, venue_name: str, today: date) -> Optional[Event]:
        return self._emit(
            title=_clean(o.get("SUMMARY")),
            start=_ics_date(o.get("DTSTART", "")),
            end=_ics_date(o.get("DTEND", "")) if o.get("DTEND") else None,
            time=_ics_time(o.get("DTSTART", "")),
            venue=_clean(o.get("LOCATION")) or None, city=None, postcode=None,
            url=_clean(o.get("URL")), desc=_clean(o.get("DESCRIPTION"))[:400],
            fallback_venue=venue_name, today=today,
        )


def _jsonld_time(s) -> Optional[str]:
    s = str(s or "")
    m = re.search(r"T(\d{2}):(\d{2})", s)
    if m and (m[1], m[2]) != ("00", "00"):
        return f"{m[1]}:{m[2]}"
    return None
