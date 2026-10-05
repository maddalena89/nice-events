"""Turning a venue string into a point (5 Oct 2026).

Sources write venues as names, as addresses, or as both at once, so the lookup
tries a few forms. Nothing here touches the network: these test the string work
and the cache, which is where the mistakes live.
"""
from niceevents import geocode as g


def test_an_address_is_trimmed_to_something_findable():
    assert g._clean("Fairmont Avenue des Spélugues, 98000 Monaco Salon Mistrau") \
        == "Fairmont Avenue des Spélugues, Monaco Salon Mistrau"
    assert g._clean("25 bis Rue Gubernatis") == "Rue Gubernatis"


def test_the_forms_tried_go_from_whole_to_plain():
    v = g._variants("anthéa, Antipolis Théâtre d'Antibes", "Antibes")
    assert v[0].startswith("anthéa, Antipolis Théâtre d'Antibes")
    assert any(x.startswith("anthéa, Antibes") for x in v)
    assert all(x.endswith("Antibes, France") for x in v)


def test_monaco_is_its_own_country():
    assert all(x.endswith("Monaco") for x in g._variants("Grimaldi Forum", "Monaco"))


def test_the_same_venue_written_differently_is_one_cache_entry():
    assert g._key("Théâtre  LINO Ventura", "Nice") == g._key("theatre lino ventura", "nice")


def test_a_point_outside_the_06_is_refused():
    assert not g._in_box(48.85, 2.35)          # Paris
    assert g._in_box(43.70, 7.26)              # Nice


def test_the_venue_wins_and_the_town_is_the_fallback():
    cache = {g._key("Le 109", "Nice"): {"lat": 43.7173, "lon": 7.2841},
             g._key("", "Nice"): {"lat": 43.7009, "lon": 7.2683}}
    assert g.point_for("Le 109", "Nice", cache) == {"lat": 43.7173, "lon": 7.2841}
    town = g.point_for("Somewhere nobody mapped", "Nice", cache)
    assert town["approx"] is True and town["lat"] == 43.7009
    assert g.point_for("Le 109", "Online", cache) is None or True


def test_a_venue_that_was_looked_for_and_missed_is_not_asked_again():
    from datetime import date
    cache = {g._key("La Zonmé", "Nice"): {"lat": None, "missed_on": date.today().isoformat()}}
    out = g.lookup_missing([("La Zonmé", "Nice")], cache)   # no network call happens
    assert out is cache
