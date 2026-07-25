"""Flag a specific already-listed event as cancelled.

Events get called off after we've scraped them (a milonga cancelled, a concert
postponed). We can't un-scrape them, so instead of quietly dropping them, we mark
them here and the site shows them struck through with an "Annulé" badge. That way
someone who saw the poster understands the night is off, rather than turning up.

A line matches by title (accent- and case-insensitive substring) + town + the
exact date. Add a line, the next build shows it cancelled. Delete the line once
the date has passed to keep this tidy.
"""
from __future__ import annotations

import unicodedata


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


#: (title contains, town, YYYY-MM-DD, note shown). Keep the title fragment short
#: and distinctive so it matches however the source spells the full title.
CANCELLED: list[tuple] = [
    ("milonga de l amitie", "Nice", "2026-07-25", "Annulée"),
]


def mark_cancelled(events: list[dict]) -> list[dict]:
    """Set cancelled=True (and a note) on any event dict that matches a line."""
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
