"""Eventbrite — business, tech/AI conferences, workshops, expat socials.

Two problems, both real:
  1. The public search API was retired in 2019. There is no sanctioned way to
     query events by city any more.
  2. The search pages are bot-protected — plain HTTP requests time out
     (verified: two attempts, both hung past 180s).

So: browser, unhurried, and honest about being flaky. Eventbrite embeds
schema.org JSON-LD per event card, which is the sturdiest thing to read.

If this scraper starts returning zero across the board, that's Eventbrite
tightening protection rather than a parsing bug. Don't fight it — the events
that matter usually also live on Meetup or the organiser's own site.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, classify, parse_date, parse_time
from .base import BrowserScraper, register

BASE = "https://www.eventbrite.fr"

# Eventbrite's own category slugs; --only eventbrite -v shows what each returns.
FEEDS = [
    "/d/france--nice/business--events/",
    "/d/france--nice/science-and-tech--events/",
    "/d/france--nice/all-events/",
    "/d/france--nice/networking--events/",
    "/d/france--nice/music--events/",
    "/d/france--nice/arts--events/",
]
PAGES = 3


@register
class Eventbrite(BrowserScraper):
    name = "eventbrite"
    label = "Eventbrite (business, tech, AI)"
    delay = 3.0  # deliberately slow; this one gets blocked if pushed

    def fetch(self) -> Iterator[Event]:
        seen: set[str] = set()
        for feed in FEEDS:
            for page in range(1, PAGES + 1):
                url = f"{BASE}{feed}" + (f"?page={page}" if page > 1 else "")
                html = self._page_text(
                    url,
                    wait_for="script[type='application/ld+json'], [data-testid='search-event']",
                    scroll=2,
                )
                if not html:
                    break
                found = 0
                for ev in self._parse(html):
                    found += 1
                    if ev.fingerprint in seen:
                        continue
                    seen.add(ev.fingerprint)
                    yield ev
                if found == 0:
                    break

    def _parse(self, html: str) -> Iterator[Event]:
        tree = HTMLParser(html)
        for node in tree.css('script[type="application/ld+json"]'):
            try:
                data = json.loads(node.text() or "{}")
            except json.JSONDecodeError:
                continue
            for obj in _walk(data):
                ev = self._from_obj(obj)
                if ev:
                    yield ev

    def _from_obj(self, obj: dict) -> Optional[Event]:
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if not any(str(x).endswith("Event") for x in types if x):
            return None

        name = _txt(obj.get("name"))
        start = parse_date(_txt(obj.get("startDate")) or "")
        if not name or not start or start < date.today():
            return None
        end = parse_date(_txt(obj.get("endDate")) or "") if obj.get("endDate") else None
        if end == start:
            end = None

        loc = obj.get("location") or {}
        venue = town = None
        if isinstance(loc, dict):
            venue = _txt(loc.get("name"))
            addr = loc.get("address")
            if isinstance(addr, dict):
                town = _txt(addr.get("addressLocality"))
            elif isinstance(addr, str):
                town = _txt(addr)
        town = town or "Nice"

        offers = obj.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = _txt(offers.get("price")) if isinstance(offers, dict) else None
        free = price in ("0", "0.0", "0.00")

        desc = (_txt(obj.get("description")) or "")[:250]
        tm = parse_time(_txt(obj.get("startDate")) or "")

        return Event(
            title=name,
            start=start,
            end=end,
            time=tm,
            town=town,
            venue=venue,
            category=classify(name, desc, venue),
            url=_txt(obj.get("url")),
            note=" · ".join(b for b in (tm, desc) if b)[:400] or None,
            price=None if free else (f"{price} €" if price else None),
            free=free,
            source=self.name,
        )


def _walk(data) -> Iterator[dict]:
    if isinstance(data, dict):
        if "@graph" in data:
            yield from _walk(data["@graph"])
            return
        yield data
        for v in data.values():
            if isinstance(v, (dict, list)):
                yield from _walk(v)
    elif isinstance(data, list):
        for item in data:
            yield from _walk(item)


def _txt(v) -> Optional[str]:
    if v is None:
        return None
    if isinstance(v, dict):
        v = v.get("name") or v.get("@value") or ""
    if isinstance(v, list):
        v = v[0] if v else ""
    s = re.sub(r"<[^>]+>", " ", str(v))
    return re.sub(r"\s+", " ", s).strip() or None
