"""Phantom second days, and shouted titles.

A reader asked why the Riviera bar crawl showed 7 to 8 August when it is only
on the 7th. Three separate bugs answered that question, each with a different
cause, and each is pinned here against the real shape of the data.
"""
from __future__ import annotations

from datetime import date

from niceevents import db
from niceevents.models import Event
from niceevents.scrapers.brocabrac import Brocabrac
from niceevents.scrapers.harvest import _ics_end_date
from niceevents.site import _clean_title, _collapse_overlaps, _collapse_recurring

TODAY = date(2026, 8, 1)


# --------------------------------------------------------------------------
# 1. brocabrac: a section wrapper must not claim the previous day's date
# --------------------------------------------------------------------------

# The real page shape: <div class="ev-section"> holds the date heading AND the
# cards for that day, so the walk meets the section while `current` is still
# yesterday. A section with one card used to leak that card onto the day before.
TWO_DAYS = """
<div class="block ev-list">
  <div class="ev-section">
    <div class="section-title"><h2>08 Août 2026</h2></div>
    <div class="ev">
      <h3><a href="/06/gourdon/1389618-vide-grenier">Gourdon Vide grenier</a></h3>
      06620 - Vide-Grenier - Place du Château
    </div>
  </div>
  <div class="ev-section">
    <div class="section-title"><h2>09 Août 2026</h2></div>
    <div class="ev">
      <h3><a href="/06/nice/1392047-vide-grenier-du-vieux-nice">Nice Vide grenier du vieux nice</a></h3>
      06300 - Vide-Grenier - Place du Palais de Justice
    </div>
  </div>
</div>"""

# A genuine two day brocante IS listed under both headings, and must survive.
GENUINE_TWO_DAY = """
<div class="block ev-list">
  <div class="ev-section">
    <div class="section-title"><h2>15 Août 2026</h2></div>
    <div class="ev"><h3><a href="/06/auribeau-sur-siagne/1387093-brocante">Auribeau Brocante</a></h3>
    06810 - Brocante - notre-dame de valcluse</div>
  </div>
  <div class="ev-section">
    <div class="section-title"><h2>16 Août 2026</h2></div>
    <div class="ev"><h3><a href="/06/auribeau-sur-siagne/1387093-brocante">Auribeau Brocante</a></h3>
    06810 - Brocante - notre-dame de valcluse</div>
  </div>
</div>"""


def _parse(html):
    return list(Brocabrac.__new__(Brocabrac)._parse(html))


def test_single_card_section_is_not_dated_a_day_early():
    # Vide grenier du vieux nice is Sunday 9 August. It went out as 8 to 9.
    vieux = [ev.start for ev in _parse(TWO_DAYS) if "vieux" in (ev.url or "")]
    assert vieux == [date(2026, 8, 9)]


def test_the_days_own_card_still_comes_through():
    starts = sorted(ev.start for ev in _parse(TWO_DAYS))
    assert starts == [date(2026, 8, 8), date(2026, 8, 9)]


def test_real_two_day_brocante_keeps_both_dates():
    starts = sorted(ev.start for ev in _parse(GENUINE_TWO_DAY))
    assert starts == [date(2026, 8, 15), date(2026, 8, 16)]


# --------------------------------------------------------------------------
# 2. harvest: a night that runs past midnight is one night out
# --------------------------------------------------------------------------

def test_milonga_finishing_after_midnight_is_one_night():
    # MILONGA "El Gato Tanguero", 8 August 21:00, published as 8 to 9 August.
    assert _ics_end_date("20260808T210000", "20260809T010000") is None


def test_evening_event_finishing_before_midnight_is_one_night():
    assert _ics_end_date("20260808T193000", "20260808T233000") is None


def test_end_at_exactly_midnight_is_still_the_same_night():
    assert _ics_end_date("20260808T210000", "20260809T000000") is None


def test_date_only_dtend_is_exclusive():
    # A one day all-day entry carries the NEXT date by spec.
    assert _ics_end_date("20260808", "20260809") is None


def test_date_only_multiday_keeps_its_last_real_day():
    assert _ics_end_date("20260808", "20260811") == date(2026, 8, 10)


def test_a_real_two_day_event_keeps_its_second_day():
    # Ends in the afternoon, not before dawn: this one really does run twice.
    assert _ics_end_date("20260808T100000", "20260809T180000") == date(2026, 8, 9)


def test_two_night_run_is_untouched():
    assert _ics_end_date("20260808T210000", "20260810T020000") == date(2026, 8, 10)


def test_no_dtend_means_no_end():
    assert _ics_end_date("20260808T200000", "") is None


def test_a_utc_end_is_read_in_the_same_frame_as_the_start():
    # 23:30 UTC is 01:30 in Nice the next morning: still one night out.
    assert _ics_end_date("20260808T190000Z", "20260808T233000Z") is None


# --------------------------------------------------------------------------
# 3. site: two separately bookable nights are not one run
# --------------------------------------------------------------------------

def _pipeline(evs, today=TODAY):
    return _collapse_recurring(_collapse_overlaps(evs), today=today)


def test_friday_and_saturday_crawls_stay_two_nights():
    # The organiser runs this every Friday AND Saturday, booked separately.
    evs = [
        {"title": "Nice Riviera Bar Crawl", "town": "Nice", "venue": "Villa st Exupery",
         "start": "2026-08-07", "url": "https://www.meetup.com/x/events/315739163/"},
        {"title": "Nice Riviera Bar Crawl", "town": "Nice", "venue": "Villa st Exupery",
         "start": "2026-08-08", "url": "https://www.meetup.com/x/events/315739164/"},
    ]
    out = _pipeline(evs)
    assert len(out) == 2
    assert [e["start"] for e in out] == ["2026-08-07", "2026-08-08"]
    assert not any(e.get("end") for e in out)


def test_theatre_run_sharing_one_page_still_collapses():
    evs = [
        {"title": "Scripto", "town": "Antibes", "venue": "Anthéa",
         "start": "2026-09-25", "url": "https://anthea-antibes.fr/scripto"},
        {"title": "Scripto", "town": "Antibes", "venue": "Anthéa",
         "start": "2026-09-26", "url": "https://anthea-antibes.fr/scripto"},
    ]
    out = _pipeline(evs)
    assert len(out) == 1
    assert out[0]["start"] == "2026-09-25" and out[0]["end"] == "2026-09-26"


def test_run_with_no_urls_still_collapses():
    evs = [
        {"title": "L'Abribus", "town": "Nice", "venue": "TNN", "start": "2026-09-18"},
        {"title": "L'Abribus", "town": "Nice", "venue": "TNN", "start": "2026-09-19"},
    ]
    out = _pipeline(evs)
    assert len(out) == 1 and out[0]["end"] == "2026-09-19"


# --------------------------------------------------------------------------
# 4. titles: no emoji, no shouting
# --------------------------------------------------------------------------

def test_emoji_are_stripped_and_shouting_is_undone():
    raw = "\U0001F525 NICE RIVIERA BAR CRAWL & PUB TOUR — BEST NICE NIGHTLIFE EXPERIENCE \U0001F525"
    assert _clean_title(raw) == (
        "Nice Riviera Bar Crawl & Pub Tour - Best Nice Nightlife Experience"
    )


def test_no_dangling_separator_where_an_emoji_was():
    assert _clean_title("\U0001F539 Apéro Web Nice ! \U0001F539") == "Apéro Web Nice !"
    assert _clean_title("Mojitos & Sunset Vibes at La Shounga \U0001F379") == (
        "Mojitos & Sunset Vibes at La Shounga"
    )


def test_a_shouted_name_gets_its_case_back():
    assert _clean_title("DOUCE FRANCE") == "Douce France"
    assert _clean_title("GIPSY 4 EVER") == "Gipsy 4 Ever"
    assert _clean_title("ALPES AZUR MERCANTOUR - Nuit des Perséïdes") == (
        "Alpes Azur Mercantour - Nuit des Perséïdes"
    )


def test_a_single_shouted_word_is_de_shouted_too():
    """CHANGED 2026-08-21: no word on the page is left in caps.

    This used to assert the opposite — "MILONGA de la Liberté" was deliberately
    left alone, on the reasoning that one capitalised word is a name rather than
    shouting. On the page it did not read that way. A day's rows carried
    'MILONGA "El Gato Tanguero"', 'Soirées MUSIC', "Milonga de L'AMITIE" and
    'Language Exchange ROOF TOP', each shouting a different word, and the list
    looked like four sources rather than one site.

    Acronyms are still protected, which is the whole reason this is a word-level
    rule with guards and not a blanket .title() call.
    """
    assert _clean_title("MILONGA de la Liberté") == "Milonga de la Liberté"
    assert _clean_title('MILONGA "El Gato Tanguero" aux Amarras') == (
        'Milonga "El Gato Tanguero" aux Amarras'
    )
    assert _clean_title("Soirées MUSIC - Les Canailles") == "Soirées Music - Les Canailles"


def test_an_ordinary_title_is_untouched():
    assert _clean_title("Arrivée du Tour de France Femmes à Nice") == (
        "Arrivée du Tour de France Femmes à Nice"
    )
    assert _clean_title("Match Ligue 1 - OGC NICE / FC Lorient") == (
        "Match Ligue 1 - OGC Nice / FC Lorient"      # OGC and FC survive
    )


def test_joiners_stay_lowercase_but_never_the_first_word():
    assert _clean_title("SOIRÉE DJ AU MAMAC AVEC VIP") == "Soirée DJ au MAMAC avec VIP"
    assert _clean_title("LA NUIT DES MUSÉES") == "La Nuit des Musées"


def test_unlisted_acronyms_survive_because_they_have_no_vowel():
    # "OGC NICE / PSG" turning into "Ogc Nice / Psg" is worse than leaving it.
    assert _clean_title("Match Ligue 1 - OGC NICE / PSG") == (
        "Match Ligue 1 - OGC Nice / PSG"
    )
    assert _clean_title("CONCERT DU TNN AVEC LA CRS") == "Concert du TNN avec la CRS"


def test_a_quoted_word_is_capitalised_like_a_first_word():
    assert _clean_title('MILONGA "EL GATO TANGUERO" AUX AMARRAS') == (
        'Milonga "El Gato Tanguero" aux Amarras'
    )
    assert _clean_title("«LES INOUBLIABLES»") == "«Les Inoubliables»"


def test_only_a_dangling_separator_is_trimmed():
    # The hyphen in "2/-" is glued to the text and must stay.
    assert _clean_title("D&D 2024e | \U0001F987 Curse of Strahd \U0001F3F0 | 2/-") == (
        "D&D 2024e | Curse of Strahd | 2/-"
    )


def test_bullet_separators_survive():
    assert _clean_title("☀️ Sunrise 5K Run • Nice Fitness") == (
        "Sunrise 5K Run • Nice Fitness"
    )


# --------------------------------------------------------------------------
# 5. a scraper correcting itself must be able to take a value back
# --------------------------------------------------------------------------

def _ev(**kw):
    base = dict(title="MILONGA test", start=date(2026, 8, 8), town="Nice",
                venue="Les Amarras", source="harvest")
    base.update(kw)
    return Event(**base)


def test_owning_source_can_clear_a_wrong_end_date():
    with db.connect(":memory:") as conn:
        db.upsert(conn, [_ev(end=date(2026, 8, 9))])
        db.upsert(conn, [_ev(end=None)])          # scraper fixed, no end now
        assert conn.execute("SELECT end FROM events").fetchone()["end"] is None


def test_owning_source_can_clear_a_wrong_free_tag():
    with db.connect(":memory:") as conn:
        db.upsert(conn, [_ev(source="meetup", free=True)])
        db.upsert(conn, [_ev(source="meetup", free=False)])
        assert not conn.execute("SELECT free FROM events").fetchone()["free"]


def test_a_second_source_cannot_wipe_what_it_does_not_know():
    with db.connect(":memory:") as conn:
        db.upsert(conn, [_ev(end=date(2026, 8, 11), free=True)])
        db.upsert(conn, [_ev(source="openagenda", end=None, free=False)])
        row = conn.execute("SELECT end, free FROM events").fetchone()
        assert row["end"] == "2026-08-11"
        assert row["free"]


# ------------------------------------------------- unclosed brackets and times
#
# 21 August 2026, from the live page. Meetup titles are typed by hand into a box
# with no validation, so they arrive unfinished and with the start time in the
# name instead of the time field.

from niceevents.site import _close_brackets, _time_from_title


def test_an_unclosed_bracket_is_closed():
    assert _clean_title("Saturday Morning Yoga (at Espace Rancher!") == (
        "Saturday Morning Yoga (at Espace Rancher)"
    )
    assert _close_brackets("Concert [jazz") == "Concert [jazz]"
    assert _close_brackets("Expo « Lumière") == "Expo « Lumière»"


def test_a_trailing_opener_with_nothing_after_it_is_dropped():
    assert _close_brackets("Brocante du Cours Saleya (") == "Brocante du Cours Saleya"


def test_a_balanced_title_and_a_stray_closer_are_untouched():
    assert _close_brackets("Soirée (complet)") == "Soirée (complet)"
    assert _close_brackets("Atelier 2) suite") == "Atelier 2) suite"


def test_a_time_in_the_title_moves_to_the_time_field():
    assert _time_from_title("Saturday Morning Yoga 12h30", None) == (
        "Saturday Morning Yoga", "12:30")
    assert _time_from_title("Concert à 20h", None) == ("Concert", "20:00")


def test_a_number_that_is_not_a_time_is_left_where_it_is():
    assert _time_from_title("Apéro 20", None) == ("Apéro 20", None)
    assert _time_from_title("Rétrospective 2026", None) == ("Rétrospective 2026", None)


def test_a_stored_time_always_wins():
    """The title is a guess; a time field came from structured data. On a
    disagreement, change nothing — that is a data fault worth seeing."""
    assert _time_from_title("Yoga 12h30", "19:00") == ("Yoga 12h30", "19:00")
    assert _time_from_title("Yoga 12h30", "00:00") == ("Yoga", "12:30")   # 00:00 = unknown


def test_a_title_that_is_only_a_time_keeps_its_text():
    assert _time_from_title("12h30", None) == ("12h30", "12:30")


def test_acronyms_with_vowels_survive_word_level_deshouting():
    """The no-vowel rule cannot save these, so they are in _KEEP_CAPS. Taken
    from the words the change actually altered across the live feed."""
    for t, keep in [
        ("Expositions AMSL Aquarelle", "AMSL"),
        ("Free Startup Office Hours AMA", "AMA"),
        ("Trail UTMB 2026", "UTMB"),
        ("Permanence UNAFAM", "UNAFAM"),
        ("Journées JEP au CIAP", "JEP"),
    ]:
        assert keep in _clean_title(t), f"{keep} lost in {_clean_title(t)!r}"


def test_a_colon_without_minutes_is_not_a_time():
    """"Walk & Talk 1 : « … »" is an edition number and a separator. Reading it
    as 01:00 sorted that event to the very top of its day."""
    t = "Walk & Talk 1 : « Je voudrais tellement rencontrer des gens comme moi »"
    assert _time_from_title(t, None) == (t, None)
    assert _time_from_title("Atelier 3 : les bases", None) == ("Atelier 3 : les bases", None)
    # but "h" without minutes IS a time people write
    assert _time_from_title("Concert à 20h", None) == ("Concert", "20:00")
