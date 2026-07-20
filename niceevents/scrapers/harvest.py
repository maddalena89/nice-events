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
from datetime import date, timedelta
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, canon_town, classify
from .base import HttpScraper, register

log = logging.getLogger(__name__)

# (name, url, kind[, town]). kind is "jsonld" (an HTML page to scan) or "ics" (a
# feed). The optional 4th field is a DEFAULT TOWN, used when a feed's events carry
# no address of their own — common for Google-Calendar feeds, which often list a
# room name but no city. Without it those events land in "Unknown" and drop out of
# a place-based site.
# Seeded thin ON PURPOSE: the engine below is tested with fixtures, but which of
# these actually expose a feed can only be learned from a real run. Prune the ones
# that come back empty; add ones you find.
VENUES: list[tuple] = [
    # ("Théâtre National de Nice", "https://www.tnn.fr/fr/calendrier", "jsonld"),
    # ("Opéra de Nice",            "https://www.opera-nice.org/fr/agenda", "jsonld"),
    # La Zonmé — Nice arts collective, programme lives on a public Google Calendar.
    ("La Zonmé",
     "https://calendar.google.com/calendar/ical/"
     "9fc9ae4b740cbf6e2d361a6c959c634e7d025e9412a811bafbac1c8144cd3648"
     "%40group.calendar.google.com/public/basic.ics",
     "ics", "Nice"),
    # Swingin'Nice — lindy hop / swing across the 06. Public Google Calendar,
    # recurring practices (RRULE) + one-off workshops & the festival.
    ("Swingin'Nice",
     "https://calendar.google.com/calendar/ical/"
     "swing06events%40gmail.com/public/basic.ics",
     "ics", "Nice"),
    # Liste Salsa d'Olivier — salsa / bachata / kizomba socials, whole 06. Each
    # entry carries its own address, so the town comes from the LOCATION itself.
    ("Liste Salsa d'Olivier",
     "https://salsa.faurax.fr/calendrier.php?dpt=06",
     "ics"),
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
            if key in ("SUMMARY", "DTSTART", "DTEND", "LOCATION", "URL",
                       "DESCRIPTION", "RRULE"):
                # ICS escapes commas/semicolons/newlines with backslashes.
                cur[key] = (val.replace("\\,", ",").replace("\\;", ";")
                               .replace("\\n", " ").replace("\\N", " "))
            elif key == "EXDATE":               # may repeat; accumulate raw dates
                cur["EXDATE"] = (cur.get("EXDATE", "") + "," + val).strip(",")


# A French 5-digit postcode. Take the LAST one in the string — the postcode sits
# right before the town, after the street number (which can also be 4–5 digits).
_PC = re.compile(r"\b(\d{5})\b")

# Country words that flag an out-of-France listing. A national association's
# calendar (swing camps, festivals) carries dates in Sweden, Belgium, etc. that
# have no place on a Nice/06 what's-on.
_FOREIGN = re.compile(
    r"\b(su[eè]de|sweden|norv[eè]ge|belgi|allemagne|germany|deutschland|espagne|"
    r"spain|espa[nñ]a|italie|italia|italy|portugal|suisse|switzerland|schweiz|"
    r"royaume-uni|angleterre|england|pays-bas|autriche|maroc|tunisie)\b", re.I)


def _split_ics_location(loc: str) -> tuple[Optional[str], Optional[str], Optional[str]]:
    """(venue, city, postcode) from an iCal LOCATION string.

    'Le WAG, 5 Rue Leonetti 06160 Juan-les-Pins' -> ('Le WAG, 5 Rue Leonetti',
    'Juan-les-Pins', '06160'). No postcode -> the whole string is the venue and
    the town is left to the caller's fallback."""
    if not loc:
        return None, None, None
    matches = list(_PC.finditer(loc))
    if not matches:
        return loc.strip() or None, None, None
    m = matches[-1]
    postcode = m.group(1)
    city = re.split(r"[,\n]", loc[m.end():])[0].strip(" ,.-") or None
    venue = loc[: m.start()].strip(" ,.-") or None
    return venue, city, postcode


def _in_scope(city: Optional[str], postcode: Optional[str], loc: str) -> bool:
    """Is this iCal event actually in the Alpes-Maritimes (06)?

    National feeds list events everywhere; this keeps the site to its patch. A
    06 postcode passes; any other French postcode fails; a foreign country word
    fails; and an event with NO address at all passes (a local feed's practice
    with just a room name — the caller's default town handles it)."""
    if loc and _FOREIGN.search(loc):
        return False
    if postcode:
        return postcode.startswith("06")
    return True


# ------------------------------------------------------- recurrence (RRULE)
_WD = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_HORIZON_DAYS = 120          # how far ahead to materialise a repeating event


def _rrule_dates(start: date, rrule: str, exdates: set,
                 win_start: date, win_end: date) -> list[date]:
    """Expand a weekly/monthly/daily RRULE into concrete dates inside the window.

    Calendar feeds (Google Calendar especially) store a recurring social as ONE
    event with a start date months in the past plus an RRULE. Read literally it's
    a past event and gets dropped, so a weekly salsa or lindy night would never
    show. This materialises the next occurrences instead. Supports the shapes
    dance socials actually use: FREQ WEEKLY/MONTHLY/DAILY, INTERVAL, BYDAY
    (incl. nth / last weekday for MONTHLY), COUNT and UNTIL."""
    p = dict(kv.split("=", 1) for kv in rrule.split(";") if "=" in kv)
    freq = p.get("FREQ", "").upper()
    interval = max(int(p.get("INTERVAL", "1") or 1), 1)
    count = int(p["COUNT"]) if p.get("COUNT", "").isdigit() else None
    until = None
    mu = re.match(r"(\d{4})(\d{2})(\d{2})", p.get("UNTIL", "") or "")
    if mu:
        until = date(int(mu[1]), int(mu[2]), int(mu[3]))
    byday = [b for b in p.get("BYDAY", "").split(",") if b]

    out: list[date] = []
    n = 0

    def keep(d: date) -> Optional[bool]:
        nonlocal n
        if until and d > until:
            return False                     # stop
        if d > win_end:
            return False
        n += 1
        if d >= win_start and d >= start and d not in exdates:
            out.append(d)
        return not (count and n >= count)

    if freq == "DAILY":
        step = 0
        while True:
            d = start + timedelta(days=interval * step)
            if keep(d) is False:
                break
            step += 1
            if step > 4000:
                break

    elif freq == "WEEKLY":
        wds = sorted(_WD[b[-2:]] for b in byday) if byday else [start.weekday()]
        base = start - timedelta(days=start.weekday())
        wk = 0
        stop = False
        while not stop:
            ws = base + timedelta(weeks=interval * wk)
            if ws > win_end:
                break
            for wd in wds:
                occ = ws + timedelta(days=wd)
                if occ < start:
                    continue
                if keep(occ) is False:
                    stop = True
                    break
            wk += 1
            if wk > 700:
                break

    elif freq == "MONTHLY":
        y, mo = start.year, start.month
        for _ in range(120):                 # up to 10 years of months, capped by window
            month_days = _month_dates(y, mo, byday, start.day)
            for occ in month_days:
                if occ < start:
                    continue
                r = keep(occ)
                if r is False:
                    return out
            first = date(y, mo, 1)
            if first > win_end:
                break
            # advance INTERVAL months
            idx = (y * 12 + (mo - 1)) + interval
            y, mo = idx // 12, idx % 12 + 1
    return out


def _month_dates(year: int, month: int, byday: list[str], dom: int) -> list[date]:
    """The dates in a given month matched by a MONTHLY rule's BYDAY (e.g. '-1TH',
    '3WE'), or the plain day-of-month when there's no BYDAY."""
    if not byday:
        try:
            return [date(year, month, dom)]
        except ValueError:
            return []
    out: list[date] = []
    for token in byday:
        m = re.match(r"(-?\d)?([A-Z]{2})$", token)
        if not m or m.group(2) not in _WD:
            continue
        nth = int(m.group(1)) if m.group(1) else 0
        wd = _WD[m.group(2)]
        days = [d for d in _month_weekday_days(year, month, wd)]
        if nth == 0:
            out.extend(days)
        elif nth > 0 and nth <= len(days):
            out.append(days[nth - 1])
        elif nth < 0 and -nth <= len(days):
            out.append(days[nth])
    return sorted(out)


def _month_weekday_days(year: int, month: int, wd: int) -> list[date]:
    d = date(year, month, 1)
    out = []
    while d.month == month:
        if d.weekday() == wd:
            out.append(d)
        d += timedelta(days=1)
    return out


def _ics_starts(raw: dict, today: date) -> list[str]:
    """The concrete DTSTART strings an ICS event resolves to: itself if one-off,
    or its materialised occurrences if it carries an RRULE. Time-of-day (and
    thus the displayed start time) is carried over from the original DTSTART."""
    dt = raw.get("DTSTART", "")
    rrule = raw.get("RRULE")
    if not rrule:
        return [dt] if dt else []
    start = _ics_date(dt)
    if not start:
        return []
    tsuffix = ""
    mt = re.search(r"T(\d{6})", dt) or re.search(r"T(\d{4})", dt)
    if mt:
        t = mt.group(1)
        tsuffix = "T" + (t if len(t) == 6 else t + "00")
    exdates = {d for tok in (raw.get("EXDATE", "") or "").split(",")
               if (d := _ics_date(tok.strip()))}
    win_end = today + timedelta(days=_HORIZON_DAYS)
    return [f"{d:%Y%m%d}{tsuffix}" for d in
            _rrule_dates(start, rrule, exdates, today, win_end)]


@register
class VenueHarvest(HttpScraper):
    name = "harvest"
    label = "Venue calendars"
    delay = 1.0

    def fetch(self) -> Iterator[Event]:
        today = date.today()
        seen: set[str] = set()
        for name, url, kind, *rest in VENUES:
            town = rest[0] if rest else None
            try:
                yield from self._one(name, url, kind, today, seen, town)
            except Exception as e:                     # one venue must not sink the rest
                log.warning("%s: %s (%s) failed — %s", self.name, name, url, e)

    def _one(self, name, url, kind, today, seen, default_town=None) -> Iterator[Event]:
        r = self.get(url)
        if not r:
            return
        if kind == "ics":
            for raw in _events_from_ics(r.text):
                # A recurring event fans out into its upcoming occurrences.
                for start_str in _ics_starts(raw, today):
                    inst = dict(raw, DTSTART=start_str)
                    if raw.get("RRULE"):
                        inst.pop("DTEND", None)     # per-occurrence: no stale end
                    ev = self._from_ics(inst, name, today, default_town)
                    if ev and ev.fingerprint not in seen:
                        seen.add(ev.fingerprint)
                        yield ev
            return
        for raw in _events_from_jsonld(r.text):
            ev = self._from_jsonld(raw, name, today, default_town)
            if ev and ev.fingerprint not in seen:
                seen.add(ev.fingerprint)
                yield ev

    # -- mappers -----------------------------------------------------------
    def _emit(self, *, title, start, end, time, venue, city, postcode, url, desc,
              fallback_venue, today, fallback_town=None) -> Optional[Event]:
        if not title or not start:
            return None
        if end and end < start:
            end = None
        if (end or start) < today:
            return None
        town = canon_town(city or None, postcode or None)
        if town == "Unknown":
            # No geo signal on the event itself. A source that DECLARED its town
            # (4th VENUES field) is trusted next — it's a real place. Only if none
            # was given do we guess from the source name, which for a venue is its
            # town but for a promoter/collective is just a label.
            if fallback_town:
                t = canon_town(fallback_town)
                town = t if t != "Unknown" else fallback_town
            elif fallback_venue:
                town = canon_town(fallback_venue or None)
        venue = venue or fallback_venue
        return Event(
            title=title, start=start, end=end, time=time,
            town=town, venue=venue,
            category=classify(title, desc or "", venue or ""),
            url=url or None, note=(desc or None), source=self.name,
        )

    def _from_jsonld(self, o: dict, venue_name: str, today: date,
                     default_town=None) -> Optional[Event]:
        from ..models import parse_date
        venue, city, pc = _loc(o)
        return self._emit(
            title=_clean(o.get("name")),
            start=parse_date(_clean(o.get("startDate"))),
            end=parse_date(_clean(o.get("endDate"))) if o.get("endDate") else None,
            time=_jsonld_time(o.get("startDate")),
            venue=venue, city=city, postcode=pc,
            url=_clean(o.get("url")), desc=_clean(o.get("description"))[:400],
            fallback_venue=venue_name, today=today, fallback_town=default_town,
        )

    def _from_ics(self, o: dict, venue_name: str, today: date,
                  default_town=None) -> Optional[Event]:
        loc = _clean(o.get("LOCATION"))
        venue, city, postcode = _split_ics_location(loc)
        if not _in_scope(city, postcode, loc):     # a Montpellier / Sweden date
            return None
        return self._emit(
            title=_clean(o.get("SUMMARY")),
            start=_ics_date(o.get("DTSTART", "")),
            end=_ics_date(o.get("DTEND", "")) if o.get("DTEND") else None,
            time=_ics_time(o.get("DTSTART", "")),
            venue=venue, city=city, postcode=postcode,
            url=_clean(o.get("URL")), desc=_clean(o.get("DESCRIPTION"))[:400],
            fallback_venue=venue_name, today=today, fallback_town=default_town,
        )


def _jsonld_time(s) -> Optional[str]:
    s = str(s or "")
    m = re.search(r"T(\d{2}):(\d{2})", s)
    if m and (m[1], m[2]) != ("00", "00"):
        return f"{m[1]}:{m[2]}"
    return None
