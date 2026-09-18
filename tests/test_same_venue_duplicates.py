"""The same event from two sources, worded differently.

The prefix check only merges when one title starts the other. These start
differently, because one source adds a lead-in: "Une visite du passé : comment
les archives…" against "Comment les archives…". Both examples here were reported
from the live site. The Villa Arson test guards the opposite mistake, which an
early version of this check made: a guided tour and a free visit are different
things, and merging them hides the guided tour.
"""
from niceevents.site import _collapse_same_venue, _same_listing


def _e(title, venue, start="2026-09-19", end=None, time=None, town="Nice", **kw):
    d = {"title": title, "venue": venue, "start": start, "town": town,
         "time": time, "source": "x"}
    if end:
        d["end"] = end
    d.update(kw)
    return d


def test_the_chagall_talk_listed_twice():
    a = _e("Comment les archives peuvent redonner vie à un élément oublié ?",
           "Musée national Marc Chagall", time="11:00")
    b = _e("Une visite du passé : comment les archives peuvent redonner vie à un élément oublié ?",
           "Musée national Marc Chagall Avenue du Docteur Ménard", time="11:00")
    assert _same_listing(a, b)
    assert len(_collapse_same_venue([a, b])) == 1


def test_image_satellite_at_le_109():
    a = _e("Exposition collective de L'Image Satellite « Dériver encore »", "Le 109",
           end="2026-09-20", time="11:00")
    b = _e("Inauguration de l’image_Satellite", "Le 109", end="2026-09-20", time="13:00")
    assert _same_listing(a, b)


def test_a_guided_tour_and_a_free_visit_stay_separate():
    a = _e("Visite guidée dans les jardins et les expositions temporaires", "Villa Arson",
           end="2026-09-20", time="14:00")
    b = _e("Visite libre dans les jardins et les expositions temporaires", "Villa Arson",
           end="2026-09-20", time="12:00")
    assert not _same_listing(a, b)
    assert len(_collapse_same_venue([a, b])) == 2


def test_a_night_visit_is_not_the_day_visit():
    a = _e("Visite du château de Nice", "Colline du Château")
    b = _e("Visite nocturne du château de Nice", "Colline du Château")
    assert not _same_listing(a, b)


def test_two_sessions_of_one_talk_on_the_same_day_stay_separate():
    a = _e("Conférence sur les archives du musée", "Musée Chagall", time="09:00")
    b = _e("Conférence sur les archives du musée", "Musée Chagall", time="11:00")
    assert not _same_listing(a, b)


def test_different_venues_never_merge():
    a = _e("Jazz au jardin quartet", "Jardin Albert 1er", time="20:00")
    b = _e("Jazz au jardin quartet", "Théâtre de Verdure", time="20:00")
    assert not _same_listing(a, b)


def test_one_generic_word_is_not_enough():
    """"Visite du château" shares a single distinctive word with anything about
    the château; that is not evidence of the same event."""
    a = _e("Visite du château", "Colline du Château")
    b = _e("Visite du château et du cimetière", "Colline du Château")
    assert not _same_listing(a, b)


def test_the_merged_row_keeps_the_richer_listing():
    a = _e("Comment les archives peuvent redonner vie", "Musée Marc Chagall", time="11:00")
    b = _e("Une visite du passé : comment les archives peuvent redonner vie",
           "Musée Marc Chagall", time="11:00", url="https://example.com/x", note="Détails")
    merged = _collapse_same_venue([a, b])
    assert len(merged) == 1
    assert merged[0]["url"] == "https://example.com/x"
    assert merged[0]["note"] == "Détails"


# ---- A shorter listing inside a longer run (_within_run) ----------------------
# Le 109, September 2026, exactly as the sources gave it: the run from nice.fr,
# the opening weekend from OpenAgenda, and the inauguration as one row PER DAY.
# The earlier test above used a made-up 19-20 inauguration row, which is why it
# passed while the live page still showed four rows.

def _le109():
    return [
        _e("Dériver encore", "Le 109", end="2026-10-10", time="13:00", category="expo"),
        _e("Exposition collective de L'Image Satellite « Dériver encore »", "Le 109",
           end="2026-09-20", time="11:00", category="expo"),
        _e("Inauguration de l’image_Satellite", "Le 109", time="13:00", category="expo"),
        _e("Inauguration de l’image_Satellite", "Le 109", start="2026-09-20", time="12:00",
           category="expo"),
        _e("Vernissage de l'exposition collective « Dériver encore »", "Le 109",
           time="15:00", category="expo"),
    ]


def test_one_exhibition_listed_four_ways_is_one_row_for_the_whole_run():
    out = _collapse_same_venue(_le109())
    runs = [e for e in out if "vernissage" not in e["title"].lower()]
    assert len(runs) == 1
    assert (runs[0]["start"], runs[0]["end"]) == ("2026-09-19", "2026-10-10")


def test_the_vernissage_stays_its_own_event():
    out = _collapse_same_venue(_le109())
    assert any(e["title"].startswith("Vernissage") for e in out)


def test_a_guided_tour_of_an_exhibition_is_not_the_exhibition():
    run = _e("Exposition Lévitation de Mathieu Forget", "Musée de la Photographie Charles Nègre",
             start="2026-06-13", end="2026-09-27", category="expo")
    tour = _e("Visite commentée de l’exposition « Lévitation » de Mathieu Forget",
              "Musée de la Photographie Charles Nègre", time="15:00", category="expo")
    assert len(_collapse_same_venue([run, tour])) == 2


def test_a_different_kind_of_event_named_after_the_show_stays():
    run = _e("Dériver encore", "Le 109", end="2026-10-10", category="expo")
    gig = _e("Dériver encore", "Le 109", start="2026-09-26", time="21:00", category="concert")
    assert len(_collapse_same_venue([run, gig])) == 2


# ---- 18 Sep 2026: typos, one match three ways, a one-word title ---------------

def test_a_typo_in_the_title_is_still_the_same_show():
    a = _e("Le Comte de Bouderbala", "Lino Ventura (Théâtre)", time="20:30")
    b = _e("Le Comte de Bourderbala", "Théâtre Lino Ventura", time="20:30")
    assert _same_listing(a, b)


def test_one_match_listed_three_ways_is_one_row():
    rows = [_e("Match OGC Nice -Lille", "Stade Allianz Riviera Bd des jardiniers", start="2026-09-20", time="17:15"),
            _e("OGC Nice vs LOSC Lille", "Allianz Riviera", start="2026-09-20", time="17:15"),
            _e("Match Ligue 1 – OGC NICE / LOSC", "Stade Allianz Riviera Bd des jardiniers", start="2026-09-20", time="17:15")]
    assert len(_collapse_same_venue(rows)) == 1


def test_a_one_word_title_at_the_same_place_and_minute():
    a = _e("Chopin", "Opéra Nice Côte d’Azur", time="18:00")
    b = _e("Chopin - Récital de Piano", "Opéra Nice Côte d'Azur 4/6 rue Saint-François-de-Paule", time="18:00")
    assert _same_listing(a, b)


def test_worded_differently_at_different_hours_stays_apart():
    a = _e("Match OGC Nice -Lille", "Allianz Riviera", start="2026-09-20", time="17:15")
    b = _e("OGC Nice vs LOSC Lille", "Allianz Riviera", start="2026-09-20", time="21:00")
    assert not _same_listing(a, b)
