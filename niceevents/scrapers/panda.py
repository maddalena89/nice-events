"""Panda Events — the 109 / Frigo 16 / Théâtre Lino Ventura live-music promoter.

Panda programmes most of the gig calendar at Le 109 (Frigo 16 club, the main
courtyard) plus the REF Sessions, REF Festival and summer beach dates. Their
site is WordPress, but the event DATE shown on each card is NOT the value the
REST API returns (that's the post's publish date — e.g. Acid Pauli is published
in July yet plays in December), so the agenda can't be read cleanly from the API.

Until the live agenda parser is wired up, this is a hand-checked snapshot of the
published Panda calendar. Dates/venues/prices are transcribed from panda-events.com.
Past dates drop at build time and overlaps collapse on the shared fingerprint, so
it degrades gracefully; refresh when Panda announces a new season.

Venues 'Le 109', 'Frigo 16' and 'Théâtre Lino Ventura' are all in Nice; the
summer "hors les murs" beach dates carry their real town (Antibes, Cap-Ferrat).
"""
from __future__ import annotations

from datetime import date
from typing import Iterator

from ..models import Event, classify
from .base import Scraper, register

_BASE = "https://www.panda-events.com/evenement/"

#: (start, title, town, venue, price-note, free, slug)
SHOWS: list[tuple[str, str, str, str, str, bool, str]] = [
    ("2026-08-13", "REF à la Plage #03 — Tini Gessler", "Antibes", "La Siesta", "à partir de 21 €", False, "ref-a-la-plage-03-tini-gessler"),
    ("2026-08-20", "REF à la Plage #04 — Silvie Loto", "Antibes", "La Siesta", "à partir de 21 €", False, "ref-a-la-plage-04-silvie-loto"),
    ("2026-08-21", "Crossover Summer : Mosimann & Friends", "Saint-Jean-Cap-Ferrat", "", "à partir de 30 € · sold out", False, "crossover-summer-mosimann-friends"),
    ("2026-09-04", "Platurne XXL 2", "Nice", "Le 109", "à partir de 21 €", False, "platurne-xxl-2"),
    ("2026-09-18", "Yoyaku x REF Session #15", "Nice", "Frigo 16 · Le 109", "à partir de 10 €", False, "yoyaku-x-ref-session-15"),
    ("2026-09-25", "Dje Baleti — Gigi de Nissa", "Nice", "Frigo 16 · Le 109", "gratuit", True, "clown-power-dje-baleti-gigi-de-nissa"),
    ("2026-10-10", "Liv del Estal", "Nice", "Frigo 16 · Le 109", "à partir de 5 €", False, "liv-del-estal"),
    ("2026-10-16", "Henrik Schwarz x REF Session #16", "Nice", "Frigo 16 · Le 109", "à partir de 12,49 €", False, "henrik-schwarz-x-ref-session-16"),
    ("2026-10-17", "Les Wampas", "Nice", "Théâtre Lino Ventura", "à partir de 19 €", False, "les-wampas"),
    ("2026-10-17", "Chinese Man Records", "Nice", "Frigo 16 · Le 109", "à partir de 10 €", False, "chinese-man-record"),
    ("2026-10-22", "Danyl", "Nice", "Théâtre Lino Ventura", "à partir de 19 €", False, "danyl"),
    ("2026-10-28", "Limsa + Isha", "Nice", "Théâtre Lino Ventura", "à partir de 19 €", False, "limsa-isha"),
    ("2026-11-06", "63OG by UNICA", "Nice", "Frigo 16 · Le 109", "à partir de 5 €", False, "63og-by-unicart"),
    ("2026-11-07", "UMA x REF Session #17 : Zara", "Nice", "Frigo 16 · Le 109", "à partir de 12,49 €", False, "uma-x-ref-session-17-zara"),
    ("2026-11-13", "Camille Yembe", "Nice", "Frigo 16 · Le 109", "à partir de 10 €", False, "camille-yembe"),
    ("2026-11-13", "Jetlag Gang", "Nice", "Frigo 16 · Le 109", "à partir de 10 €", False, "jetlag-gang"),
    ("2026-11-14", "Caravel", "Nice", "Frigo 16 · Le 109", "à partir de 5 €", False, "caravel"),
    ("2026-11-20", "Paul Seul", "Nice", "Frigo 16 · Le 109", "à partir de 10 €", False, "paul-seul"),
    ("2026-11-21", "Marcus Gad", "Nice", "Frigo 16 · Le 109", "à partir de 15 €", False, "marcus-gad"),
    ("2026-12-04", "Acid Pauli x REF Session #18", "Nice", "Frigo 16 · Le 109", "à partir de 12,49 €", False, "acid-pauli"),
    ("2026-12-05", "Dakeez", "Nice", "Frigo 16 · Le 109", "à partir de 15 €", False, "dakeez"),
    ("2026-12-11", "Brodinski", "Nice", "Frigo 16 · Le 109", "à partir de 15 €", False, "brodinsky"),
    ("2026-12-12", "Mungo's Hi Fi", "Nice", "Frigo 16 · Le 109", "à partir de 15 €", False, "mungos-hifi"),
    ("2027-01-08", "Ana Godefroy", "Nice", "Théâtre Lino Ventura", "à partir de 30 €", False, "ana-godefroy"),
    ("2027-02-05", "Kemmler", "Nice", "Théâtre Lino Ventura", "à partir de 19 €", False, "kemmler"),
    ("2027-02-27", "Jeanjass", "Nice", "Théâtre Lino Ventura", "à partir de 26,50 €", False, "jeanjass"),
    ("2027-05-07", "REF Festival 2027", "Nice", "Le 109", "à partir de 38 €", False, "ref-festival"),
]


@register
class Panda(Scraper):
    name = "panda"
    label = "Panda Events (Le 109 / Frigo 16 / TLV)"

    def fetch(self) -> Iterator[Event]:
        today = date.today()
        for start_s, title, town, venue, price, free, slug in SHOWS:
            start = date.fromisoformat(start_s)
            if start < today:                     # gig has passed — drop it
                continue
            yield Event(
                title=title,
                start=start,
                end=None,
                town=town,
                venue=venue or None,
                category=classify(title) or "concert",
                url=f"{_BASE}{slug}/",
                note=price,
                free=free,
                source=self.name,
            )
