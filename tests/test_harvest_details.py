"""Time and price read out of an all-day calendar entry's description.

Every string here is copied from the live Agenda Tango Argentin feed. These
calendars are written by hand: DTSTART is a bare date and the real detail sits in
the DESCRIPTION, so an importer that trusts DTSTART alone publishes a milonga
with no time at all.
"""
from __future__ import annotations

from niceevents.scrapers.harvest import _price_from_text, _time_from_text

AMARRAS = ("Evènement organisé par l'association El Gato Tanguero et Pierre Gabrielli."
           "      &gt; Milonga de 21h00 à 01h30   Tdj : Pierre Gabrielli    "
           "TARIF : 12€    Le prix de l'entrée sera réduit à 10€ pour ceux qui "
           "viennent avec leur propre verre    LIEU : AMARRAS - 2 rue La Bruyère")

LA_LOCA = ("Milonga organisée par Ka et Jeff et l'association Two 4 Tango.      "
           "&gt; Milonga de 20h30 à 23h30   avec auberge espagnole     DJ :       "
           "TARIFS  : 6€ (adhérents) / 8€ (non adhérents)  LIEU : Arty'Studio")

ESTACION = ("Milonga en plein air gratuite de 19h30 à 23h30 (Chaises à disposition "
            "pour votre confort)    Tdj : Hernan Gerez (Argentine)    "
            "La milonga sera précédée d'un cours de tango gratuit de 18h45 à 19h30")


# --------------------------------------------------------------------- time

def test_range_gives_the_start():
    assert _time_from_text(AMARRAS) == "21:00"
    assert _time_from_text(LA_LOCA) == "20:30"


def test_a_class_before_the_milonga_does_not_steal_the_start_time():
    # The lesson runs 18h45, the milonga 19h30. The event is the milonga.
    assert _time_from_text(ESTACION) == "19:30"


def test_class_first_still_finds_the_main_event():
    text = ("Cours de tango de 18h45 à 19h30    "
            "&gt; Milonga de 19h30 à 23h30")
    assert _time_from_text(text) == "19:30"


def test_a_partir_de():
    assert _time_from_text("Milonga à partir de 19h  entrée libre") == "19:00"
    assert _time_from_text("Bal dès 20h30") == "20:30"


def test_a_bare_hour_in_prose_is_not_a_start_time():
    # "réservation avant 18h" is a deadline. A wrong time is worse than none.
    assert _time_from_text("Milonga au kiosque. Réservation avant 18h par mail.") is None


def test_nothing_to_read():
    assert _time_from_text("") is None
    assert _time_from_text("Milonga au Kiosque à musique, venez nombreux") is None


def test_a_class_time_alone_is_not_used_as_the_start():
    # No way to tell from the text when the main event picks up, so say nothing.
    assert _time_from_text("Un cours de tango de 18h45 à 19h30") is None


def test_a_tariff_table_is_left_to_the_description():
    # Cinéma Tango, 2 August 2026. No single number belongs on a card, and a
    # truncated one would read as a real price.
    table = ("TARIFS : - Cours seul 12 € / adhérents 10 € - Milonga seule 15 € / "
             "adhérents 12 € - Cours + Milonga 20 € / adhérents 15 €")
    assert _price_from_text(table) is None


# -------------------------------------------------------------------- price

def test_single_tarif():
    assert _price_from_text(AMARRAS) == "12€"


def test_two_tier_tarif():
    assert _price_from_text(LA_LOCA) == "6€ (adhérents) / 8€ (non adhérents)"


def test_free_milonga_has_no_price_line():
    # "gratuite" is in the prose, not a TARIF line. site.py infers free from the
    # note text, so there is nothing to put in the price field here.
    assert _price_from_text(ESTACION) is None


def test_a_price_label_with_no_number_is_ignored():
    assert _price_from_text("TARIF :      LIEU : Arty Studio") is None
