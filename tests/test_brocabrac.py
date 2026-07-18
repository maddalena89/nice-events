"""Brocabrac parsing — the JSON-leak bug and its neighbours.

The live site showed a vide-grenier whose venue field was raw JSON-LD:
    "07-18\\",\\"url\\":\\"https://brocabrac.fr/...\\",\\"startDate\\":...
because each card embeds a <script type="application/ld+json"> and node.text()
concatenated the script body with the visible text. These tests pin the fix.
"""
from __future__ import annotations

from niceevents.scrapers.brocabrac import Brocabrac, _clean_venue

CARD_WITH_JSONLD = """
<div>
  <h2>Samedi</h2><h2>18 Juillet 2026</h2>
  <li>
    <script type="application/ld+json">
    {"@type":"Event","url":"https://brocabrac.fr/06/consegudes/1318308-vide-grenier",
     "startDate":"2026-07-18","endDate":"2026-07-18",
     "location":{"@type":"Place","name":"place du village",
     "address":{"postalCode":"06510"}},"image":["large.jpg"]}
    </script>
    <h3><a href="/06/consegudes/1318308-vide-grenier">Conségudes Vide-Grenier</a></h3>
    06510 - Vide-Grenier - place du village
  </li>
</div>"""


def _parse(html):
    return list(Brocabrac.__new__(Brocabrac)._parse(html))


def test_json_ld_never_leaks_into_venue_or_note():
    (ev,) = _parse(CARD_WITH_JSONLD)
    for field in (ev.venue or "", ev.note or ""):
        assert "{" not in field
        assert "http" not in field
        assert "startDate" not in field
        assert "schema.org" not in field
    assert ev.venue == "place du village"


def test_hyphenated_type_is_not_split_into_the_venue():
    """'Vide-Grenier' must stay whole. The separator is a spaced ' - ', so the
    hyphen inside the type name is not a boundary."""
    (ev,) = _parse(CARD_WITH_JSONLD)
    assert ev.venue == "place du village"          # not "Grenier - place du village"
    assert "Grenier" not in (ev.venue or "")


def test_town_is_stripped_from_title_despite_the_accent():
    """Slug 'consegudes' vs title 'Conségudes' — the fold must ignore accents,
    or the town ends up doubled in the title."""
    (ev,) = _parse(CARD_WITH_JSONLD)
    assert not ev.title.lower().startswith("conségudes")


def test_clean_venue_rejects_json_shaped_strings():
    assert _clean_venue('07-18","url":"https://...') is None
    assert _clean_venue("x" * 200) is None
    assert _clean_venue("Place Garibaldi") == "Place Garibaldi"
    assert _clean_venue(None) is None


def test_plain_card_still_parses():
    html = """
    <div><h2>18 Juillet 2026</h2>
      <li><h3><a href="/06/nice/1025571-brocante-garibaldi">Nice Brocante Garibaldi</a></h3>
          06300 - Brocante - Place Garibaldi</li>
    </div>"""
    (ev,) = _parse(html)
    assert ev.venue == "Place Garibaldi"
    assert ev.start.isoformat() == "2026-07-18"
