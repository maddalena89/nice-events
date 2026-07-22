"""Curated seed — hand-verified events no automated scraper reliably reaches.

The daily scrapers cover Nice and the métropole well, but the surrounding coast
and hinterland — Menton, Monaco, Beaulieu, Villefranche, Cagnes, Saint-Paul-de-
Vence, Èze — have their museum shows and festivals scattered across venue sites
we don't each scrape. This is the hand-checked list that fills that gap so those
exhibitions never silently vanish.

It yields plain Event objects like any other source, so it gets the same dedup,
merge and display. Anything here that a scraper ALSO finds simply collapses on
the shared fingerprint — no double listing. Past-dated entries are dropped at
build time, so a stale line here is harmless; refresh the exhibitions each season.
"""
from __future__ import annotations

from datetime import date
from typing import Iterator, Optional

from ..models import Event
from .base import Scraper, register

#: (start, end, title, town, venue, category, note, url, free)
#: end="" for single-day; venue="" when unknown.
SEED: list[tuple] = [
    # ---- festivals / concerts / seasonal ----
    ("2026-06-26", "2026-09-11", "Jazz at the Château", "Cagnes-sur-Mer", "Château-Musée Grimaldi", "concert", "Jazz & blues · recurring dates", "https://www.explorenicecotedazur.com/en/event/jazz-at-the-chateau/", False),
    ("2026-02-21", "2026-11-29", "Concerts at the Trinquette Jazz Club", "Villefranche-sur-Mer", "La Trinquette", "concert", "Jazz & blues · recurring", "https://www.explorenicecotedazur.com/en/event/concerts-at-the-trinquette-jazz-club/", False),
    ("2026-09-12", "2026-09-19", "Beaulieu Classic Festival", "Beaulieu-sur-Mer", "Petite Afrique, Casino, Église St Michael, Hôtel Royal Riviera", "concert", "8 days of classical music · opening 12 Sept: Nice Opera Chorus", "https://www.explorenicecotedazur.com/en/event/beaulieu-classic-festival-2026/", False),
    # Belaprem lives in its own module now (per-night line-up), so no umbrella here.
    ("2026-09-18", "2026-09-20", "LEC Summer Finals 2026", "Nice", "Palais Nikaïa", "autre", "League of Legends esports finals", "https://www.nikaia.fr/programmation/lec-summer-finals-2026", False),
    ("2026-09-25", "", "La Légende de Monte-Cristo, le Musical", "Nice", "Palais Nikaïa", "scene", "20h · musical", "https://www.nikaia.fr/programmation/la-legende-de-monte-cristo-le-musical", False),
    ("2026-07-25", "2026-07-26", "Fête du Cheval", "Levens", "", "autre", "Horse festival · village fête", "https://www.explorenicecotedazur.com/en/event/horse-festival/", False),
    ("2026-07-06", "2026-08-22", "Summer Nights at the Hippodrome", "Cagnes-sur-Mer", "Hippodrome de la Côte d'Azur", "autre", "Evening race meetings", "https://www.explorenicecotedazur.com/en/event/summer-nights-at-the-hippodrome-summer-horse-meeting/", False),
    ("2026-06-19", "2026-09-11", "Étoiles grandeur nature", "Vence", "", "autre", "Astronomy observation evenings", "https://www.explorenicecotedazur.com/en/event/etoiles-grandeur-nature/", False),
    # Les Contes d'apéro is on nice.fr (TNN) already — the scraper covers it per night.

    # ---- exhibitions: Nice ----
    ("2026-06-17", "2026-09-28", "Henri Matisse – Yves Saint Laurent. Le beau, la mode et le bonheur", "Nice", "Musée Matisse", "expo", "Major summer show · fashion & Matisse", "https://www.explorenicecotedazur.com/en/event/henri-matisse-yves-saint-laurent-le-beau-la-mode-et-le-bonheur/", False),
    ("2026-05-02", "2026-09-21", "Chagall à l'œuvre — un prêt d'exception", "Nice", "Musée Marc Chagall", "expo", "", "https://www.explorenicecotedazur.com/en/event/chagall-a-loeuvre-un-pret-dexception-au-musee/", False),
    ("2026-02-13", "2027-01-11", "Merveilles et curiosités du Palais Lascaris", "Nice", "Palais Lascaris", "expo", "", "https://www.explorenicecotedazur.com/en/event/merveilles-et-curiosites-du-palais-lascaris/", False),
    ("2026-06-27", "2027-01-18", "Coun — Libera l'Art", "Nice", "Palais Lascaris", "expo", "Contemporary intervention in the baroque palace", "https://www.explorenicecotedazur.com/en/event/coun-libera-lart-au-palais-lascaris/", False),
    ("2026-09-24", "2026-12-11", "Niki de Saint Phalle. Vive l'Amour #6", "Nice", "MAMAC nomade · Cité mixte du Parc Impérial", "expo", "MAMAC off-site (museum closed for renovation)", "https://www.mamac-nice.org/exposition/niki-de-saint-phalle-vive-lamour-6/", False),
    ("2026-11-13", "2026-11-29", "OVNi — La biennale de l'image en mouvement", "Nice", "Galleries, museums & hotels", "expo", "Video-art biennial", "https://www.explorenicecotedazur.com/en/event/ovni-la-biennale-de-limage-en-mouvement/", False),

    # ---- exhibitions: Fondation Maeght (Saint-Paul-de-Vence) ----
    ("2026-06-27", "2026-11-15", "Ellsworth Kelly — At the Edge of Water", "Saint-Paul-de-Vence", "Fondation Maeght", "expo", "Major show · water in Kelly's work · curator Éric de Chassey", "https://www.fondation-maeght.com/ellsworth-kelly-at-the-edge-of-water/", False),
    ("2026-05-14", "2026-11-08", "Peter Knapp — The Era of Courrèges", "Saint-Paul-de-Vence", "Fondation Maeght · Galerie Anny Courtade", "expo", "Art & fashion · 1965 Courrèges photographs", "https://www.fondation-maeght.com/peter-knapp-the-era-of-courreges/", False),

    # ---- exhibitions: Menton & Monaco ----
    ("2026-07-04", "2026-11-16", "Jean Cocteau — Le château de la Bête", "Menton", "Musée Jean Cocteau – Le Bastion", "expo", "80 years of « La Belle et la Bête »", "https://www.museecocteaumenton.fr/Nouvelle-exposition-du-04-07-au-16-11-2026-272.html", False),
    ("2026-07-01", "2026-09-06", "Monaco et l'Automobile, de 1893 à nos jours", "Monaco", "Grimaldi Forum", "expo", "130+ years of motoring · ~50 cars", "https://www.grimaldiforum.com/en/events-schedule-monaco/monaco-and-the-automobile-from-1893-to-nowadays", False),
    ("2026-07-03", "2027-01-03", "Victor Brauner — The Magical Adventure", "Monaco", "Nouveau Musée National de Monaco · Villa Paloma", "expo", "", "https://www.visitmonaco.com/en/events/monaco-s-major-events/grimaldi-forum-monaco-summer-exhibition", False),

    # ---- exhibitions: the coast ----
    ("2026-06-12", "2026-09-20", "Temporary exhibition at Villa Kérylos", "Beaulieu-sur-Mer", "Villa Kérylos", "expo", "Contemporary art", "https://www.explorenicecotedazur.com/en/event/temporary-exhibition-at-villa-kerylos/", False),
    ("2026-07-01", "2026-07-30", "Sabine Vandenbulcke — The Studio by the Sea", "Beaulieu-sur-Mer", "", "expo", "", "https://www.explorenicecotedazur.com/en/event/exhibition-by-sabine-vandenbulcke-the-studio-by-the-sea/", False),
    ("2026-07-02", "2026-10-31", "L'Absurde et Le Rêve — summer exhibition", "Villefranche-sur-Mer", "", "expo", "Modern / contemporary art", "https://www.explorenicecotedazur.com/en/event/labsurde-et-le-reve-summer-exhibition/", False),
    ("2026-07-03", "2026-09-03", "La vie en rose", "Villefranche-sur-Mer", "Hôtel Provençal", "expo", "Contemporary art", "https://www.explorenicecotedazur.com/en/event/la-vie-en-rose-exhibition-at-the-hotel-provencal/", False),
    ("2026-07-03", "2027-01-04", "80th Anniversary of the Grimaldi Castle Museum", "Cagnes-sur-Mer", "Château-Musée Grimaldi", "expo", "", "https://www.explorenicecotedazur.com/en/event/exhibition-the-80th-anniversary-of-the-grimaldi-castle-museum/", False),
    ("2026-06-04", "2026-09-20", "Destination Bijou", "Cagnes-sur-Mer", "", "expo", "Jewellery / design", "https://www.explorenicecotedazur.com/en/event/destination-bijou-cagnes/", False),
    ("2026-05-13", "2026-09-04", "Il cuore della terra — Cesare Catania", "Saint-Jean-Cap-Ferrat", "", "expo", "Contemporary art", "https://www.explorenicecotedazur.com/en/event/il-cuore-della-terra-exhibition-by-cesare-catania/", False),
    ("2026-06-12", "2026-10-11", "Cerises aux cœurs — Jean-Louis Landraud", "Saint-Jean-Cap-Ferrat", "Open-air sculpture trail", "expo", "Sculpture", "https://www.explorenicecotedazur.com/en/event/cerises-aux-coeurs-open-air-sculpture-exhibition-by-jean-louis-landraud/", False),
    ("2026-04-01", "2026-08-30", "Ramiro Arrue", "Cap-d'Ail", "", "expo", "Visual / graphic arts", "https://www.explorenicecotedazur.com/en/event/ramiro-arrue-exhibition/", False),

    # ---- exhibitions: Èze & hinterland ----
    ("2026-07-12", "2026-07-30", "Exposition F. Suzanne 2026", "Èze", "", "expo", "Visual / graphic arts", "https://www.explorenicecotedazur.com/en/event/exposition-f-suzanne-2026/", False),
    ("2026-08-15", "2026-08-31", "Exposition Maja Kerin", "Èze", "", "expo", "Photography", "https://www.explorenicecotedazur.com/en/event/exposition-maja-kerin-aout-2026/", False),
    ("2026-09-02", "2026-09-14", "Exposition Corinne Canta", "Èze", "", "expo", "Visual / graphic arts", "https://www.explorenicecotedazur.com/en/event/exposition-corinne-canta-2026/", False),
    ("2026-08-01", "2026-12-18", "Expositions AMSL Aquarelle & « Levens d'un temp è de deman »", "Levens", "", "expo", "Watercolour & local heritage", "https://www.explorenicecotedazur.com/en/event/expositions-de-lamsl-aquarelle-et-de-lassociation-levens-dun-temp-e-de-deman/", False),
    ("2026-07-09", "2026-11-01", "Mémoires de l'eau", "Vence", "", "expo", "", "https://www.explorenicecotedazur.com/en/event/exposition-memoires-de-leau/", False),
    ("2026-07-04", "2026-08-29", "Escales littorales", "Saint-Martin-Vésubie", "", "expo", "", "https://www.explorenicecotedazur.com/en/event/exhibition-escales-littorales/", False),

    # ---- spotted in the wild: Le Bistrot Poète (Nice) ----
    # From posters on the door, 34 rue Tonduti de l'Escarène, 06000 Nice (@bistrotpoete).
    # The 17 Jul finissage of "Iel & Mer" (Mary Joly & Denis Gibelin) is already
    # past, so it's not listed — seed drops past-dated entries at build time anyway.
    # NB: the poster spells the artist "Jasmine"; the monthly flyer wrote "Y'asmine".
    ("2026-07-23", "2026-09-07", "Exposition Jasmine", "Nice", "Le Bistrot Poète · 34 rue Tonduti de l'Escarène", "expo", "Vernissage jeu. 23 juil. à partir de 18h · visible jusqu'au 7 septembre", "https://www.instagram.com/bistrotpoete/", True),
    ("2026-07-23", "", "Vernissage de l'artiste Jasmine", "Nice", "Le Bistrot Poète · 34 rue Tonduti de l'Escarène", "expo", "À partir de 18h · expo visible jusqu'au 7 septembre", "https://www.instagram.com/bistrotpoete/", True),
]


@register
class Seed(Scraper):
    name = "seed"
    label = "Curated (coast & hinterland)"

    def fetch(self) -> Iterator[Event]:
        today = date.today()
        for start_s, end_s, title, town, venue, cat, note, url, free in SEED:
            start = date.fromisoformat(start_s)
            end = date.fromisoformat(end_s) if end_s else None
            if (end or start) < today:               # season passed — drop it
                continue
            yield Event(
                title=title,
                start=start,
                end=end,
                town=town,
                venue=venue or None,
                category=cat,
                url=url,
                note=note or None,
                free=free,
                source=self.name,
            )
