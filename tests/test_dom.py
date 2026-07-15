"""Regression tests for the document-order bug.

This bug produced *confident wrong data* rather than an error: brocabrac
reported 64 brocantes all stamped with the last date on the page, and tango
collapsed ~50 milongas onto one day. Pin it.
"""
from selectolax.parser import HTMLParser

from niceevents.dom import cards_containing, in_order
from niceevents.scrapers.brocabrac import Brocabrac
from niceevents.scrapers.tango import TangoArgentin


def test_css_comma_selector_is_not_document_order():
    """The upstream behaviour we're working around. If selectolax ever fixes
    this, this test fails and dom.py can be simplified."""
    html = "<div><h6>A</h6><tr>1</tr><h6>B</h6><tr>2</tr></div>"
    tags = [n.tag for n in HTMLParser(html).css("h6, tr")]
    assert tags == ["h6", "h6"] or tags[:2] == ["h6", "h6"], (
        "selectolax now returns document order — dom.in_order may be redundant")


def test_in_order_is_document_order():
    html = "<div><h6>A</h6><p>1</p><h6>B</h6><p>2</p></div>"
    got = [(n.tag, n.text()) for n in in_order(HTMLParser(html), {"h6", "p"})]
    assert got == [("h6", "A"), ("p", "1"), ("h6", "B"), ("p", "2")]


def test_brocabrac_dates_track_their_heading():
    """Each brocante must get the date of the heading ABOVE it, not the last."""
    html = """
    <div>
      <h2>Samedi</h2><h2>18 Juillet 2026</h2>
      <li><h3><a href="/06/nice/1025571-brocante-garibaldi">Nice Brocante Garibaldi</a></h3>
          06300 - Brocante - Place Garibaldi</li>
      <h2>Dimanche</h2><h2>19 Juillet 2026</h2>
      <li><h3><a href="/06/sospel/1386766-vide-grenier-ete">Sospel Vide grenier</a></h3>
          06380 - Vide-Grenier - Esplanade Gianotti</li>
      <h2>Lundi</h2><h2>20 Juillet 2026</h2>
      <li><h3><a href="/06/nice/900037-brocante-cours-saleya">Nice Brocante du cours saleya</a></h3>
          06300 - Brocante - Cours Saleya</li>
    </div>"""
    got = {e.title: e.start.isoformat() for e in Brocabrac.__new__(Brocabrac)._parse(html)}
    assert got == {
        "Brocante Garibaldi": "2026-07-18",
        "Vide grenier": "2026-07-19",
        "Brocante du cours saleya": "2026-07-20",
    }, f"dates did not track their headings: {got}"


def test_tango_dates_track_their_heading():
    html = """
    <div>
      <h6>Wednesday 15 July 2026</h6>
      <table><tr><td>8:30pm</td><td>Amarras 2 rue la Bruyere 06000 Nice
        from 8:30pm to 12:00am 10 euros DJ : Pierre Gabrielli</td></tr></table>
      <h6>Thursday 16 July 2026</h6>
      <table><tr><td>7:00pm</td><td>Practica Jeudi 8 rue Gaston Charbonnier 06300 Nice
        from 7:00pm to 11:00pm 8 euros</td></tr></table>
      <h6>Sunday 19 July 2026</h6>
      <table><tr><td>9:00pm</td><td>Milonga de la Estacion 35 av Malaussena 06000 Nice
        from 9:00pm to 12:00am chapeau</td></tr></table>
    </div>"""
    evs = list(TangoArgentin.__new__(TangoArgentin)._parse(html, "nice"))
    dates = sorted(e.start.isoformat() for e in evs)
    assert dates == ["2026-07-15", "2026-07-16", "2026-07-19"], (
        f"expected 3 distinct dates, got {dates}")
    assert len({e.start for e in evs}) == 3, "milongas collapsed onto one date again"


def test_cards_containing_finds_tightest_card():
    html = """
    <ul>
      <li><div><a href="/en/event/one/">One</a> 18 July 2026 Nice</div></li>
      <li><div><a href="/en/event/two/">Two</a> 19 July 2026 Vence</div></li>
    </ul>"""
    cards = list(cards_containing(HTMLParser(html), {"li", "div"}, "a[href*='/event/']"))
    assert len(cards) == 2, f"expected 2 cards, got {len(cards)}"
    assert all(len(c.css("a[href*='/event/']")) == 1 for c in cards)


def test_selectolax_node_identity_is_meaningless():
    """Pins the trap that broke cards_containing: selectolax rebuilds Node
    wrappers per access, so `is` comparisons never match the same element."""
    t = HTMLParser("<div id='x'>hi</div>")
    a = t.css_first("div")
    b = t.css_first("div")
    assert a.html == b.html          # same element...
    assert a is not b                # ...but never the same object


def test_cards_containing_skips_oversized_wrapper():
    """A <div> wrapping the whole page must not be returned as a card."""
    big = "x" * 5000
    html = f"<div>{big}<li><a href='/en/event/one/'>One</a></li></div>"
    cards = list(cards_containing(HTMLParser(html), {"li", "div"},
                                 "a[href*='/event/']", max_text=4000))
    assert len(cards) == 1 and cards[0].tag == "li"
