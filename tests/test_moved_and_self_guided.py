"""Leftovers of a moved date, and self-guided visits (18 Sep 2026)."""
from niceevents.site import _drop_moved, _group_stage_runs, _is_self_guided_only


def _r(fp, start, first, last, url="https://x/match", source="explore_nca"):
    return {"fingerprint": fp, "start": start, "url": url, "source": source,
            "first_seen": first, "last_seen": last}


def test_the_old_date_of_a_moved_event_is_dropped():
    old = _r("a", "2026-09-19", "2026-08-05T09:00:00", "2026-09-02T08:40:56")
    new = _r("b", "2026-09-20", "2026-09-02T08:40:56", "2026-09-18T07:27:11")
    assert [r["fingerprint"] for r in _drop_moved([old, new])] == ["b"]


def test_dates_of_a_series_listed_side_by_side_are_kept():
    one = _r("a", "2026-09-19", "2026-08-01T08:00:00", "2026-09-14T09:00:00")
    two = _r("b", "2026-09-20", "2026-08-01T08:00:00", "2026-09-18T09:00:00")
    assert len(_drop_moved([one, two])) == 2


def test_self_guided_visits_go_and_guided_ones_stay():
    assert _is_self_guided_only({"title": "Visite libre de la Tour Saint-François"})
    assert _is_self_guided_only({"title": "Visit of the SAINT-FRANÇOIS TOWER", "note": "Self-guided visits"})
    assert not _is_self_guided_only({"title": "Visite libre ou commentée de la Villa Arson"})
    assert not _is_self_guided_only({"title": "Visite guidée du Fort Carré"})


def test_a_play_on_several_nights_becomes_one_entry_with_its_dates():
    ev = lambda d: {"title": "Orlando", "venue": "Opéra Nice Côte d’Azur", "town": "Nice",
                    "category": "scene", "start": d, "time": "20:00"}
    out = _group_stage_runs([ev("2026-10-02"), ev("2026-10-04"), ev("2026-10-06")])
    assert len(out) == 1 and out[0]["dates"] == ["2026-10-02", "2026-10-04", "2026-10-06"]


def test_a_concert_on_several_nights_is_left_alone():
    ev = lambda d: {"title": "Jazz", "venue": "Le Shapko", "town": "Nice", "category": "concert", "start": d}
    assert len(_group_stage_runs([ev("2026-10-02"), ev("2026-10-09")])) == 2
