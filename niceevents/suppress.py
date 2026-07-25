"""Drop specific phantom / dead events from the build entirely.

Scrapers sometimes hold on to a listing whose detail page has since gone (a
404), or that was published with a nonsense date. Those are not cancelled
events (which we keep and strike through so people know a night is off) - they
simply are not real, and should vanish from the site.

A line matches a scraped event and removes it before it ever reaches the page.
Match on the URL when you have it (most precise, survives title tweaks), or on
title (accent- and case-insensitive substring) + town. Add the exact date too
if you only want to drop one occurrence of a repeating title.

    ("https://www.nice.fr/agenda/fete-de-fin-dannee/", None, None, None)
    (None, "fete de fin d annee", "Nice", "2026-07-28")

Delete a line once its date has passed to keep this tidy.
"""
from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _fold(s: str) -> str:
    # Strip accents, lowercase, and collapse every run of punctuation/space to a
    # single space so "Fête de fin d'année" and "fete de fin d annee" match.
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return _NON_ALNUM.sub(" ", s).strip()


#: (url exact, title contains, town, YYYY-MM-DD). Any field left None is a
#: wildcard; the fields you DO set must all match for the event to be dropped.
#:
#: IMPORTANT: do NOT add a nice.fr event just because its /agenda/<slug>/ page
#: returns 404 to an automated fetch. nice.fr blocks bots (429/404), so that is
#: NOT proof the event is dead. Verify against the source of truth first:
#:   https://www.nice.fr/wp-json/wp/v2/events?search=<title>
#: If the WordPress API still lists it with a future date, it is REAL. Only add
#: events here that are genuinely gone or bogus in the source itself.
SUPPRESSED: list[tuple] = [
]


def _matches(e: dict, url, needle, town, date) -> bool:
    if url is not None and (e.get("url") or "").strip() != url:
        return False
    if needle is not None and _fold(needle) not in _fold(e.get("title")):
        return False
    if town is not None and (e.get("town") or "").strip() != town:
        return False
    if date is not None and (e.get("start") or "").strip() != date:
        return False
    # A line of all-None would drop everything; treat it as a no-op instead.
    return any(x is not None for x in (url, needle, town, date))


def drop_suppressed(events: list[dict]) -> list[dict]:
    """Return events with any that match a SUPPRESSED line removed."""
    if not SUPPRESSED:
        return events
    return [
        e for e in events
        if not any(_matches(e, *line) for line in SUPPRESSED)
    ]
