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
    r"\byoga\b|pilates|zumba|fitness|workout|bootcamp|boot camp|cross ?fit|stretching|abdos")
_DANCE = re.compile(r"danse|dance|tango|milonga|salsa|bachata|kizomba|swing|ballet")


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
    return None


def drop_noise(events: list[dict]) -> list[dict]:
    return [e for e in events if not why(e)]
