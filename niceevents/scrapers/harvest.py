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

import html
import json
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Iterator, Optional
from zoneinfo import ZoneInfo

from selectolax.parser import HTMLParser

from ..models import Event, canon_town, classify, slugify
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
    # La Zonmé moved OUT of this list on 2026-08-06. scrapers/lazonme.py now reads
    # the very same calendar (identical CAL_ID) through GCalICS, and it knows
    # things this generic entry cannot: the venue name, a link to fall back on,
    # and that an ambiguous title at a music venue is a concert, not "other".
    # Two scrapers on one calendar is not a duplicate on the page — they share a
    # fingerprint and merge — but harvest runs FIRST, so its poorer category and
    # venue were the ones that stuck, and the dedicated scraper's better values
    # were silently discarded. One owner per source.
    #
    # Swingin'Nice stays for now: scrapers/swing.py reads a DIFFERENT calendar id
    # (cf05fbae…@group) from the one here (swing06events@gmail.com). They may be
    # the same programme migrated to a group calendar, or two live calendars.
    # Until that is confirmed against both feeds, dropping this risks losing the
    # swing nights outright, and keeping it costs one fetch and a merge.
    ("Swingin'Nice",
     "https://calendar.google.com/calendar/ical/"
     "swing06events%40gmail.com/public/basic.ics",
     "ics", "Nice"),
    # Liste Salsa d'Olivier — salsa / bachata / kizomba socials, whole 06. Each
    # entry carries its own address, so the town comes from the LOCATION itself.
    ("Liste Salsa d'Olivier",
     "https://salsa.faurax.fr/calendrier.php?dpt=06",
     "ics"),
    # Agenda Tango Argentin Nice Riviera 06 AM — the reference tango calendar for
    # the department, kept by hand and linked as "le calendrier référence" by the
    # local associations. This REPLACED the tango-argentin.fr scraper (see
    # scrapers/__init__.py) because it is the only tango source that publishes
    # CANCELLATIONS: a called-off milonga is retitled "(ANNULEE) MILONGA …", which
    # cancellations.py reads. It also carries venues tango-argentin.fr never
    # listed — Cannes, Antibes, Plascassier, La Trésorerie, Arty Studio.
    #
    # Entries are all-day, but they are NOT untimed: the organiser writes the
    # time, the DJ and the price into the description ("> Milonga de 21h00 à
    # 01h30 … TARIF : 12€"). _time_from_text and _price_from_text read them, so
    # nothing is lost against the old tango-argentin.fr scraper.
    # Every event carries its own address, so the town comes from the LOCATION.
    ("Agenda Tango Argentin Nice Riviera 06",
     "https://calendar.google.com/calendar/ical/"
     "agendatangoam%40gmail.com/public/basic.ics",
     "ics", "Nice"),
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


#: Google Calendar writes a ONE-OFF event in UTC ("…T180000Z") and a RECURRING
#: series in a named zone ("DTSTART;TZID=Europe/Paris:…T200000"). _ics_prop has
#: already thrown the TZID parameter away by the time we get here, so a trailing
#: Z is the only signal left that a value still needs converting.
#:
#: Reading the digits and ignoring that Z published every one-off La Zonmé gig
#: two hours early in summer and one hour early in winter — an offset that
#: tracked European daylight saving exactly, which is the tell. Doors at 20:00
#: were advertised as 18:00. Found 2026-08-07.
PARIS = ZoneInfo("Europe/Paris")


def _ics_date(val: str) -> Optional[date]:
    """The date AS THE CALENDAR WROTE IT, with no timezone conversion.

    Deliberately raw, because _ics_starts materialises an RRULE by walking this
    date forward and re-attaching the original clock time: that sequence has to
    stay in the calendar's own frame or every occurrence drifts. For the date a
    visitor should actually see, use _ics_dt.
    """
    m = re.match(r"(\d{4})(\d{2})(\d{2})", val)
    if not m:
        return None
    try:
        return date(int(m[1]), int(m[2]), int(m[3]))
    except ValueError:
        return None


def _ics_dt(val: str) -> tuple[Optional[date], Optional[str]]:
    """(local date, 'HH:MM' or None) for an ICS value, UTC converted to Nice.

    Returns the pair together because the conversion can roll the DATE as well
    as the clock: a milonga starting 23:30 UTC is 01:30 the next morning here.
    Taking the date from one function and the time from another would put those
    two halves in different timezones.
    """
    m = re.match(r"(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2})(?:\d{2})?(Z)?)?",
                 val.strip())
    if not m:
        return None, None
    y, mo, d, hh, mi, zulu = m.groups()
    try:
        day = date(int(y), int(mo), int(d))
    except ValueError:
        return None, None
    if hh is None:                      # an all-day entry: a date, no clock
        return day, None
    hh, mi = int(hh), int(mi)
    if zulu:
        moment = datetime(int(y), int(mo), int(d), hh, mi,
                          tzinfo=timezone.utc).astimezone(PARIS)
        day, hh, mi = moment.date(), moment.hour, moment.minute
    # Midnight is how these calendars say "no time given", not a real start.
    return day, (None if (hh, mi) == (0, 0) else f"{hh:02d}:{mi:02d}")


def _ics_time(val: str) -> Optional[str]:
    return _ics_dt(val)[1]


def _ics_end_date(dtstart: str, dtend: str) -> Optional[date]:
    """The last date a visitor should see, in Nice time, or None for one day.

    The same two traps gcal already handles, so this reads the end the same way
    rather than inventing a second rule.

    A date-only DTEND is EXCLUSIVE by spec, so a genuine one day entry carries
    the following date. And a TIMED end on the day after the start is a night
    that runs past midnight: a milonga from 21:00 to 01:00 is one night out,
    not a two-day event.

    Reading DTEND raw dodged the second trap only while a calendar happened to
    write local time. The tango feeds write it plainly, so 26 evening events,
    nearly all milongas, were published as two day ranges.
    """
    if not dtend:
        return None
    start, _ = _ics_dt(dtstart)
    end, _ = _ics_dt(dtend)
    if not start or not end:
        return None
    if "T" not in dtend.upper():        # date-only: DTEND is exclusive
        end -= timedelta(days=1)
    elif (end - start).days == 1:
        hm = _ics_dt(dtend)[1]
        # Anything finishing before dawn belongs to the night it started on.
        # A real two-day event ending at 18:00 tomorrow keeps its second day.
        # (gcal collapses every timed next-day end without checking the hour;
        # this cutoff is the finer version and gcal is worth aligning to it.)
        if hm is None or hm < "06:00":
            end = start
    return None if end <= start else end


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


# ------------------------------------------------- details hidden in the text
#
# An all-day VEVENT is not the same as an event with no time. Hand-kept calendars
# put the real detail in the DESCRIPTION and leave DTSTART as a plain date:
#
#   > Milonga de 21h00 à 01h30   Tdj : Pierre Gabrielli    TARIF : 12€
#
# Reading only DTSTART throws that away and publishes a milonga with no time,
# which on a what's-on is most of the answer missing.
#
# _events_from_ics has already turned the feed's "\n" escapes into spaces, so
# what arrives here is one long line whose logical breaks are runs of two or more
# spaces and the ">" bullets the authors type.
_SEGMENT = re.compile(r"\s{2,}|[>•·]")

#: A segment describing something BEFORE the main event. "La milonga sera
#: précédée d'un cours de tango gratuit de 18h45 à 19h30" is a class, and taking
#: its time would start the milonga three quarters of an hour early.
_PRELUDE = re.compile(r"cours|pr[ée]c[ée]d|stage|initiation|atelier|d[ée]butant|workshop", re.I)

_RANGE = re.compile(r"\bde\s*(\d{1,2})\s*h\s*(\d{2})?\s*(?:à|a|au|jusqu|[-–])", re.I)
_FROM = re.compile(r"(?:à partir de|a partir de|d[èe]s|d[ée]but(?:e)?\s*(?:à|a)?)\s*(\d{1,2})\s*h\s*(\d{2})?", re.I)
_PRICE_LINE = re.compile(r"\b(?:tarifs?|prix|entr[ée]e)\s*:\s*(.{1,60}?)\s*$", re.I)


def _segments(text: str) -> list[str]:
    raw = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    # Authors pad before the colon ("TARIFS  : 6€"). That padding is not a line
    # break, and splitting on it strands the label from its value, so the price
    # line stops being recognisable. Close the gap before splitting.
    raw = re.sub(r"\s+:", " :", raw)
    return [s.strip() for s in _SEGMENT.split(raw) if s and s.strip()]


def _time_from_text(text: str) -> Optional[str]:
    """The main event's start time, read out of a free-text description.

    Segments that describe a warm-up class are skipped first, then the earliest
    remaining segment wins. Only an explicit range ("de 21h00 à 01h30") or an
    explicit start ("à partir de 19h") counts: a bare "19h" anywhere in prose is
    just as likely to be a doors time, a deadline or a phone number, and a wrong
    time is worse than none.
    """
    for seg in _segments(text):
        if _PRELUDE.search(seg):
            # A class, and there is no safe way to derive the main start from it.
            # "précédée d'un cours de 18h45 à 19h30" happens to end when the
            # milonga begins, but plenty of others do not, and there is no way to
            # tell which from the text. No time at all beats an hour early.
            continue
        m = _RANGE.search(seg) or _FROM.search(seg)
        if m:
            h, mi = int(m[1]), int(m[2] or 0)
            if 0 <= h <= 23 and 0 <= mi <= 59:
                return f"{h:02d}:{mi:02d}"
    return None


#: A price longer than this is a tariff TABLE, not a price. The Cinéma Tango
#: entry runs "Cours seul 12 € / adhérents 10 € - Milonga seule 15 € / adhérents
#: 12 € - Cours + Milonga 20 € / adhérents 15 €": there is no single number to
#: put on a card, and cutting it to fit produces a garbled half-sentence that
#: reads as a real price. The description already carries the full table, so
#: leave the field empty and let it be read there.
_PRICE_MAX = 45


def _price_from_text(text: str) -> Optional[str]:
    """The price as the organiser wrote it: "12€", "6€ (adhérents) / 8€"."""
    for seg in _segments(text):
        m = _PRICE_LINE.search(seg)
        if m:
            price = m[1].strip(" .:-–")
            if price and len(price) <= _PRICE_MAX and re.search(r"\d|gratuit|libre", price, re.I):
                return price
    return None


def _town_from_text(loc: str) -> Optional[str]:
    """A known 06 commune NAMED in a location that carries no usable postcode.

    Hand-kept calendars write addresses freely: "12ter Place Garibaldi 06 NICE"
    has the department number but not a postcode, so the postcode split finds
    nothing and the town falls back to the feed's own name — which is how a
    calendar called "Agenda Tango Argentin Nice Riviera 06" ends up in the town
    column. Read the commune out of the text instead.

    Longest name first, so "Saint-Jean-Cap-Ferrat" is not beaten by a stray
    "Saint", and matched on whole words so "Nice" inside "Nice Riviera" only ever
    resolves to the commune it actually is.
    """
    from ..models import _TOWN_CANON

    words = slugify(loc or "").split("-")
    for key in sorted(_TOWN_CANON, key=lambda k: -k.count("-")):
        parts = key.split("-")
        n = len(parts)
        if any(words[i:i + n] == parts for i in range(len(words) - n + 1)):
            return _TOWN_CANON[key]
    return None


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
        # Carry the trailing Z through to every occurrence. Drop it and each
        # materialised date looks like a local time, so a UTC-written series
        # would be published an hour or two early — the same bug _ics_dt exists
        # to stop, sneaking back in through the recurrence fan-out.
        tsuffix = ("T" + (t if len(t) == 6 else t + "00")
                   + ("Z" if dt.rstrip().endswith("Z") else ""))
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
    # Each venue's iCal/JSON-LD feed is complete every run (RRULEs are expanded in
    # full, no pagination), so a recurring date the calendar no longer returns —
    # a milonga the organiser cancelled with an EXDATE — is a genuine removal, not
    # a truncated scrape. Reconcile prunes it (title still listed on later dates,
    # this date gone) instead of leaving a ghost on the site until the day passes.
    reconciles_dates = True

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
              fallback_venue, today, fallback_town=None, price=None) -> Optional[Event]:
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
            url=url or None, note=(desc or None), price=price or None,
            source=self.name,
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
        if not postcode and canon_town(city) == "Unknown":
            city = _town_from_text(loc) or city    # "…Place Garibaldi 06 NICE"
        # Read the WHOLE description for details, then keep only the first 400
        # characters as the note. These calendars put the time and price in the
        # middle of a long entry (after the organiser, before the address), so
        # parsing the truncated note would find them only by luck.
        desc = _clean(o.get("DESCRIPTION"))
        # One call, so the date and the clock time can never end up in different
        # timezones — converting a UTC start can move it onto the next day.
        start, start_time = _ics_dt(o.get("DTSTART", ""))
        return self._emit(
            title=_clean(o.get("SUMMARY")),
            start=start,
            # Read in the same frame as the start, and collapse a night that
            # runs past midnight back onto the day it started. See
            # _ics_end_date: reading DTEND raw kept one night out looking like
            # a two-day event whenever the calendar wrote a plain local time.
            end=_ics_end_date(o.get("DTSTART", ""), o.get("DTEND", "")),
            # An all-day entry is not an event without a time: it is an event
            # whose time is written in words.
            time=start_time or _time_from_text(desc),
            price=_price_from_text(desc),
            venue=venue, city=city, postcode=postcode,
            url=_clean(o.get("URL")), desc=desc[:400],
            fallback_venue=venue_name, today=today, fallback_town=default_town,
        )


def _jsonld_time(s) -> Optional[str]:
    s = str(s or "")
    m = re.search(r"T(\d{2}):(\d{2})", s)
    if m and (m[1], m[2]) != ("00", "00"):
        return f"{m[1]}:{m[2]}"
    return None
