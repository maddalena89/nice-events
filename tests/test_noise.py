"""What noise.py removes, and what it must never remove (18 Sep 2026)."""
from niceevents.noise import why


def e(title, note="", url=""):
    return {"title": title, "note": note, "url": url}


def test_france_travail_agenda_goes():
    assert why(e("Les aides financières de la création d'entreprise",
                 url="https://openagenda.com/francetravail/events/les-aides")) == "France Travail agenda"


def test_job_fairs_and_trading_webinars_go():
    assert why(e("Ibt Côte d'Azur : Job Dating dédié à l'industrie")) == "jobs & recruiting"
    assert why(e("Why You Should Be Trading - Free Crypto & Forex Workshop")) == "trading / sales webinar"


def test_fitness_classes_go():
    assert why(e("Saturday Morning Yoga (at Espace Rancher)")) == "fitness class"
    assert why(e("Body Bien-Etre (Yoga, Pilates & Stretching)")) == "fitness class"


def test_dance_is_always_kept():
    assert why(e("Milonga Le Bandoneon", note="warm-up stretching before the milonga")) is None
    assert why(e("Silver Swans - fitness & ballet moves class")) is None


def test_real_events_are_kept():
    for t in ["Match Ligue 1 - OGC Nice / Paris FC", "Chopin - Récital de Piano",
              "Tropical twist : DJ sets", "Le Ventre de Paris : les halles de Baltard",
              "Visite guidée du Fort Carré", "Concert jazz manouche Paco"]:
        assert why(e(t)) is None, t


def test_wellness_sessions_and_season_presentations_go():
    assert why(e("Gym douce")) == "fitness class"
    assert why(e("Séance de relaxation")) == "wellness session"
    assert why(e("Morning Medical QiGong - Online session")) == "wellness session"
    assert why(e("Free Pranayama Breathing Meditation")) == "wellness session"
    assert why(e("Présentation de saison")) == "season presentation / gym promo"
    assert why(e("Programmes Sports Santé Bien-Être avec Jofitsport06")) == "wellness session"


def test_real_evenings_out_are_still_kept():
    for t in ["Semaine de la Forme - Portes ouvertes", "Concert de musique sacrée",
              "Milonga La Trésorerie", "Nuit des musées", "Marathon de Nice"]:
        assert why(e(t)) is None, t
