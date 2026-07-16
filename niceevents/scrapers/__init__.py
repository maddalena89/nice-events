"""Scraper registry.

Importing this module registers every scraper via the @register decorator.
Add a new source by dropping a module here and importing it below.
"""
from .base import REGISTRY, Scraper, HttpScraper, BrowserScraper  # noqa: F401

# Static HTML / JSON — no browser needed
from . import brocabrac      # noqa: F401  vide-greniers & brocantes
from . import nice_fr        # noqa: F401  Ville de Nice (incl. Jazz Fest)
from . import tango          # noqa: F401  milongas
from . import explore_nca    # noqa: F401  Métropole tourist office (50 communes)
from . import museums        # noqa: F401  Maeght, MAMAC, Matisse, Chagall…

# JS-rendered — Playwright required
from . import meetup         # noqa: F401  design, business, AI, expat
from . import ra             # noqa: F401  electronic / clubs
from . import eventbrite     # noqa: F401  business, tech, conferences

# Not scraped — read back out of our own Supabase table. Everything a human
# approved in the Table Editor comes in through here.
from . import submissions    # noqa: F401  community submissions

__all__ = ["REGISTRY", "Scraper", "HttpScraper", "BrowserScraper"]
