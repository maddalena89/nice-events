"""Théâtres de Nice portal parser — real card markup, both date shapes."""
from __future__ import annotations

from niceevents.scrapers import REGISTRY
from niceevents.scrapers.theatres_nice import (
    _genre_category,
    _jeune_public_hrefs,
    _parse,
)

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

# Two Alphabet cards with the SAME genre, one for children and one not. This is
# the real pair that proves genre can't decide it: both are "Comédie".
ALPHABET_PAGE = """
<a href="/evenement/cest-pas-juste">
  <div class="image-container"><img src="a.jpg" alt="C'est pas juste"></div>
  <div class="info-container">
    <p class="lieu"><i class="ipicto marker"></i> Alphabet (Théâtre l')</p>
    <p class="genre"><i class="ipicto theatre"></i> Comédie / Café-théâtre / Boulevard</p>
    <h2>C'est pas juste</h2>
    <p class="date"><i class="ipicto date"></i> Le 25/08/2026</p>
  </div>
</a>
<a href="/evenement/reveillon-a-la-morgue">
  <div class="image-container"><img src="b.jpg" alt="Réveillon à la morgue"></div>
  <div class="info-container">
    <p class="lieu"><i class="ipicto marker"></i> Alphabet (Théâtre l')</p>
    <p class="genre"><i class="ipicto theatre"></i> Comédie / Café-théâtre / Boulevard</p>
    <h2>Réveillon à la morgue</h2>
    <p class="date"><i class="ipicto date"></i> Le 30/07/2026</p>
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
"""

# A /recherche?lieu=7&cible=1 result page: same card markup, plus a trailing
# slash and a query string to prove the href is normalised before comparison.
SEARCH_PAGE = """
<a href="/evenement/cest-pas-juste/?page=1">
  <div class="info-container">
    <p class="lieu"><i class="ipicto marker"></i> Alphabet (Théâtre l')</p>
    <p class="genre"><i class="ipicto theatre"></i> Comédie / Café-théâtre / Boulevard</p>
    <h2>C'est pas juste</h2>
  </div>
</a>
<a href="/evenement/cest-pas-juste"><img src="dup.png" alt="dup"></a>
"""


def test_registered():
    assert "theatres_nice" in REGISTRY


def test_parses_run_and_single_and_dedups():
    evs = list(_parse(PAGE, set()))                # nothing flagged jeune public
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


def test_search_page_hrefs_are_normalised():
    # Query string and trailing slash stripped, image-only duplicate ignored.
    assert _jeune_public_hrefs(SEARCH_PAGE) == {"/evenement/cest-pas-juste"}


def test_drops_only_the_flagged_alphabet_show():
    evs = list(_parse(ALPHABET_PAGE, {"/evenement/cest-pas-juste"}))
    titles = [e.title for e in evs]
    assert "C'est pas juste" not in titles         # jeune public, gone
    assert "Réveillon à la morgue" in titles       # same genre, adult, kept
    assert "The Jazz Room" in titles               # other venue, untouched


def test_empty_set_keeps_every_alphabet_show():
    # No children's show on right now is a real state, not a failure.
    evs = list(_parse(ALPHABET_PAGE, set()))
    assert len(evs) == 3


def test_unknown_audience_drops_the_whole_venue():
    # None means "could not read the audience list". Fail closed on the Alphabet
    # only — every other venue still comes through.
    evs = list(_parse(ALPHABET_PAGE, None))
    assert [e.title for e in evs] == ["The Jazz Room"]


def test_flagged_href_at_another_venue_is_ignored():
    # The venue check is what stops a stale or renumbered lieu id from silently
    # deleting a different theatre's programme.
    evs = list(_parse(ALPHABET_PAGE, {"/evenement/the-jazz-room"}))
    assert "The Jazz Room" in [e.title for e in evs]
