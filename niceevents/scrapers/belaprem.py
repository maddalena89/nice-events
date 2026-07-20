"""Belaprem — the Ville de Nice free open-air summer series at Le 109.

Every July, Tuesday–Friday 17h30–00h30, the cour intérieure of Le 109 (89 route
de Turin) hosts free concerts, DJ sets, dance workshops, a market and a kids'
corner. The nightly line-up is only published on the printed programme and on
Instagram (@belaprem_) — neither le109.nice.fr nor panda-events.com lists the
individual nights in a machine-readable way — so it's transcribed here by hand
from the official 2026 programme.

Free, single-venue, single-night events. Past nights drop at build time, so once
July is over this whole source quietly empties until next year's line-up is added.
"""
from __future__ import annotations

from datetime import date
from typing import Iterator

from ..models import Event
from .base import Scraper, register

_URL = "https://www.panda-events.com/evenement/belaprem-2026/"
_VENUE = "Belaprem · Le 109"

#: (day-in-July-2026, headline act, featured slot, workshop / activity)
NIGHTS: list[tuple[int, str, str, str]] = [
    (1,  "Opening — All Residents", "18h00–19h30", "Initiation DJ by Spæce"),
    (2,  "Funktown",                "17h30–19h00", "Cours commercial by Marine — Reia Crew"),
    (3,  "Zona de Perreo",          "19h00–20h00", "Cours salsa colombienne by Juliette"),
    (7,  "Fest Kaf",                "18h30–19h30", "Cours yoga by Capucine"),
    (8,  "Lovi x LQB",              "18h00–19h30", "Initiation DJ by Spæce"),
    (9,  "Amapiano & Afrobeats Lovers", "17h30–19h00", "Cours afro by Antonia — Reia Crew"),
    (10, "Zona de Perreo",          "19h00–20h00", "Cours salsa colombienne by Juliette"),
    (14, "Carnival Fest",           "18h30–19h30", "Cours yoga by Capucine"),
    (15, "Lui",                     "18h00–19h30", "Initiation DJ by Spæce"),
    (16, "Club Disco",              "17h30–19h00", "Cours hip-hop commercial by Mathilde — Reia Crew"),
    (17, "Zona de Perreo",          "19h00–20h00", "Cours salsa colombienne by Juliette"),
    (21, "Funana Fever",            "18h30–19h30", "Cours yoga by Capucine"),
    (22, "Nøval",                   "18h00–19h30", "Initiation DJ by Spæce"),
    (23, "Do Brasil",               "17h30–19h00", "Cours street jazz by Mathilde — Reia Crew"),
    (24, "Zona de Perreo",          "19h00–20h00", "Cours salsa colombienne by Juliette"),
    (28, "Fuego del Caribe",        "18h30–19h30", "Cours yoga by Capucine"),
    (29, "Spæce",                   "18h00–19h30", "Initiation DJ by Spæce"),
    (30, "California Love",         "17h30–19h00", "Cours hip-hop by Cixa — Reia Crew"),
    (31, "Zona de Perreo",          "19h00–20h00", "Cours salsa colombienne by Juliette"),
]


@register
class Belaprem(Scraper):
    name = "belaprem"
    label = "Belaprem (Le 109, free open-air)"

    def fetch(self) -> Iterator[Event]:
        today = date.today()
        for day, act, slot, activity in NIGHTS:
            start = date(2026, 7, day)
            if start < today:                     # night has passed — drop it
                continue
            yield Event(
                title=f"Belaprem — {act}",
                start=start,
                end=None,
                town="Nice",
                venue=_VENUE,
                category="concert",
                url=_URL,
                note=f"Free open-air · concert {slot} · {activity} · 17h30–00h30, cour du 109",
                free=True,
                source=self.name,
            )
