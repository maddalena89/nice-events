"""Mark an event as called off, so it shows struck through instead of vanishing.

Someone who saw the poster needs to be told the night is off. Dropping the event
silently is worse than useless: they turn up anyway.

Two routes in, and the automatic one should do the work.

1. AUTOMATIC — the source says so in the title. Calendars that are maintained by
   a human tend to retitle rather than delete, because their own readers need to
   see the cancellation: "(ANNULEE) MILONGA de la Casita". We read that word and
   mark the event, then strip the marker so the title stays readable next to the
   badge the page already draws.

   This exists because of 6 August 2026. The Casita milonga was cancelled, the
   reference tango agenda said "(ANNULEE)" plainly in the event title, and the
   site still advertised it as on — because nothing anywhere read that word, and
   cancellations were only ever the hand-written list below. Three layers (the
   scraper, the build, the daily health check) and not one of them was looking.

   Title only, never the description. A description saying "en cas d'annulation,
   remboursement sous 8 jours" is boilerplate, not a cancellation, and marking a
   live event as cancelled is the same harm in reverse.

2. MANUAL — the list below, for when a cancellation reaches you some other way
   (an email, a poster, a message from the venue) and no source has said it. A
   line matches by title (accent- and case-insensitive substring) + town + the
   exact date. Delete the line once the date has passed, to keep this tidy.
"""
from __future__ import annotations

import re
import unicodedata


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


#: (title contains, town, YYYY-MM-DD, note shown). Keep the title fragment short
#: and distinctive so it matches however the source spells the full title.
CANCELLED: list[tuple] = [
    ("milonga de l amitie", "Nice", "2026-07-25", "Annulée"),
    ("casita", "Nice", "2026-08-02", "Annulée"),
    # 2026-08-08 health check. Panda deleted the event page — the url 404s and
    # it is gone from their agenda and their own search — and Songkick marks the
    # concert "Canceled". Two independent signals, but neither is the venue, so
    # if La Siesta or REF confirm the night is on, delete this line.
    # Nothing in the feed says ANNULE, because the promoter removed the page
    # instead of retitling it, so the automatic route above cannot see this one.
    ("tini gessler", "Antibes", "2026-08-13", "Annulée"),
]


#: The word, however the source spells it: ANNULEE, Annulée, annulés, CANCELLED.
#: Matched against the accent-folded title, so the bare stem is enough.
_SAYS_CANCELLED = re.compile(r"\bannul\w*|\bcancell?ed\b")

#: The same word as it appears in the real title, with the brackets and the
#: punctuation that usually trails it, so it can be lifted out cleanly:
#: "(ANNULEE) MILONGA de la Casita" -> "MILONGA de la Casita".
_MARKER = re.compile(r"^\W*(?:annul\w*|cancell?ed)\W*", re.I)


def _strip_marker(title: str) -> str:
    """Take the cancellation word out of the title; the page draws a badge."""
    cleaned = _MARKER.sub("", title or "", count=1).strip(" -–—:·,")
    return cleaned or title


def mark_cancelled(events: list[dict]) -> list[dict]:
    """Set cancelled=True (and a note) on anything a source or the list calls off."""
    for e in events:
        if _SAYS_CANCELLED.search(_fold(e.get("title"))):
            e["cancelled"] = True
            e.setdefault("cancel_note", "Annulé")
            e["title"] = _strip_marker(e.get("title") or "")

    if not CANCELLED:
        return events
    for e in events:
        t = _fold(e.get("title"))
        town = (e.get("town") or "").strip()
        start = (e.get("start") or "").strip()
        for needle, ctown, cdate, note in CANCELLED:
            if _fold(needle) in t and town == ctown and start == cdate:
                e["cancelled"] = True
                if note:
                    e["cancel_note"] = note
    return events
