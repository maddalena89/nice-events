"""One event, more than one category.

"Visites guidées de la bibliothèque et de l'exposition Michel Butor" is a guided
visit AND an exhibition. With one category per event it was hidden from whoever
browsed the other chip, and overrides.py was pinning events to "the tab the
right crowd looks at" to work around the limit. Each event now keeps one primary
category and gains the others its title clearly signals.
"""
from datetime import date, timedelta

from niceevents import landing
from niceevents.models import extra_categories


def test_the_reported_examples_get_both_categories():
    assert extra_categories(
        "Visites guidées de la bibliothèque et de l'exposition Michel Butor",
        "visite") == ["expo"]
    assert extra_categories(
        "Exposition et visite de la Maison Francine Gag", "expo") == ["visite"]


def test_the_primary_is_never_repeated_or_replaced():
    extra = extra_categories("Exposition et visite", "expo")
    assert "expo" not in extra


def test_a_plain_title_gets_nothing_extra():
    assert extra_categories("Concert jazz", "concert") == []


def test_parcours_is_not_a_class():
    """"cours" matched the end of "Parcours", so an exhibition was a workshop."""
    assert "atelier" not in extra_categories("Exposition Fragments d'un Parcours", "expo")
    assert "atelier" in extra_categories("Cours de salsa", "danse")


def test_brocante_folds_into_the_same_chip():
    """brocante is stored separately but shares the Brocantes & fêtes chip, so it
    must never appear as a second, separate category next to it."""
    assert extra_categories("Vide-grenier et fête du village", "marche") == []


def _ev(i, tags, days=1):
    start = date.today() + timedelta(days=days)
    return {"title": f"E{i}", "start": start.isoformat(), "town": "Nice",
            "category": tags[0], "tags": tags, "slug": f"e{i}",
            "online": False, "time": "20:00", "note": "", "free": False}


def test_an_event_is_listed_on_every_category_page_it_belongs_to():
    evs = [_ev(1, ["visite", "expo"])] + [_ev(i, ["concert"]) for i in range(2, 8)]
    _, cats = landing.collect(evs)
    by = {p["key"]: [e["title"] for e in p["events"]] for p in cats}
    assert "E1" in by["visite"]
    assert "E1" in by["expo"], "a guided visit of an exhibition must be on /exhibitions/ too"
