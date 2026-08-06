"""Shared base for public Google Calendar sources.

Several local organisers (the swing scene, La Zonmé, …) keep a *public* Google
Calendar. Google publishes any public calendar as a plain iCalendar (.ics) feed
— the same feed a calendar app subscribes to — so we read structured data
directly instead of scraping a rendered page. Stable, no browser, no guessing.

Subclass GCalICS, set CAL_ID (the calendar's group-address id), and optionally
pin a CATEGORY / VENUE / default town. Everything else is handled here.
"""
from __future__ import annotations

import logging
import re
from datetime import date, timedelta
from typing import Iterator, Optional

from ..models import Event, canon_town, classify, slugify
from ..models import _TOWN_CANON  # noqa: private, but it's the town lookup table
from .base import HttpScraper

log = logging.getLogger(__name__)


def _ics_url(cal_id: str) -> str:
    return f"https://calendar.google.com/calendar/ical/{cal_id.replace('@', '%40')}/public/basic.ics"


def unfold(text: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with space/tab continues the last."""
    out: list[str] = []
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if line[:1] in (" ", "\t") and out:
            out[-1] += line[1:]
        else:
            out.append(line)
    return out


def unescape(v: str) -> str:
    return (v.replace("\\n", " ").replace("\\N", " ")
             .replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")).strip()


def split_prop(line: str) -> tuple[str, str]:
    """'DTSTART;TZID=Europe/Paris:20260815T190000' -> ('DTSTART', '20260815T190000')."""
    i = line.find(":")
    if i < 0:
        return "", ""
    return line[:i].split(";", 1)[0].upper(), line[i + 1:]


def parse_dt(value: str) -> tuple[Optional[date], Optional[str]]:
    """Return (date, 'HH:MM' or None). Handles date, local datetime, and UTC 'Z'."""
    m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?", value.strip())
    if not m:
        return None, None
    y, mo, d, hh, mm = m.groups()
    try:
        dt = date(int(y), int(mo), int(d))
    except ValueError:
        return None, None
    if hh is None:
        return dt, None
    hm = f"{hh}:{mm}"
    return dt, (None if hm == "00:00" else hm)   # midnight == "no time given"


def town_from(loc: str, default: str = "Nice") -> str:
    """Best-effort town from a free-text LOCATION."""
    if loc:
        m = re.search(r"\b(0?6\d{3})\b", loc)
        if m:
            t = canon_town(None, m.group(1).zfill(5))
            if t and t != "Unknown":
                return t
        for part in re.split(r"[,\n]", loc):
            key = slugify(part.strip())
            if key in _TOWN_CANON:
                return _TOWN_CANON[key]
    return default


class GCalICS(HttpScraper):
    """Base for a single public Google Calendar. Set CAL_ID in the subclass."""

    CAL_ID: str = ""
    #: force a category, or leave None to classify from the title/description
    CATEGORY: Optional[str] = None
    #: fallback category when classify() can't tell (a music venue -> "concert")
    DEFAULT_CATEGORY: Optional[str] = None
    #: fallback venue when the event has no LOCATION
    VENUE: Optional[str] = None
    #: town to assume when the LOCATION names none
    DEFAULT_TOWN: str = "Nice"
    #: link used when an event carries no URL of its own — so every event this
    #: source produces is clickable (e.g. the organiser's events page).
    URL_FALLBACK: Optional[str] = None
    delay = 0.5

    def fetch(self) -> Iterator[Event]:
        r = self.get(_ics_url(self.CAL_ID))
        if not r:
            log.warning("%s: could not fetch the ICS feed", self.name)
            return
        today = date.today()
        cur: dict[str, str] = {}
        in_event = False
        kept = 0
        for line in unfold(r.text):
            if line == "BEGIN:VEVENT":
                cur, in_event = {}, True
            elif line == "END:VEVENT":
                in_event = False
                ev = self._to_event(cur, today)
                if ev is not None:
                    kept += 1
                    yield ev
            elif in_event:
                name, val = split_prop(line)
                if name and name not in cur:      # keep the first DTSTART etc.
                    cur[name] = val
        if kept == 0:
            log.warning("%s: 0 upcoming events — is the calendar still public/populated?",
                        self.name)

    def _to_event(self, ev: dict, today: date) -> Optional[Event]:
        title = unescape(ev.get("SUMMARY", ""))
        start, time = parse_dt(ev.get("DTSTART", ""))
        if not title or not start:
            return None

        end, _ = parse_dt(ev.get("DTEND", ""))
        # All-day DTEND is exclusive (the morning after) — pull it back a day.
        if end and "T" not in ev.get("DTEND", "") and end > start:
            end = end - timedelta(days=1)
        if end and end <= start:
            end = None
        if (end or start) < today:
            return None

        loc = unescape(ev.get("LOCATION", ""))
        desc = unescape(ev.get("DESCRIPTION", ""))
        venue = (loc.split(",")[0].strip() if loc else None) or self.VENUE
        cat = self.CATEGORY
        if not cat:
            cat = classify(title, desc, venue or "")
            if cat == "autre" and self.DEFAULT_CATEGORY:
                cat = self.DEFAULT_CATEGORY

        # Always give the event a link so it's clickable: its own URL, else a link
        # found in the description, else the source's fallback (organiser page).
        url = (ev.get("URL") or "").strip()
        if not url and desc:
            m = re.search(r"https?://[^\s>)\]]+", desc)
            if m:
                url = m.group(0).rstrip(".,;")
        url = url or self.URL_FALLBACK

        return Event(
            title=title,
            start=start,
            end=end,
            time=time,
            town=town_from(loc, self.DEFAULT_TOWN),
            venue=venue,
            category=cat,
            url=url or None,
            note=desc[:300] or None,
            source=self.name,
        )
