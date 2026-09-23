"""Sport is named precisely (23 Sep 2026).

Live, the short-film festival's "Compétition" screenings, a writing meetup's
"Table Reads Marathon" and a 6-week counselling "Course" all showed as Sport.
"""
from niceevents.models import classify


def test_real_sport_is_still_sport():
    for t in ["Triathlon", "Ultra trail Nice Côte d’Azur By UTMB", "Marathon de Nice",
              "Semi-marathon de Nice", "Course à pied nocturne", "Match Ligue 1 - OGC Nice / Losc",
              "Tournoi de pétanque", "Championnat de France de natation",
              "48es Régates Royales de Cannes"]:
        assert classify(t) == "sport", t


def test_an_initiation_stays_a_workshop():
    # Unchanged by the sport fix: a beginners' session is a class, wherever it is.
    assert classify("Initiation boxe anglaise") == "atelier"


def test_what_is_not_sport():
    assert classify("Compétition « Animation » d’Un festival c’est trop court") != "sport"
    assert classify("Weekend Table Reads Marathon (Sat through Sun)") != "sport"
    assert classify("Counselling Made Simple (6-Week Course) - Better Listening") == "atelier"
    assert classify("The ADHD Survival Guide - A Simpler Approach (6-Week Course)") == "atelier"
    assert classify("Compétition de danse latine") == "danse"
    assert classify("Cours de dessin") == "atelier"
