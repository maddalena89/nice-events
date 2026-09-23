"""Listings that are not "something on" and should not be on the site at all.

The site keeps every event (Maddalena, 18 Sep 2026: "let's also keep all the
events"), so this is not curation. It removes what is not an event people go
out for, and which made the list feel like a dump:

  * France Travail's whole OpenAgenda agenda: job datings, CV workshops, info
    sessions on training funding, e-invoicing briefings. 214 listings, the
    single largest source of noise.
  * Job fairs and recruiting from anywhere else.
  * Trading / crypto / "online income" / sales-funnel webinars (Meetup's online
    sweep brings these in).
  * Wellness sessions: relaxation, sophrologie, meditation, qi gong, breathwork
    (Maddalena, 23 Sep 2026: "gym douce maison sport sante, presentation de
    saison, seance de relaxation... wtf"), a theatre's season presentation, and
    a gym's open days on repeat.
  * Whatever a gym, dance school, dojo or sport-health centre puts on. Sport
    people organise themselves — races, matches, tournaments — stays. So does a
    real night out at one of those places: a milonga at a dance studio is a
    party, not a lesson. The word "cours", "class" or "lesson" in a title is
    NOT a reason on its own (Maddalena, 23 Sep 2026): a sailing lesson on the
    beach or a free trial class at a music school is something a person can
    turn up to.
  * Fitness classes named as such in the TITLE: yoga, pilates, bootcamp... Read
    in the title only, because a milonga's description can mention stretching;
    and anything with dance, tango or milonga in it is always kept.

Each rule is one line below, with its reason, so any of them can be dropped if
it ever turns out to take something real. `why()` returns the reason, or None.
"""
from __future__ import annotations

import re
import unicodedata
from typing import Optional


def _fold(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


_JOBS = re.compile(
    r"job ?dating|job expo|job fair|recrutement|\brecrute\b|forum (de l.)?emploi|"
    r"forum des metiers|salon de l.emploi|atelier cv|\bcv\b|entretien d.embauche|"
    r"offres? d.emploi|france travail|pole emploi|\bhiring\b")
_SPAM = re.compile(
    r"\btrading\b|\btrader\b|crypto|\bforex\b|bitcoin|online income|passive income|"
    r"tunnel de vente|business opportunit|network marketing|\bmlm\b|"
    r"interview questions|\bwebinar\b|\bwebinaire\b")
_FITNESS = re.compile(
    r"\byoga\b|pilates|zumba|fitness|workout|bootcamp|boot camp|cross ?fit|stretching|abdos|"
    r"gym douce|gym adapt|gym tonic|gym senior|reveil musculaire|marche nordique")
#: Wellness sessions: a weekly relaxation or meditation slot at a health centre,
#: and the online meditation/breathwork meetups. Not something on tonight.
_WELLNESS = re.compile(
    r"relaxation|sophrologie|meditation|meditative|qi ?gong|tai ?chi|breathwork|pranayama|"
    r"sport ?sante|jofitsport|bain de son|sonotherapie")
#: A theatre announcing next year's programme, and a gym's open days on repeat.
_TRADE = re.compile(r"presentation de (?:la )?saison|lancement de saison|programmes sports? sante")
_DANCE = re.compile(r"danse|dance|tango|milonga|salsa|bachata|kizomba|swing|ballet")

#: Venues that exist to teach or to train: a gym, a dance school, a dojo, a
#: health-and-sport centre. Maddalena, 23 Sep 2026: "independent organised sport
#: are good but not from gyms or dance schools".
#: The venue must BE a school or a gym, not merely mention one: a vide-grenier
#: on a school playground ("Plateau Sportif de l'école Eugène Blanc") and a
#: tango guinguette on the Place de l'École are events, and a bare "école" in an
#: address took both (23 Sep 2026).
_TEACHING_VENUE = re.compile(
    r"ecole de (?:danse|musique|cirque|theatre|langues|yoga)|"
    r"(?:dance|language|music|art) school|school of|"
    r"\bstudio\b|academie de|\bacademy\b|\bgym\b|fitness|salle de sport|"
    r"maison sport sante|\bdojo\b|centre de danse|danse club")

#: ...but those places also host real nights out, and those stay. A milonga at
#: Arty Studio is a dance party, not a lesson.
_A_NIGHT_OUT = re.compile(
    r"milonga|\bbal\b|soiree|\bapero\b|concert|spectacle|\bgala\b|festival|"
    r"tournoi|competition|\bmatch\b|portes ouvertes|vernissage|projection|"
    r"vide.grenier|brocante|\bmarche\b|guinguette|\bfete\b")


def why(e: dict) -> Optional[str]:
    url = e.get("url") or ""
    if "openagenda.com/francetravail/" in url:
        return "France Travail agenda"
    title = _fold(e.get("title"))
    text = f"{title} {_fold(e.get('note'))}"
    if _JOBS.search(text):
        return "jobs & recruiting"
    if _SPAM.search(text):
        return "trading / sales webinar"
    if _FITNESS.search(title) and not _DANCE.search(title):
        return "fitness class"
    if _WELLNESS.search(title) and not _DANCE.search(title):
        return "wellness session"
    if _TRADE.search(title):
        return "season presentation / gym promo"
    if _A_NIGHT_OUT.search(title):
        return None                      # a party at a dance school is still a party
    if _TEACHING_VENUE.search(_fold(e.get("venue"))):
        return "class at a gym or school"
    return None


def drop_noise(events: list[dict]) -> list[dict]:
    return [e for e in events if not why(e)]
