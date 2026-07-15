"""Tango — milongas and practicas.

tango-argentin.fr has run a hand-verified calendar for France since 2002 and is
by far the best tango source for the 06. Server-rendered tables:

    <h6>Wednesday 15 July 2026</h6>
    <table>
      <tr><td>8:30pm</td>
          <td>Amarras 2 rue la Bruyere 06000 Nice from 8:30pm to 12:00am
              10 euros DJ : Pierre Gabrielli</td></tr>
    </table>

An <img src=".../pleinair.png"> on the row means the milonga is outdoors.

We sweep Nice plus the nearby 06 towns the site indexes.
"""
from __future__ import annotations

import re
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..dom import in_order
from ..models import Event, parse_date, parse_time
from .base import HttpScraper, register

BASE = "https://tango-argentin.fr/en"

# Cities this site indexes that sit in or near the 06.
CITIES = ["nice", "beausoleil", "villeneuve-loubet"]

_DAY_HEAD = re.compile(
    r"^\s*(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+"
    r"(\d{1,2}\s+\w+\s+\d{4})\s*$", re.I)

_POSTCODE = re.compile(r"\b(0[46]\d{3})\b")
_PRICE = re.compile(r"(\d+\s*euros?(?:\s*/\s*\d+\s*euros?)?|au chapeau|chapeau|free|gratuit)", re.I)
_DJ = re.compile(r"DJ\s*:\s*([^\n]+?)(?:\s{2,}|$)", re.I)
_RANGE = re.compile(r"from\s+([\d:apm.]+)\s+to\s+([\d:apm.]+)", re.I)


@register
class TangoArgentin(HttpScraper):
    name = "tango_argentin"
    label = "Tango-Argentin (verified)"
    delay = 1.2

    def fetch(self) -> Iterator[Event]:
        seen: set[str] = set()
        for city in CITIES:
            r = self.get(f"{BASE}/{city}")
            if not r:
                continue
            for ev in self._parse(r.text, city):
                if ev.fingerprint in seen:
                    continue
                seen.add(ev.fingerprint)
                yield ev

    def _parse(self, html: str, city: str) -> Iterator[Event]:
        tree = HTMLParser(html)
        current = None

        # MUST be document order — see niceevents/dom.py. css("h6, tr") groups
        # by selector and silently dates every milonga to the last heading.
        for node in in_order(tree, {"h6", "h5", "h4", "tr"}):
            text = re.sub(r"\s+", " ", (node.text() or "")).strip()

            if node.tag in ("h6", "h5", "h4"):
                m = _DAY_HEAD.match(text)
                if m:
                    current = parse_date(m[1])
                continue

            if current is None or not text:
                continue

            cells = node.css("td")
            if len(cells) < 2:
                continue

            ev = self._event(cells, node, current, city)
            if ev:
                yield ev

    def _event(self, cells, row, when, city) -> Optional[Event]:
        start_t = parse_time(re.sub(r"\s+", " ", cells[0].text() or ""))
        body = re.sub(r"\s+", " ", cells[-1].text() or "").strip()
        if not body:
            return None

        # Title = everything before the street address / postcode.
        m = _POSTCODE.search(body)
        head = body[: m.start()] if m else body
        # Strip a trailing street address off the head: "Amarras 2 rue la Bruyere"
        title_m = re.match(r"^(.*?)(?=\s+\d+\s+(?:rue|av|avenue|bd|boulevard|place|chemin|quai))",
                           head, re.I)
        title = (title_m[1] if title_m else head).strip(" ,-–")
        if not title:
            return None

        postcode = m[1] if m else None
        # Venue = address chunk between title and postcode, plus what follows it.
        venue = head[len(title):].strip(" ,-–") or None
        if postcode:
            venue = f"{venue} · {postcode}" if venue else postcode

        town = "Nice"
        if postcode:
            town = postcode
        elif city != "nice":
            town = city.replace("-", " ").title()

        bits = []
        rng = _RANGE.search(body)
        if rng:
            a, b = parse_time(rng[1]), parse_time(rng[2])
            if a and b:
                bits.append(f"{a}–{b}")
        elif start_t:
            bits.append(start_t)

        price = None
        pm = _PRICE.search(body)
        if pm:
            price = pm[1].strip()
            bits.append(price)

        dj = _DJ.search(body)
        if dj:
            bits.append(f"DJ {dj[1].strip()}")

        outdoor = bool(row.css_first("img[src*='pleinair']"))
        if outdoor:
            bits.append("outdoor")

        return Event(
            title=title,
            start=when,
            time=start_t,
            town=town if not postcode else _town_from_cp(postcode, city),
            venue=venue,
            category="danse",
            url=f"{BASE}/{city}",
            note=" · ".join(bits) or None,
            price=price,
            free=bool(price and re.search(r"chapeau|free|gratuit", price, re.I)),
            outdoor=outdoor,
            source=self.name,
        )


def _town_from_cp(cp: str, fallback: str) -> str:
    from ..models import canon_town
    return canon_town(None, cp) or fallback.replace("-", " ").title()
