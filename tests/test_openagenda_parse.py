

# ---- times are Nice time, not UTC (18 Sep 2026) -------------------------------
from niceevents.scrapers.openagenda import _iso_date as _d, _iso_time as _t


def test_a_utc_time_is_shown_in_nice_time():
    # France Travail, "Comprendre les financements": 09:30 in Nice.
    assert _t("2026-09-18T07:30:00+00:00") == "09:30"
    assert _t("2026-01-15T18:00:00+00:00") == "19:00"          # winter: one hour


def test_a_local_time_stays_as_it_is():
    assert _t("2026-07-18T19:30:00+02:00") == "19:30"


def test_no_time_given_does_not_move_the_event_to_the_day_before():
    # Local midnight is 22:00 UTC the previous evening.
    assert _d("2026-09-17T22:00:00+00:00").isoformat() == "2026-09-18"
    assert _t("2026-09-17T22:00:00+00:00") is None
