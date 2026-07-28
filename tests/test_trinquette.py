"""La Trinquette homepage parsing.

We can't reach the live club site from the test sandbox, so this exercises the
parser against markup shaped like Nicepage's export: a date heading, the act
name, and a Billetweb reservation link per night.
"""
from __future__ import annotations

import datetime

from niceevents.scrapers.trinquette import Trinquette

# Shaped like the real Nicepage export: the club prints the hour on its OWN
# line, above the act name — the parser must read it as the time, never the
# title. A future year so nothing is dropped as past regardless of when tests run.
_HOME = """
<html><body>
<nav><a href="/">ACCUEIL</a><a href="/AGENDA">AGENDA</a></nav>

<div class="u-container">
  <h4>JEUDI 30 JUILLET 2099</h4>
  <h2>21H</h2>
  <h3>Carlos G. Lopes</h3>
  <a href="https://www.billetweb.fr/carlos-g-lopes3">JE RESERVE !</a>
</div>

<div class="u-container">
  <h4>DIMANCHE 2 AOÛT 2099</h4>
  <h2>20H</h2>
  <h3>Luca Fenoli &amp; Thomas Delor Trio</h3>
  <a href="https://www.billetweb.fr/luca-fenoli-thomas-delor-trio">JE RESERVE !</a>
</div>

<div class="u-container">
  <h4>VENDREDI 14 AOÛT 2099</h4>
  <h2>21H</h2>
  <h3>NINA PAPA QUARTET</h3>
  <a href="https://www.billetweb.fr/nina-papa-quartet-aout-2099">JE RESERVE !</a>
</div>

<div class="u-container">
  <h4>SAMEDI 1 AOÛT 2099</h4>
  <h2>21H</h2>
  <h3>Simon Chivallon Trio</h3>
  <!-- no ticket link this week -->
</div>

<footer>ENTRÉE 18€ · TARIF RÉDUIT 12€ · CONCERTS À 21H</footer>
</body></html>
"""


def _events(html):
    return list(Trinquette()._parse(html))


def test_parses_each_night():
    evs = {e.title: e for e in _events(_HOME)}
    assert "Carlos G. Lopes" in evs
    assert "NINA PAPA QUARTET" in evs
    assert "Simon Chivallon Trio" in evs
    assert len(evs) == 4


def test_time_line_is_never_the_title():
    # The "21H" / "20H" line is the start time, not an act. No event may be
    # titled after it. (This is the exact bug the first version shipped.)
    titles = [e.title for e in _events(_HOME)]
    assert not any(t.strip().rstrip("Hh").isdigit() for t in titles)
    assert "21H" not in titles and "20H" not in titles


def test_dates_times_and_sunday_default():
    evs = {e.title: e for e in _events(_HOME)}
    assert evs["Carlos G. Lopes"].start == datetime.date(2099, 7, 30)
    assert evs["Carlos G. Lopes"].time == "21:00"
    # Sunday night: printed 20H and it is a Sunday.
    assert evs["Luca Fenoli & Thomas Delor Trio"].start == datetime.date(2099, 8, 2)
    assert evs["Luca Fenoli & Thomas Delor Trio"].time == "20:00"


def test_ticket_link_matched_by_slug():
    evs = {e.title: e for e in _events(_HOME)}
    assert evs["NINA PAPA QUARTET"].url == "https://www.billetweb.fr/nina-papa-quartet-aout-2099"
    # No ticket link -> falls back to the club homepage, never a wrong act's link.
    assert evs["Simon Chivallon Trio"].url == "https://www.trinquettejazzclub.com/"


def test_venue_price_free_flag():
    e = _events(_HOME)[0]
    assert e.town == "Villefranche-sur-Mer"
    assert e.venue == "La Trinquette Jazz Club"
    assert e.free is False
    assert "18€/12€" in (e.note or "")
    assert e.category == "concert"
