"""anthéa Antibes: one card is many nights, and the year comes from the heading.

The fixture uses the real class names and the real date strings from
anthea-antibes.fr/fr/calendrier, including the three shapes that break a naive
parser: "1er" for the 1st, a gap mid-run, and one card listing three months.
"""
from __future__ import annotations

from datetime import date

from niceevents.scrapers.anthea import Anthea, parse_dates

BASE = "https://www.anthea-antibes.fr/fr/spectacles/saison-2026-2027"


def _section(year: str, month: str, cards: list[tuple[str, str, str]]) -> str:
    items = "".join(
        f'<li class="card card--1">'
        f'<a href="{BASE}/{section}/{title.lower()}" class="card__link">'
        f'<div class="card__spectacle_information">'
        f'<h3 class="card__spectacle_title">{title}</h3>'
        f'<p class="card__description">Une description</p>'
        f'<p class="card__dates"> {dates} </p>'
        f"</div></a></li>"
        for title, dates, section in cards
    )
    return (
        '<section class="spectacles__section"><h2 class="spectacles__title">'
        '<div class="spectacles__main_title">'
        f'<span class="enveloppe__number">{year}</span>'
        f'<span class="enveloppedate__title">{month}</span>'
        "</div></h2>"
        f'<ul class="spectacles__list cards">{items}</ul></section>'
    )


PAGE = (
    '<html><body><div class="spectacles__panel spectacles__panel--mois">'
    + _section("2026", "septembre", [
        ("Laponie", "10, 11 et 12 septembre", "privilege-theatre"),
        ("Pierre Richard", "29 septembre", "tout-le-spectacle-vivant"),
    ])
    + _section("2026", "decembre", [
        ("Le Fantome", "1er, 2 et 3 décembre", "tout-le-theatre"),
        ("Casse Noisette", "8, 9, 11 et 12 décembre", "l-incontournable"),
    ])
    + _section("2027", "avril", [
        ("Tournee", "3 et 17 avril. 22 mai. 12 juin", "tout-le-theatre"),
    ])
    + "</div></body></html>"
)


def _events():
    return list(Anthea()._parse(PAGE))


# ----------------------------------------------------------------- date line

def test_run_of_nights_becomes_one_date_each():
    assert parse_dates("10, 11 et 12 septembre", 2026) == [
        date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12)]


def test_premier_is_the_first():
    assert parse_dates("1er, 2 et 3 décembre", 2026) == [
        date(2026, 12, 1), date(2026, 12, 2), date(2026, 12, 3)]


def test_gap_in_a_run_is_kept():
    # 10 December is a dark night: it must NOT be filled in.
    assert parse_dates("8, 9, 11 et 12 décembre", 2026) == [
        date(2026, 12, 8), date(2026, 12, 9), date(2026, 12, 11), date(2026, 12, 12)]


def test_days_bind_to_the_month_that_follows_them():
    # The shape that collapses onto one month if you parse a single month name.
    assert parse_dates("3 et 17 avril. 22 mai. 12 juin", 2027) == [
        date(2027, 4, 3), date(2027, 4, 17), date(2027, 5, 22), date(2027, 6, 12)]


def test_run_across_two_months():
    # Real shape from the live page: "En attendant Bojangles".
    assert parse_dates("30 et 31 mars. 1er, 2 et 3 avril", 2027) == [
        date(2027, 3, 30), date(2027, 3, 31),
        date(2027, 4, 1), date(2027, 4, 2), date(2027, 4, 3)]


def test_run_across_new_year_rolls_the_year_forward():
    # Under a "décembre 2026" heading, the January nights are 2027.
    assert parse_dates("30 et 31 décembre. 2 janvier", 2026) == [
        date(2026, 12, 30), date(2026, 12, 31), date(2027, 1, 2)]


def test_du_x_au_y_range_expands():
    assert parse_dates("du 10 au 13 octobre", 2026) == [
        date(2026, 10, 10), date(2026, 10, 11), date(2026, 10, 12), date(2026, 10, 13)]


# ---------------------------------------------------------------------- page

def test_year_comes_from_the_month_heading():
    # A season straddles New Year: the card text never says which year it is.
    evs = {e.title: [x.start for x in _events() if x.title == e.title] for e in _events()}
    assert evs["Laponie"][0].year == 2026
    assert evs["Tournee"][0].year == 2027


def test_one_card_yields_one_event_per_night():
    evs = [e for e in _events() if e.title == "Laponie"]
    assert [e.start for e in evs] == [
        date(2026, 9, 10), date(2026, 9, 11), date(2026, 9, 12)]


def test_venue_town_and_category():
    e = next(e for e in _events() if e.title == "Pierre Richard")
    assert e.town == "Antibes"
    assert "anth" in (e.venue or "").lower()
    assert e.category == "scene"
    assert e.source == "anthea"


def test_unknown_section_still_lands_on_stage_not_other():
    e = next(e for e in _events() if e.title == "Casse Noisette")
    assert e.category == "scene"


def test_no_invented_start_time():
    # Times live on each show's own page, not the calendar. Never guess one.
    assert all(e.time is None for e in _events())


def test_total_performances():
    assert len(_events()) == 3 + 1 + 3 + 4 + 4
