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
