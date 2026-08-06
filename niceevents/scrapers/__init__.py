"""Scraper registry.

Importing this module registers every scraper via the @register decorator.
Add a new source by dropping a module here and importing it below.
"""
from .base import REGISTRY, Scraper, HttpScraper, BrowserScraper  # noqa: F401

# Static HTML / JSON — no browser needed
from . import brocabrac      # noqa: F401  vide-greniers & brocantes
from . import nice_fr        # noqa: F401  Ville de Nice (incl. Jazz Fest)
from . import openagenda     # noqa: F401  culture: opera, theatre, festivals (national API)
# Tango is NOT scraped from tango-argentin.fr any more. Retired 2026-08-06: on
# 6 August the Casita milonga was cancelled, the reference agenda said
# "(ANNULEE)", and tango-argentin.fr still listed it as on — so the site would
# have sent people to a closed door. Tango now comes from the Agenda Tango
# Argentin Nice Riviera 06 through `harvest`, which is the only tango source that
# publishes cancellations, and which also covers Cannes, Antibes and Grasse.
#
# Leaving this unregistered (rather than deleting tango.py) is what lets
# db.prune_retired clear the old rows on the next full run, and keeps the parser
# around: it is still the only source with milonga START TIMES, so if we ever
# want to enrich the calendar's all-day entries, it is here.
# from . import tango        # noqa: F401  retired, see above
from . import explore_nca    # noqa: F401  Métropole tourist office (50 communes)
from . import departement06  # noqa: F401  Département 06 agenda (Soirées Estivales, etc.)
from . import museums        # noqa: F401  MAMAC, Matisse, Chagall…
from . import maeght         # noqa: F401  Fondation Maeght (Saint-Paul-de-Vence) [browser]
from . import seed           # noqa: F401  hand-curated coast & hinterland exhibitions
from . import belaprem       # noqa: F401  Belaprem free open-air series at Le 109
from . import panda          # noqa: F401  Panda Events gigs (109 / Frigo 16 / TLV)
from . import anthea         # noqa: F401  anthéa, Antipolis Théâtre d'Antibes
from . import harvest        # noqa: F401  generic JSON-LD / iCal venue harvester
from . import swing          # noqa: F401  Swing 06 community calendar (public ICS)
from . import lazonme        # noqa: F401  La Zonmé venue (own events page)

# JS-rendered — Playwright required
from . import theatres_nice  # noqa: F401  municipal & partner theatres [browser]
from . import meetup         # noqa: F401  design, business, AI, expat
from . import ra             # noqa: F401  electronic / clubs
from . import eventbrite     # noqa: F401  business, tech, conferences

# Not scraped — read back out of our own Supabase table. Everything a human
# approved in the Table Editor comes in through here.
from . import submissions    # noqa: F401  community submissions

__all__ = ["REGISTRY", "Scraper", "HttpScraper", "BrowserScraper"]
