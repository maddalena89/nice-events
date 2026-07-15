"""Museums & art spaces — Maeght, MAMAC, Matisse, Chagall, Villa Arson, Le 109,
Villa Ephrussi, Palais Lascaris, TNN, Opéra, Nikaïa.

These sites all look different, so rather than eleven bespoke parsers we lean on
schema.org JSON-LD (`Event` / `ExhibitionEvent` / `VisualArtsEvent`), which a
good share of French cultural sites emit for Google. Where a venue doesn't emit
it, we fall back to <time datetime> pairs near a heading.

REALITY CHECK: this is the least reliable scraper in the project. JSON-LD
coverage varies and some of these sites are JS-rendered. Expect to tune per
venue — `--only museums -v` prints exactly what each one yielded. Venues that
come back empty are listed in the README under "Known gaps".
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, classify, parse_date
from .base import HttpScraper, register


class Venue:
    def __init__(self, key: str, name: str, town: str, urls: list[str],
                 needs_browser: bool = False):
        self.key, self.name, self.town = key, name, town
        self.urls, self.needs_browser = urls, needs_browser


VENUES = [
    # VERIFIED AGAINST THE LIVE SITES — the first run 404'd or DNS-failed on
    # most of the URLs I guessed. What each one actually did:
    #   fondation-maeght.com/expositions/  -> 301 to /past-exhibitions/ (wrong!)
    #   fondation-maeght.com/agenda/       -> 404
    #   musee-matisse-nice.org/fr/expositions/ -> 404
    #   le109nice.fr, palais-lascaris.fr   -> DNS: no such host
    #   villa-arson.fr                     -> SSL cert hostname mismatch
    #   opera-nice.org/fr/saison, nikaia.fr/agenda/ -> 404
    #   musees-nationaux-alpesmaritimes.fr -> SSL EOF
    #
    # Most of these venues are ALSO in the nice.fr agenda (which returned 495
    # events), so losing them costs little. This scraper now only covers what
    # nice.fr can't: venues outside the commune of Nice.
    Venue("maeght", "Fondation Maeght", "Saint-Paul-de-Vence",
          ["https://www.fondation-maeght.com/en/exhibitions/",
           "https://www.fondation-maeght.com/expositions-en-cours/"]),
    Venue("mamac", "MAMAC", "Nice",
          ["https://www.mamac-nice.org/"]),          # homepage lists current shows
]


@register
class Museums(HttpScraper):
    name = "museums"
    label = "Museums & art spaces"
    delay = 1.5

    def fetch(self) -> Iterator[Event]:
        seen: set[str] = set()
        for venue in VENUES:
            for url in venue.urls:
                r = self.get(url)
                if not r:
                    continue
                for ev in self._from_page(r.text, venue, url):
                    if ev.fingerprint in seen:
                        continue
                    seen.add(ev.fingerprint)
                    yield ev

    def _from_page(self, html: str, venue: Venue, url: str) -> Iterator[Event]:
        tree = HTMLParser(html)
        got = 0
        for ev in self._from_jsonld(tree, venue, url):
            got += 1
            yield ev
        if got == 0:
            yield from self._from_time_tags(tree, venue, url)

    # ------------------------------------------------------------ JSON-LD
    def _from_jsonld(self, tree: HTMLParser, venue: Venue, url: str) -> Iterator[Event]:
        for node in tree.css('script[type="application/ld+json"]'):
            raw = node.text() or ""
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for obj in _walk(data):
                ev = self._from_obj(obj, venue, url)
                if ev:
                    yield ev

    def _from_obj(self, obj: dict, venue: Venue, url: str) -> Optional[Event]:
        t = obj.get("@type")
        types = t if isinstance(t, list) else [t]
        if not any(str(x).endswith("Event") or x in ("Exhibition", "ExhibitionEvent")
                   for x in types if x):
            return None

        name = _txt(obj.get("name"))
        start = parse_date(_txt(obj.get("startDate")))
        if not name or not start:
            return None
        end = parse_date(_txt(obj.get("endDate"))) if obj.get("endDate") else None
        if (end or start) < date.today():
            return None

        loc = obj.get("location") or {}
        place = _txt(loc.get("name")) if isinstance(loc, dict) else _txt(loc)

        offers = obj.get("offers") or {}
        if isinstance(offers, list):
            offers = offers[0] if offers else {}
        price = _txt(offers.get("price")) if isinstance(offers, dict) else None
        free = price in ("0", "0.0", "0.00")

        return Event(
            title=name,
            start=start,
            end=end,
            town=venue.town,
            venue=place or venue.name,
            category=classify(name, _txt(obj.get("description")), venue.name),
            url=_txt(obj.get("url")) or url,
            note=(_txt(obj.get("description")) or "")[:300] or None,
            price=None if free else (f"{price} €" if price else None),
            free=free,
            source=f"{self.name}:{venue.key}",
        )

    # -------------------------------------------------------- <time> pairs
    def _from_time_tags(self, tree: HTMLParser, venue: Venue, url: str) -> Iterator[Event]:
        """Fallback: a heading with <time datetime="..."> nearby."""
        for node in tree.css("article, .event, .exposition, li, .card"):
            times = node.css("time[datetime]")
            if not times:
                continue
            head = node.css_first("h1, h2, h3, h4, a")
            title = re.sub(r"\s+", " ", (head.text() if head else "")).strip()
            if not title or len(title) < 3:
                continue

            start = parse_date(times[0].attributes.get("datetime", ""))
            if not start:
                continue
            end = parse_date(times[1].attributes.get("datetime", "")) if len(times) > 1 else None
            if (end or start) < date.today():
                continue

            href = None
            a = node.css_first("a[href]")
            if a:
                href = a.attributes.get("href")
                if href and href.startswith("/"):
                    href = re.match(r"https?://[^/]+", url)[0] + href

            yield Event(
                title=title,
                start=start,
                end=end,
                town=venue.town,
                venue=venue.name,
                category=classify(title, venue.name),
                url=href or url,
                source=f"{self.name}:{venue.key}",
            )


def _walk(data) -> Iterator[dict]:
    """JSON-LD nests under @graph / arrays; flatten it all out."""
    if isinstance(data, dict):
        if "@graph" in data:
            yield from _walk(data["@graph"])
        else:
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
