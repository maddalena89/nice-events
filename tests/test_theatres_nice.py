"""Théâtres de Nice portal parser — real card markup, both date shapes."""
from __future__ import annotations

from niceevents.scrapers import REGISTRY
from niceevents.scrapers.theatres_nice import _parse, _genre_category

# Trimmed from the live page: a dated run, a one-off, a concert, and an
# image-only link that must be ignored.
PAGE = """
<a href="/evenement/guignol-et-le-grenier-des-merveilles">
  <div class="image-container">
    <img class="img-responsive" src="x.png" alt="Guignol et le grenier des merveilles">
  </div>
  <div class="info-container">
    <p class="lieu"><i class="ipicto marker"></i> Alphabet (Théâtre l')</p>
    <p class="genre"><i class="ipicto theatre"></i> Marionnettes</p>
    <h2>Guignol et le grenier des me…</h2>
    <p class="date"><i class="ipicto date"></i> Du 20/07/2026 au 22/08/2026</p>
  </div>
</a>
<a href="/evenement/the-jazz-room">
  <div class="image-container"><img src="y.jpg" alt="The Jazz Room"></div>
  <div class="info-container">
    <p class="lieu"><i class="ipicto marker"></i> Cité (Théâtre de la)</p>
    <p class="genre"><i class="ipicto music"></i> Concert Jazz</p>
    <h2>The Jazz Room</h2>
    <p class="date"><i class="ipicto date"></i> Le 11/10/2026</p>
  </div>
</a>
<a href="/evenement/guignol-et-le-grenier-des-merveilles"><img src="dup.png" alt="dup"></a>
"""


def test_registered():
    assert "theatres_nice" in REGISTRY


def test_parses_run_and_single_and_dedups():
    evs = list(_parse(PAGE))
    assert len(evs) == 2                          # the image-only duplicate is skipped

    run = evs[0]
    assert run.title == "Guignol et le grenier des merveilles"   # full title from alt
    assert run.start.isoformat() == "2026-07-20"
    assert run.end.isoformat() == "2026-08-22"    # "Du … au …" keeps the end
    assert run.town == "Nice"
    assert run.venue == "Alphabet (Théâtre l')"
    assert run.category == "scene"
    assert run.url == "https://theatres.nice.fr/evenement/guignol-et-le-grenier-des-merveilles"

    jazz = evs[1]
    assert jazz.start.isoformat() == "2026-10-11" and jazz.end is None
    assert jazz.category == "concert"             # jazz -> concert, not stage


def test_genre_mapping():
    assert _genre_category("Humour/One-(wo)man show") == "scene"
    assert _genre_category("Danse Hip-Hop") == "danse"
    assert _genre_category("Concert") == "concert"
    assert _genre_category("Théâtre musical") == "scene"
