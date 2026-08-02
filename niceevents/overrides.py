"""Manual, per-event category overrides.

The keyword classifier gets the large majority right, but a few events carry a
source type label or wording that lands them in the wrong tab, and changing the
shared keywords to fix one event risks moving ten others. This is the safe
escape hatch: pin a single event's category by its URL (most precise) or by a
title substring plus town. Applied at build time, after all other category
logic, so it always wins.

    (url exact, title contains, town, category)

Any field left None is a wildcard; the fields you DO set must all match. Delete
a line once the event has passed, to keep this tidy.
"""
from __future__ import annotations

import re
import unicodedata

_NON_ALNUM = re.compile(r"[^a-z0-9]+")

#: The categories a row may be pinned to (matches the site's tabs).
VALID = {"concert", "scene", "expo", "danse", "atelier", "business",
         "social", "sport", "marche", "visite", "autre"}


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return _NON_ALNUM.sub(" ", s).strip()


#: (url exact, title contains, town, category)
OVERRIDES: list[tuple] = [
    # Awareness event with a short-film premiere, tagged Business by the source.
    ("https://www.eventbrite.com/e/billets-journee-mondiale-de-la-lutte-contre-la-traite-detres-humains-1994946039306",
     None, None, "social"),
    # An AI build workshop: fits both Workshops and Business/Tech, and the site
    # allows one tab, so pin it to Business, tech & AI where the AI crowd looks.
    ("https://www.meetup.com/nice-nomads/events/315842030/", None, None, "business"),
    # Tagged Concert by the source; the curator files it under Theatre.
    ("https://www.helloasso.com/associations/academie-internationale-d-ete-de-nice/evenements/mercredi-5-aout-20h",
     None, None, "scene"),
    # A Maracatu trial class; reads as a Concert only because the venue is
    # "Offjazz". It is a workshop.
    ("https://www.meetup.com/echanges-linguistiques-de-la-cote-dazur/events/315696611/",
     None, None, "atelier"),
]


def _matches(e: dict, url, needle, town) -> bool:
    if url is not None and (e.get("url") or "").strip() != url:
        return False
    if needle is not None and _fold(needle) not in _fold(e.get("title")):
        return False
    if town is not None and (e.get("town") or "").strip() != town:
        return False
    return any(x is not None for x in (url, needle, town))


def apply_override(e: dict) -> None:
    """Pin a row's category in place if a line matches. First match wins."""
    for url, needle, town, cat in OVERRIDES:
        if cat in VALID and _matches(e, url, needle, town):
            e["category"] = cat
            return
