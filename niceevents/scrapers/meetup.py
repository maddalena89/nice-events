"""Meetup — designers, business, tech/AI, expat, social.

Meetup renders its event lists client-side: plain HTTP gets you a page shell
with zero events in it (verified — the group page returns "Events 0"). So this
one needs a real browser.

Strategy: hit /find/ once per topic keyword rather than crawling groups, because
the topic search surfaces events from groups we'd never think to list. Then let
dedup collapse the overlap.

Meetup's public GraphQL needs an OAuth key; the search page does not. We only
read pages any logged-out visitor sees, at a polite crawl rate — we never log
in, join, or touch anything behind an account.
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, classify, parse_date, parse_time
from .base import BrowserScraper, register

BASE = "https://www.meetup.com"

# Meetup's location search returns online events too — they match "near Nice"
# because the *group* is near Nice, or sometimes for no visible reason at all
# (a Lyon meetup restreamed online came back under Nice). They're kept, flagged,
# and hidden behind a checkbox rather than dropped: someone may genuinely want
# the Tuesday language exchange on Zoom.
#
# Only *bracketed* markers count in the title. A bare "online" is not evidence:
# "Online Marketing Workshop" is a real room with real chairs, and treating it
# as a webinar would hide a legitimate Nice event. Brackets and parens are how
# organisers actually mark format, so they're the honest signal. Everything else
# leans on structured fields.
_ONLINE_TITLE = re.compile(
    r"[\[(]\s*(?:online|en\s+ligne|virtual|virtuel|zoom|webinar)\s*[\])]"
    r"|^\s*online\s*!+",
    re.I,
)
_ONLINE_VENUE = re.compile(r"^\s*online\b|online\s+event", re.I)


def _is_online(obj: dict, venue: Optional[str], title: str) -> bool:
    # 1. Structured, when Meetup bothers to tell us.
    if obj.get("isOnline") is True:
        return True
    if str(obj.get("eventType") or "").upper() in {"ONLINE", "VIRTUAL"}:
        return True
    # 2. Meetup's own placeholder venue. This is the one that catches most of
    #    them in practice.
    if venue and _ONLINE_VENUE.search(venue):
        return True
    # 3. Explicit bracketed marker in the title.
    return bool(title and _ONLINE_TITLE.search(str(title)))

# Meetup search is keyword-driven: a topic that isn't in this list does not
# exist as far as this site is concerned. That's not a scraper bug, it's a
# blind spot — acroyoga jams were "missing" purely because nothing here ever
# asked for them. When something's absent from the site, check this list first.
TOPICS = [
    # work
    "design", "ux", "business", "entrepreneur", "startup", "tech",
    "artificial-intelligence", "data-science", "networking",
    # people
    "expat", "language-exchange", "social", "photography", "music",
    # bodies in rooms — the whole category that was missing
    "acroyoga", "yoga", "dance", "ecstatic-dance", "contact-improvisation",
    "movement", "wellness", "meditation", "hiking", "climbing",
    # alternative / kink. Meetup's own topic slugs; expect thin results and see
    # the note in README — most of this scene deliberately doesn't list in public.
    "alternative-lifestyle", "bdsm", "shibari", "tantra", "polyamory",
]

RADIUS_MILES = 25  # Nice -> reaches Antibes, Cannes, Monaco


@register
class Meetup(BrowserScraper):
    name = "meetup"
    label = "Meetup (design, business, AI, expat)"

    def fetch(self) -> Iterator[Event]:
        seen: set[str] = set()
        for topic in TOPICS:
            url = (f"{BASE}/find/?location=fr--nice&source=EVENTS"
                   f"&keywords={topic}&distance={RADIUS_MILES}miles")
            html = self._page_text(url, wait_for="[data-testid='categoryResults-eventCard'], "
                                                 "a[href*='/events/']", scroll=3)
            if not html:
                continue
            for ev in self._parse(html):
                if ev.fingerprint in seen:
                    continue
                seen.add(ev.fingerprint)
                yield ev

    def _parse(self, html: str) -> Iterator[Event]:
        tree = HTMLParser(html)

        # Preferred: Next.js ships the real data in __NEXT_DATA__.
        got = 0
        for ev in self._from_next_data(tree):
            got += 1
            yield ev
        if got:
            return

        # Fallback: read the rendered cards.
        yield from self._from_cards(tree)

    def _from_next_data(self, tree: HTMLParser) -> Iterator[Event]:
        node = tree.css_first("#__NEXT_DATA__")
        if not node:
            return
        try:
            data = json.loads(node.text() or "{}")
        except json.JSONDecodeError:
            return
        for obj in _find_events(data):
            ev = self._from_obj(obj)
            if ev:
                yield ev

    def _from_obj(self, obj: dict) -> Optional[Event]:
        title = obj.get("title") or obj.get("name")
        when = obj.get("dateTime") or obj.get("startTime") or obj.get("time")
        if not title or not when:
            return None
        start = parse_date(str(when))
        if not start or start < date.today():
            return None

        venue_obj = obj.get("venue") or {}
        venue = venue_obj.get("name") if isinstance(venue_obj, dict) else None
        city = venue_obj.get("city") if isinstance(venue_obj, dict) else None

        online = _is_online(obj, venue, title)
        if online:
            # NEVER fall through to the `or "Nice"` default below. That default
            # was stamping "Nice" onto every Zoom call Meetup returned for the
            # Nice location search — including a Lyon meetup restreamed online.
            # An online event has no town; pretending it has one is the whole bug.
            town = "Online"
            venue = venue or "Online event"
        else:
            town = city or "Nice"

        group = obj.get("group") or {}
        gname = group.get("name") if isinstance(group, dict) else None

        url = obj.get("eventUrl") or obj.get("url")
        desc = re.sub(r"\s+", " ", str(obj.get("description") or ""))[:250]

        bits = [b for b in (parse_time(str(when)), gname, desc) if b]
        return Event(
            title=str(title).strip(),
            start=start,
            time=parse_time(str(when)),
            town=town,
            venue=venue,
            category=classify(title, gname, desc),
            url=url,
            note=" · ".join(bits)[:400] or None,
            free=bool(obj.get("isFree") or obj.get("feeSettings") in (None, {})),
            online=online,
            source=self.name,
        )

    def _from_cards(self, tree: HTMLParser) -> Iterator[Event]:
        for card in tree.css("[data-testid='categoryResults-eventCard'], div[class*='EventCard']"):
            a = card.css_first("a[href*='/events/']")
            if not a:
                continue
            block = re.sub(r"\s+", " ", card.text() or "")
            title_node = card.css_first("h2, h3, [class*='title']")
            title = re.sub(r"\s+", " ", (title_node.text() if title_node else "")).strip()
            if not title:
                continue
            start = parse_date(block)
            if not start or start < date.today():
                continue
            href = a.attributes.get("href", "")
            yield Event(
                title=title,
                start=start,
                time=parse_time(block),
                town="Nice",
                category=classify(title, block),
                url=href if href.startswith("http") else BASE + href,
                note=block[:250] or None,
                source=self.name,
            )


def _find_events(data) -> Iterator[dict]:
    """Meetup buries event objects at unpredictable depths; walk for the shape."""
    if isinstance(data, dict):
        looks_like = (
            ("title" in data or "name" in data)
            and any(k in data for k in ("dateTime", "startTime", "eventUrl"))
        )
        if looks_like:
            yield data
        for v in data.values():
            if isinstance(v, (dict, list)):
                yield from _find_events(v)
    elif isinstance(data, list):
        for item in data:
            yield from _find_events(item)
