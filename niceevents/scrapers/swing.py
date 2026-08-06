"""Swing 06 — the community swing/lindy/balboa calendar for the Alpes-Maritimes.

A public Google Calendar the organisers keep; we read its .ics feed. See gcal.py.
"""
from __future__ import annotations

from .gcal import GCalICS
from .base import register


@register
class Swing06(GCalICS):
    name = "swing"
    label = "Swing 06 (calendar)"
    CAL_ID = ("cf05fbaecad3e753f42942b93c6d846c9bd25a486727781945edf39eaac873b5"
              "@group.calendar.google.com")
    CATEGORY = "danse"          # a swing calendar is, definitionally, dance
