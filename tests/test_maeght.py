"""Fondation Maeght parser — modelled on the live WP Grid Builder markup.

The card shapes below mirror what was verified in the real DOM: a .wpgb-card
with an event permalink, a heading, and a "DD/MM/YYYY HH:MM" string. The two
edge cases that matter: cards with no date (recurring workshops) are skipped,
and the date is day-first European.
"""
from __future__ import annotations

from niceevents.scrapers import REGISTRY
from niceevents.scrapers.maeght import Maeght

GRID = """
<div class="wpgb-grid">
  <div class="wpgb-card">
    <a href="https://www.fondation-maeght.com/vanessa-wagner-piano/">
      <img alt="Vanessa Wagner"></a>
    <h3>Vanessa Wagner (piano)</h3>
    <div class="elementor-widget-container">22/07/2026 21:00</div>
    <a href="https://www.fondation-maeght.com/vanessa-wagner-piano/">MORE INFORMATION</a>
  </div>
  <div class="wpgb-card">
    <a href="https://www.fondation-maeght.com/ellsworth-kelly-fragments/"><img></a>
    <h3>Ellsworth Kelly: Fragments</h3>
    <div class="elementor-widget-container">29/06/2026 17:00</div>
  </div>
  <div class="wpgb-card">
    <a href="https://www.fondation-maeght.com/mosaic-workshop-for-children-3/"><img></a>
    <h3>Mosaic workshop for children (Wednesday)</h3>
    <a href="https://www.fondation-maeght.com/mosaic-workshop-for-children-3/">MORE INFORMATION</a>
  </div>
</div>"""


def _parse(html):
    return list(Maeght.__new__(Maeght)._parse(html))


def test_registered():
    assert "maeght" in REGISTRY


def test_parses_dated_events_skips_undated():
    evs = _parse(GRID)
    # 2 dated events; the workshop with no date is skipped
    assert len(evs) == 2
    titles = {e.title for e in evs}
    assert "Vanessa Wagner (piano)" in titles
    assert "Ellsworth Kelly: Fragments" in titles
    assert all("workshop" not in e.title.lower() for e in evs)


def test_date_is_day_first_and_time_parsed():
    ev = next(e for e in _parse(GRID) if e.title.startswith("Vanessa"))
    assert ev.start.isoformat() == "2026-07-22"     # 22/07, not 07/22
    assert ev.time == "21:00"
    assert ev.town == "Saint-Paul-de-Vence"
    assert ev.venue == "Fondation Maeght"
    assert ev.source == "maeght"
    assert ev.url.endswith("/vanessa-wagner-piano/")


def test_empty_page_yields_nothing():
    assert _parse("<div></div>") == []
