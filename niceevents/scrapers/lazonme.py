"""La Zonmé — the Nice collective/venue.

Their gigs live on a public Google Calendar; we read its .ics feed (see gcal.py).
Every event is made clickable: its own link if the calendar entry has one, else
the La Zonmé events page, so a visitor can always get to the details/tickets.
"""
from __future__ import annotations

from .gcal import GCalICS
from .base import register


@register
class LaZonme(GCalICS):
    name = "lazonme"
    label = "La Zonmé"
    CAL_ID = ("9fc9ae4b740cbf6e2d361a6c959c634e7d025e9412a811bafbac1c8144cd3648"
              "@group.calendar.google.com")
    VENUE = "La Zonmé"
    DEFAULT_TOWN = "Nice"
    URL_FALLBACK = "https://www.lazonme.fr/evenements"
    # Let the title decide, but when it's ambiguous assume a gig — La Zonmé is a
    # music venue, so "concert" beats a generic "autre".
    DEFAULT_CATEGORY = "concert"
