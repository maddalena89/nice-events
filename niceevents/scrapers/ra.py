"""Resident Advisor — electronic music, clubs, parties.

RA lists "12 upcoming events" for Nice but only ships ~2 in the raw HTML; the
rest hydrate client-side. Browser required.

RA is a Next.js app, so __NEXT_DATA__ / Apollo cache usually holds the full
list — much better than reading the DOM.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, parse_date, parse_time
from .base import BrowserScraper, register

BASE = "https://ra.co"

# RA area pages in and around the 06.
AREAS = ["fr/nice", "fr/cotedazur", "fr/monaco"]


@register
class ResidentAdvisor(BrowserScraper):
    name = "ra"
    label = "Resident Advisor"

    def fetch(self) -> Iterator[Event]:
        seen: set[str] = set()
        for area in AREAS:
            url = f"{BASE}/events/{area}"
            html = self._page_text(url, wait_for="a[href*='/events/']", scroll=4)
            if not html:
                continue
            for ev in self._parse(html, url):
                if ev.fingerprint in seen:
                    continue
                seen.add(ev.fingerprint)
                yield ev

    def _parse(self, html: str, page_url: str) -> Iterator[Event]:
        tree = HTMLParser(html)
        got = 0
        for ev in self._from_next(tree):
            got += 1
            yield ev
        if got == 0:
            yield from self._from_dom(tree, page_url)

    def _from_next(self, tree: HTMLParser) -> Iterator[Event]:
        node = tree.css_first("#__NEXT_DATA__")
        if not node:
            return
        try:
            data = json.loads(node.text() or "{}")
        except json.JSONDecodeError:
            return

        for obj in _walk(data):
            t = obj.get("__typename") or obj.get("type")
            if t and str(t).lower() != "event":
                continue
            ev = self._from_obj(obj)
            if ev:
                yield ev

    def _from_obj(self, obj: dict) -> Optional[Event]:
        title = obj.get("title") or obj.get("name")
        when = obj.get("date") or obj.get("startTime") or obj.get("startDate")
        if not title or not when:
            return None
        start = parse_date(str(when))
        if not start or start < date.today():
            return None

        venue = obj.get("venue") or {}
        vname = venue.get("name") if isinstance(venue, dict) else None
        area = venue.get("area") if isinstance(venue, dict) else None
        town = (area or {}).get("name") if isinstance(area, dict) else "Nice"

        artists = obj.get("artists") or []
        names = [a.get("name") for a in artists if isinstance(a, dict) and a.get("name")]

        cid = obj.get("contentUrl") or obj.get("id")
        url = (BASE + cid) if isinstance(cid, str) and cid.startswith("/") \
            else (f"{BASE}/events/{cid}" if cid else None)

        bits = []
        t = parse_time(str(when))
        if t:
            bits.append(t)
        if names:
            bits.append(", ".join(names[:6]))

        return Event(
            title=str(title).strip(),
            start=start,
            time=t,
            town=town or "Nice",
            venue=vname,
            category="autre",   # RA is club/electronic → Clubs & other, not live music
            url=url,
            note=" · ".join(bits)[:300] or None,
            source=self.name,
        )

    def _from_dom(self, tree: HTMLParser, page_url: str) -> Iterator[Event]:
        for a in tree.css("a[href*='/events/']"):
            href = a.attributes.get("href", "")
            if not re.search(r"/events/\d+", href):
                continue
            title = re.sub(r"\s+", " ", (a.text() or "")).strip()
            if not title or len(title) < 3:
                continue

            card = a.parent
            for _ in range(3):
                if card is None or len(card.text() or "") > len(title) + 20:
                    break
                card = card.parent
            block = re.sub(r"\s+", " ", (card.text() if card else "") or "")

            start = parse_date(block)
            if not start or start < date.today():
                continue

            venue = None
            vm = re.search(r"Location\s*(.+?)(?:\s{2,}|Person|$)", block)
            if vm:
                venue = vm[1].strip()[:80]

            yield Event(
                title=title,
                start=start,
                town="Nice",
                venue=venue,
                category="autre",   # RA is club/electronic → Clubs & other, not live music
                url=href if href.startswith("http") else BASE + href,
                source=self.name,
            )


def _walk(data) -> Iterator[dict]:
    if isinstance(data, dict):
        yield data
        for v in data.values():
            if isinstance(v, (dict, list)):
                yield from _walk(v)
    elif isinstance(data, list):
        for item in data:
            yield from _walk(item)
