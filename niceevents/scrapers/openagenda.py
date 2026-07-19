"""OpenAgenda — the big one for culture.

Most French cultural venues — operas, national theatres, concert halls,
festivals, municipal culture services — publish their programme to OpenAgenda.
Rather than write a fragile bespoke scraper per venue (each with its own JS site
and ticketing subdomain), we read them all at once from the open, no-auth
mirror that Opendatasoft publishes:

    https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/
        evenements-publics-openagenda/records

This is where the Opéra de Nice, the TNN, the Conservatoire and — with luck —
the Nice Jazz Festival actually live in machine-readable form. One source,
potentially dozens of venues.

Two honest caveats, written down so nobody's surprised:
  * This was built against the API's documented shape, not verified against live
    06 data (the sandbox has no network to it). The first real run is the test;
    a 0-result run warns loudly rather than failing the build.
  * The dataset is national. We filter to the Alpes-Maritimes by department, and
    then again client-side by a 06 postcode, so a mislabelled department can't
    leak Paris events onto a Nice site.
"""
from __future__ import annotations

import logging
import re
from datetime import date
from typing import Iterator, Optional

from ..models import Event, canon_town, classify
from .base import HttpScraper, register

log = logging.getLogger(__name__)

API = ("https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/"
       "evenements-publics-openagenda/records")

# Exact-match filter is the most reliable ODSQL there is. If the field or value
# ever changes the run returns nothing and warns — it can't silently ship wrong
# data. The postcode belt-and-braces below is what actually guarantees 06-only.
WHERE = 'location_department="Alpes-Maritimes"'


def _iso_date(s: Optional[str]) -> Optional[date]:
    """OpenAgenda hands back ISO datetimes like 2026-07-18T19:30:00+02:00."""
    if not s or len(s) < 10:
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _iso_time(s: Optional[str]) -> Optional[str]:
    if s and len(s) >= 16 and s[10] == "T":
        hhmm = s[11:16]
        return None if hhmm == "00:00" else hhmm      # midnight == "no time given"
    return None


def _text(v) -> str:
    if isinstance(v, list):
        v = " ".join(str(x) for x in v)
    return re.sub(r"\s+", " ", str(v or "")).strip()


def _postcode(rec: dict) -> str:
    for k in ("location_postalcode", "location_postal_code", "location_zipcode"):
        if rec.get(k):
            return str(rec[k]).strip()
    return ""


@register
class OpenAgenda(HttpScraper):
    name = "openagenda"
    label = "OpenAgenda (culture)"
    delay = 0.5

    PAGE = 100          # Opendatasoft v2.1 hard-caps limit at 100
    MAX_PAGES = 40      # 4000 events is far more than the 06 will ever have

    #: Only take the fields we use — smaller responses, faster paging.
    SELECT = ",".join([
        "title_fr", "description_fr", "keywords_fr", "canonicalurl",
        "firstdate_begin", "lastdate_end",
        "location_name", "location_address", "location_city",
        "location_postalcode", "location_department",
    ])

    def fetch(self) -> Iterator[Event]:
        today = date.today()
        seen: set[str] = set()
        kept = 0

        for page in range(self.MAX_PAGES):
            offset = page * self.PAGE
            url = (f"{API}?where={self._q(WHERE)}"
                   f"&select={self._q(self.SELECT)}"
                   f"&order_by=firstdate_begin&limit={self.PAGE}&offset={offset}")
            r = self.get(url)
            if not r:
                break
            try:
                payload = r.json()
            except Exception:
                log.warning("%s: response wasn't JSON", self.name)
                break

            rows = payload.get("results") or []
            if not rows:
                break

            for rec in rows:
                ev = self._to_event(rec, today)
                if ev is None or ev.fingerprint in seen:
                    continue
                seen.add(ev.fingerprint)
                kept += 1
                yield ev

            total = payload.get("total_count")
            if isinstance(total, int) and offset + self.PAGE >= total:
                break

        if kept == 0:
            log.warning("%s: 0 events — check the API field names / WHERE clause "
                        "against a live response", self.name)

    @staticmethod
    def _q(s: str) -> str:
        from urllib.parse import quote
        return quote(s, safe="")

    def _to_event(self, rec: dict, today: date) -> Optional[Event]:
        title = _text(rec.get("title_fr"))
        start = _iso_date(rec.get("firstdate_begin"))
        if not title or not start:
            return None

        # Belt-and-braces geo filter: national dataset, so never trust the
        # department label alone. If there's a postcode and it isn't 06xxx, drop.
        pc = _postcode(rec)
        if pc and not pc.startswith("06"):
            return None

        end = _iso_date(rec.get("lastdate_end"))
        if end and end < start:
            end = None
        if (end or start) < today:
            return None

        city = _text(rec.get("location_city"))
        town = canon_town(city or None, pc or None)

        venue = _text(rec.get("location_name")) or None
        kw = _text(rec.get("keywords_fr"))
        desc = _text(rec.get("description_fr"))
        cat = classify(title, kw, desc, venue or "")

        note_bits = [b for b in (_iso_time(rec.get("firstdate_begin")), kw, desc) if b]

        return Event(
            title=title,
            start=start,
            end=end,
            time=_iso_time(rec.get("firstdate_begin")),
            town=town,
            venue=venue,
            category=cat,
            url=_text(rec.get("canonicalurl")) or None,
            note=" · ".join(note_bits)[:400] or None,
            source=self.name,
        )
