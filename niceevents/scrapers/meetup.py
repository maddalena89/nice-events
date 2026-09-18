"""Meetup — everything happening near Nice, swept day by day.

Meetup renders its event lists client-side: plain HTTP gets you a page shell
with zero events in it. So this one needs a real browser. What the browser gets
is a server-rendered __NEXT_DATA__ blob holding the FIRST PAGE of results, and
that is the whole difficulty here.

HOW THIS ENUMERATES, AND WHY IT LOOKS DUMB
------------------------------------------
/find/ returns **twelve** events per request. Nothing gets you page thirteen:
the `after=` cursor is ignored server-side, there is no infinite scroll, and the
"load more" fetch goes over a GraphQL call the logged-out page never makes.

Two filters ARE honoured server-side, and between them they do the job:

  * `customStartDate` / `customEndDate` — so we ask one **day** at a time.
  * `eventType=inPerson` — and this is the one that matters. Career & Business
    on a single day returned twelve events and claimed more; filtered to
    in-person, the same day returns **zero**. All twelve were webinars. Across
    every category, an in-person day near Nice runs to three to six events
    against a cap of twelve, so one day's answer is the whole answer.

Hence a flat day-by-day loop, ~90 requests, complete. The clever version — ask
for a wide window, narrow only when the answer looks full — was tried and is
WRONG here, in a way worth recording because it looks right: a 90-day window
comes back with ten events and `hasNextPage: false`, while a single day inside
that same window returns twelve *different* events and `true`. None of the
twelve appear in the ten. The wide answer is a ranked recommendation, not a page
of results, so "no next page" proves nothing, and anything that trusts it stops
early and silently — which is roughly what the previous keyword version did.

Online events are swept separately and only for a month, because they genuinely
cannot be enumerated and are hidden behind a checkbox on the site anyway.

The category axis is kept for one job: re-asking a single day that still comes
back full. Rare in person, routine online.

Meetup's public GraphQL needs an OAuth key; the search page does not. We only
read pages any logged-out visitor sees, at a polite crawl rate — we never log
in, join, or touch anything behind an account.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import date, timedelta
from typing import Iterator, Optional

from selectolax.parser import HTMLParser

from ..models import Event, classify, parse_date, parse_time
from .base import BrowserScraper, register

log = logging.getLogger(__name__)

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

# Meetup's own category ids, read off the filter chips on /find/. Every event
# carries exactly one, and together they cover the whole catalogue — which is
# the point: the keyword list this replaced could only ever find topics somebody
# had thought to name. Ids are Meetup's, not ours; if a chip disappears the
# search simply returns nothing for it, which the run log will show as a
# category contributing zero.
CATEGORIES = {
    "405": "Career & Business",
    "395": "Music",
    "436": "Science & Education",
    "449": "Support & Coaching",
    "467": "Writing",
    "482": "Sports & Fitness",
    "511": "Health & Wellbeing",
    "521": "Art & Culture",
    "535": "Games",
    "546": "Technology",
    "571": "Hobbies & Passions",
    "593": "Religion & Spirituality",
    "604": "Community & Environment",
    "612": "Dancing",
    "622": "Identity & Language",
    "642": "Movements & Politics",
    "652": "Social Activities",
    "673": "Parents & Family",
    "684": "Travel & Outdoor",
    "701": "Pets & Animals",
}

RADIUS_MILES = 25  # Nice -> reaches Antibes, Cannes, Monaco

#: Meetup's own words for the venue filter. `eventType=inPerson` is honoured
#: server-side and is the single most useful lever here: it takes a category-day
#: from twelve-and-overflowing down to nothing, because the overflow was all
#: webinars. Spelling matters — "IN_PERSON" is silently ignored.
IN_PERSON = "inPerson"
ONLINE = "online"

#: How far ahead to look for real, in-person events. Matches the horizon the
#: site's own town pages use.
HORIZON_DAYS = 90

#: Online events get a shorter horizon on purpose. They cannot be enumerated:
#: a single day of them overflows twelve in several categories at once, and
#: they are mostly the same handful of daily recurring language-practice and
#: webinar groups repeating forever. They are also hidden behind a checkbox on
#: the site. So: take a month of them, best-effort, and spend the request
#: budget on the events someone can actually turn up to.
ONLINE_HORIZON_DAYS = 14   # was 30; see below

#: Results Meetup returns per request. If a window comes back with this many,
#: assume there are more behind it and split. Read off pageInfo when Meetup
#: provides it; this is the fallback and the split threshold.
PAGE_SIZE = 12

#: Hard ceiling on requests per run. The sweep is bounded by the calendar
#: anyway (about 120 requests); this is the backstop against a Meetup change
#: that makes every day look full and sends every one of them through the
#: per-category split.
MAX_REQUESTS = 500


@register
class Meetup(BrowserScraper):
    name = "meetup"
    label = "Meetup (all categories, near Nice)"
    #: Half a second on top of a rendered page load that already costs one to
    #: two, so the real interval is still well over a second. Was 1.0.
    #:
    #: Both this and the shorter online horizon are about the workflow's time
    #: limit. The day-by-day sweep took the whole scrape from about 26 minutes to
    #: 39 against a 45-minute cut-off, and a run that hits the cut-off is killed
    #: and the site does not update that day. Raising the limit is the better fix
    #: but needs a token with `workflow` scope; until then the time comes back
    #: from here. Online events were the cheap place to take it from: they are
    #: hidden behind a checkbox and a fortnight of them is plenty. In-person
    #: coverage, the reason this scraper was rewritten, is untouched at 90 days.
    delay = 0.5

    def fetch(self) -> Iterator[Event]:
        found: dict[str, Event] = {}
        self._requests = 0
        today = date.today()

        with self._session() as get:
            # In-person first and in full: these are the events the site is
            # actually for, and they enumerate cleanly.
            self._sweep(get, IN_PERSON, today, HORIZON_DAYS, found,
                        split_full_days=True)
            # Then a bounded pass for online, which cannot be enumerated (see
            # ONLINE_HORIZON_DAYS) but must not vanish either. No splitting:
            # essentially every online day is full, so splitting would spend
            # 20 extra requests on each of them — six hundred requests to
            # exhaust the webinar listings, which is both slower than the whole
            # rest of the scrape and a poor use of it. Take the twelve Meetup
            # ranks highest per day and move on.
            self._sweep(get, ONLINE, today, ONLINE_HORIZON_DAYS, found,
                        split_full_days=False)

        log.info("%s: %d events in %d requests", self.name, len(found), self._requests)
        yield from found.values()

    def _sweep(self, get, event_type: str, start: date, days: int,
               found: dict[str, Event], split_full_days: bool = True) -> None:
        """Ask for one day at a time, across the whole horizon.

        A flat loop, deliberately, rather than anything cleverer. The obvious
        optimisation — ask for a wide window and narrow it only when the answer
        looks full — does not work here: a 90-day window comes back with ten
        ranked events and `hasNextPage: false`, while a single day inside that
        same window returns twelve *different* events and `true`. The wide
        answer is a recommendation, not a page of results, so "no next page"
        proves nothing and any walk that trusts it stops early and silently.

        One day is small enough that the answer is the whole answer: in-person
        days near Nice run to three to six events against a cap of twelve.
        """
        for i in range(days + 1):
            if self._requests >= MAX_REQUESTS:
                log.warning("%s: hit the %d-request ceiling during the %s sweep",
                            self.name, MAX_REQUESTS, event_type)
                return
            day = start + timedelta(days=i)
            self._requests += 1
            html = get(self._url(event_type, day, day),
                       wait_for="#__NEXT_DATA__, a[href*='/events/']")
            if not html:
                continue

            events, more = self._parse(html, online=event_type == ONLINE)
            for ev in events:
                found.setdefault(ev.fingerprint, ev)

            if more and split_full_days:
                # A day that fills the page has more behind it than we were
                # shown. Categories are the only other axis the server honours,
                # so re-ask that one day per category. Rare in person.
                self._split_by_category(get, event_type, day, found)
            elif more:
                log.info("%s: %s %s was full; not splitting", self.name,
                         event_type, day)

    def _split_by_category(self, get, event_type: str, day: date,
                           found: dict[str, Event]) -> None:
        for cat_id in CATEGORIES:
            if self._requests >= MAX_REQUESTS:
                return
            self._requests += 1
            html = get(self._url(event_type, day, day, cat_id),
                       wait_for="#__NEXT_DATA__, a[href*='/events/']")
            if not html:
                continue
            events, more = self._parse(html, online=event_type == ONLINE)
            for ev in events:
                found.setdefault(ev.fingerprint, ev)
            if more:
                # One category, one day, still full. Nothing left to narrow by.
                log.warning("%s: %s category %s on %s is full and cannot be "
                            "narrowed further — the overflow is unreachable",
                            self.name, event_type, cat_id, day)

    @staticmethod
    def _url(event_type: str, start: date, end: date,
             cat_id: Optional[str] = None) -> str:
        # The offset is Meetup's own (US/Eastern, what its UI sends). A day
        # boundary therefore lands a few hours inside our day; consecutive days
        # cover each other and results are deduped by fingerprint, so an event
        # can move between adjacent days but never fall out of every one.
        url = (f"{BASE}/find/?location=fr--nice&source=EVENTS"
               f"&distance={RADIUS_MILES}miles&eventType={event_type}"
               f"&customStartDate={start.isoformat()}T00:00:00-04:00"
               f"&customEndDate={end.isoformat()}T23:59:00-04:00")
        if cat_id:
            url += f"&categoryId={cat_id}"
        return url

    def _parse(self, html: str, online: bool = False) -> tuple[list[Event], bool]:
        """Returns (events, window_looked_full).

        `online` says the request itself asked for online events, so every
        result is one. That beats inferring it from the title and venue: the
        sniffing in _is_online exists for the in-person sweep, where Meetup
        occasionally returns a webinar anyway, and it can only ever catch the
        ones that say so in words.
        """
        tree = HTMLParser(html)

        events, more = self._from_next_data(tree, online)
        if events:
            return events, more

        # Fallback: read the rendered cards. No pageInfo to consult here, so
        # infer fullness from the count.
        cards = list(self._from_cards(tree, online))
        return cards, len(cards) >= PAGE_SIZE

    def _from_next_data(self, tree: HTMLParser,
                        online: bool = False) -> tuple[list[Event], bool]:
        node = tree.css_first("#__NEXT_DATA__")
        if not node:
            return [], False
        try:
            data = json.loads(node.text() or "{}")
        except json.JSONDecodeError:
            return [], False
        out = []
        for obj in _find_events(data):
            ev = self._from_obj(obj, online)
            if ev:
                out.append(ev)
        # BOTH conditions, and the count is the load-bearing one. The payload
        # carries PageInfo objects for things that are not our results — the
        # recommended-events rail, group carousels — and any of them saying
        # hasNextPage made a six-event window look full. That sent the walk
        # subdividing down to single days everywhere, burning requests to
        # re-fetch the same handful of events.
        #
        # A window that came back with fewer than a full page is finished, no
        # matter what any PageInfo says. One that IS full still needs Meetup to
        # confirm there is more behind it before we pay to split.
        return out, len(out) >= PAGE_SIZE and _has_next_page(data)

    def _from_obj(self, obj: dict, force_online: bool = False) -> Optional[Event]:
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

        online = force_online or _is_online(obj, venue, title)
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

        # The time is NOT repeated here. It belongs to the structured `time`
        # field, which the page renders on its own ahead of the note.
        # site._note_full does strip a leading "19:00 · " if one arrives, so this
        # is not load-bearing — but generating a duplicate and relying on a
        # downstream stripper to hide it is how the note ended up carrying the
        # only surviving copy of the time for as long as parse_time was returning
        # 00:00 for these ISO stamps.
        bits = [b for b in (gname, desc) if b]
        return Event(
            title=str(title).strip(),
            start=start,
            time=parse_time(str(when)),
            town=town,
            venue=venue,
            category=classify(title, gname, desc),
            url=url,
            note=" · ".join(bits)[:400] or None,
            # An absent feeSettings is missing information, not proof the event
            # is free. Trusting it tagged 82 of 95 Meetup events free, including
            # a bar crawl selling four bars, four shots and VIP entry. A missing
            # free tag is harmless; a wrong one misleads someone about money.
            free=bool(obj.get("isFree")),
            online=online,
            source=self.name,
        )

    def _from_cards(self, tree: HTMLParser, online: bool = False) -> Iterator[Event]:
        """Read the rendered cards — the safety net when __NEXT_DATA__ moves.

        Anchored on the event link and the <time datetime> beside it, NOT on
        test-ids or class names. The previous version looked for
        `[data-testid='categoryResults-eventCard']`, which Meetup has since
        removed; the selector matched nothing, so the fallback silently yielded
        nothing and the "safety net" was a hole. An anchor to /events/<id> and a
        machine-readable timestamp are what the page is *for*, so they are the
        parts least likely to be renamed.
        """
        seen: set[str] = set()
        for a in tree.css("a[href*='/events/']"):
            href = a.attributes.get("href", "") or ""
            m = re.search(r"/events/(\d+)", href)
            if not m or m.group(1) in seen:
                continue

            # The anchor IS the card: Meetup wraps the whole tile in the link,
            # so its subtree holds the title, the <time> and the group name.
            # Walking up to a "container" instead lands on an ancestor holding
            # several events, and every one of them then reports the first
            # card's title — which is exactly what the earlier version did.
            # Only climb if this anchor has no heading of its own, and stop the
            # moment the ancestor covers more than this one event.
            card = a
            if card.css_first("h1, h2, h3, h4") is None:
                for _ in range(3):
                    parent = card.parent
                    if parent is None or len(parent.css("a[href*='/events/']")) > 1:
                        break
                    card = parent

            block = re.sub(r"\s+", " ", card.text() or "")
            title_node = card.css_first("h1, h2, h3, h4")
            title = re.sub(r"\s+", " ", (title_node.text() if title_node else "")).strip()
            if not title:
                continue

            # Prefer the machine-readable timestamp; fall back to reading the
            # card's text the way a person would.
            start = time_str = None
            t = card.css_first("time[datetime]")
            if t:
                raw = (t.attributes.get("datetime") or "").split("[")[0]
                start, time_str = parse_date(raw), parse_time(raw)
            if not start:
                start, time_str = parse_date(block), parse_time(block)
            if not start or start < date.today():
                continue

            seen.add(m.group(1))
            yield Event(
                title=title,
                start=start,
                time=time_str,
                town="Online" if online else "Nice",
                online=online,
                category=classify(title, block),
                url=href if href.startswith("http") else BASE + href,
                note=block[:250] or None,
                source=self.name,
            )


def _has_next_page(data) -> bool:
    """Did Meetup say there are results we did not get?

    This is the signal the whole date walk turns on, so it is read from Meetup's
    own pageInfo rather than guessed from a count.
    """
    found = False

    def walk(o):
        nonlocal found
        if found:
            return
        if isinstance(o, dict):
            if o.get("__typename") == "PageInfo" and o.get("hasNextPage") is True:
                found = True
                return
            for v in o.values():
                if isinstance(v, (dict, list)):
                    walk(v)
        elif isinstance(o, list):
            for item in o:
                walk(item)

    walk(data)
    return found


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
