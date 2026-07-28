"""Département 06 agenda card parsing."""
from __future__ import annotations

import datetime

from selectolax.parser import HTMLParser

from niceevents.scrapers.departement06 import Departement06

_CARD = """
<div class="event-item__wrap"><div class="event-item__content"><h3 class="item-title event-item__title">
<span class="event-focus__category-link">
<a href="/agenda?categories=1" class="event-item__category">Les Soirées Estivales, </a>
<a href="/agenda?categories=2" class="event-item__category">Concerts, </a>
<a href="/agenda?categories=3" class="event-item__category">Accessible PMR</a>
</span>
<a href="/agenda/reverence-sanson-1" class="event-item__title-link"><span class="underline">Révérence Sanson</span></a></h3>
<div class="time-place event-item__time-place"><p class="time-place__item is-place ">
<span class="ghost">Lieu :</span> Gattières</p></div></div>
<div class="date event-item__date"><p class="date__wrap"> <span class="ghost">Le</span>
<time class="date__time" datetime="2026-07-29"><span>29</span></time>
<time class="date__hour" datetime="21:00">21h00</time></p></div></div>
"""

_RANGE_CARD = """
<div class="event-item__wrap"><div class="event-item__content"><h3 class="event-item__title">
<a href="/agenda?categories=9" class="event-item__category">Culture</a>
<a href="/agenda/expo-x" class="event-item__title-link"><span>Expo X</span></a></h3>
<div class="time-place"><p class="time-place__item is-place "><span class="ghost">Lieu :</span> Nice</p></div></div>
<div class="event-item__date"><p><span class="ghost">Du</span>
<time class="date__time" datetime="2026-07-01"><span>01</span></time>
<time class="date__time" datetime="2026-08-30"><span>30</span></time></p></div></div>
"""


def _parse(html):
    s = Departement06()
    card = HTMLParser(html).css_first(".event-item__wrap")
    return s._event_from(card, datetime.date(2026, 7, 1))


def test_soiree_estivale_card():
    e = _parse(_CARD)
    assert e.title == "Révérence Sanson"
    assert e.start == datetime.date(2026, 7, 29)
    assert e.end is None
    assert e.time == "21:00"
    assert e.town == "Gattières"
    assert e.category == "concert"
    assert e.free is True                      # Soirées Estivales are free
    assert "Soirées Estivales" in (e.note or "")
    assert e.url == "https://www.departement06.fr/agenda/reverence-sanson-1"


def test_date_range_card():
    e = _parse(_RANGE_CARD)
    assert e.start == datetime.date(2026, 7, 1)
    assert e.end == datetime.date(2026, 8, 30)


def test_past_event_dropped():
    s = Departement06()
    card = HTMLParser(_CARD).css_first(".event-item__wrap")
    assert s._event_from(card, datetime.date(2027, 1, 1)) is None
