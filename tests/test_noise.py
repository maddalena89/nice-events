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


def test_dance_is_kept_unless_it_is_a_dance_school_class():
    assert why(e("Milonga Le Bandoneon", note="warm-up stretching before the milonga")) is None
    # The title alone is never the reason; the venue is (23 Sep 2026).
    assert why(e("Silver Swans - fitness & ballet moves class")) is None
    assert why({"title": "Silver Swans - fitness & ballet moves class",
                "venue": "Melting Danse - Ecole de danse à Nice 06"}) == "class at a gym or school"


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


def test_gym_and_dance_school_classes_go():
    assert why({"title": "Karaté", "venue": "Maison Sport Santé"}) == "class at a gym or school"
    assert why({"title": "Initiation boxe anglaise", "venue": "Maison Sport Santé"}) == "class at a gym or school"
    assert why({"title": "Stage de Balboa débutant - Rockswing06",
                "venue": "fit'n gym Danse club"}) is not None


def test_a_night_out_at_a_dance_school_stays():
    assert why({"title": "Milonga la Loca", "venue": "Arty Studio, 25 bis Rue Gubernatis"}) is None
    assert why({"title": "Apero Tango de Ka &Jeff", "venue": "Arty Studio"}) is None
    assert why({"title": "Concert de fin d’année", "venue": "Conservatoire de musique"}) is None


def test_a_lesson_someone_can_turn_up_to_stays():
    # Not removed for the word alone: a free trial class, a sailing lesson.
    assert why({"title": "Cours d’essai gratuit de Maracatu", "venue": "Offjazz"}) is None
    assert why({"title": "Sailing Lessons, 10:00am", "venue": "Beach"}) is None


def test_organised_sport_and_real_workshops_stay():
    for ev in [{"title": "Marathon de Nice"}, {"title": "Tournoi de pétanque"},
               {"title": "Match Ligue 1 - OGC Nice / Losc", "venue": "Allianz Riviera"},
               {"title": "Stage de permaculture", "venue": "Maison de l’Environnement"},
               {"title": "Initiation au cirque avec Les Uto’pistes", "venue": "Le 109"},
               {"title": "Brocante du cours Saleya", "venue": "Cours Saleya"}]:
        assert why(ev) is None, ev["title"]


def test_a_school_in_an_address_is_not_a_dance_school():
    # Both were taken by a bare "école" in the venue (23 Sep 2026).
    assert why({"title": "Vide grenier automne",
                "venue": "Plateau Sportif de l'école Eugène Blanc"}) is None
    assert why({"title": "Tango Guinguette 6 Le P'tit Marathon de Cantaron",
                "venue": "Place de l'École"}) is None
    assert why({"title": "Silver Swans - ballet moves class",
                "venue": "Melting Danse - Ecole de danse à Nice 06"}) == "class at a gym or school"
