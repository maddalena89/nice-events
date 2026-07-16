"""Core data model + normalisation for Nice/06 events.

Everything a scraper produces becomes an Event. The fingerprint is what makes
dedup possible across sources that describe the same night differently.
"""
from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Optional

# ---------------------------------------------------------------- categories

CATEGORIES = {
    "brocante": "Brocantes & vide-greniers",
    "danse": "Tango & dance",
    "concert": "Concerts & clubbing",
    "expo": "Exhibitions",
    "scene": "Stage & theatre",
    "visite": "Guided visits",
    "atelier": "Workshops",
    "business": "Business, tech & AI",
    "social": "Social & expat",
    "sport": "Sport",
    "marche": "Markets & fêtes",
    "autre": "Other",
}

# Ordered: first match wins. Tuned for the 06 sources specifically.
_CATEGORY_RULES: list[tuple[str, str]] = [
    (r"vide[- ]grenier|brocante|braderie|bourse|vide[- ]dressing|vide[- ]maison|chiner", "brocante"),
    (r"\bmilonga|\btango|practica|bal\b|guinguette|salsa|bachata|kizomba|swing|lindy|danse|dance", "danse"),
    (r"concert|jazz|dj\b|club|techno|house music|live music|festival de musique|apéro club|soirée club|rave", "concert"),
    (r"exposition|\bexpo\b|vernissage|exhibition|galerie|rétrospective|collection permanente", "expo"),
    (r"théâtre|theatre|spectacle|opéra|opera|ballet|one man show|humour|cirque|danse contemporaine", "scene"),
    (r"visite guidée|visite|guided (tour|visit)|parcours patrimoine|balade", "visite"),
    (r"atelier|workshop|stage de|masterclass|initiation|cours\b", "atelier"),
    (r"conférence|conference|meetup|networking|afterwork|startup|\bai\b|\bia\b|intelligence artificielle|"
     r"tech\b|pitch|hackathon|business|entrepreneur|coworking|summit|forum|salon professionnel|webinar", "business"),
    (r"expat|language exchange|échange linguistique|apéro|picnic|pique-nique|rencontre|social|hangout|"
     r"jeux de société|board game|quiz|blind test", "social"),
    (r"marché|market|fête|festa|foire|festin|procession|feu d'artifice|carnaval|transhumance", "marche"),
    (r"course|trail|randonnée|match|tournoi|compétition|marathon|régate|pétanque|yoga|running", "sport"),
]


def strip_accents(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c))


def slugify(text: str) -> str:
    """Accent-insensitive lowercase slug. 'Beaulieu-sur-Mer' -> 'beaulieu-sur-mer'."""
    text = strip_accents(text).lower()
    text = re.sub(r"[^\w\s-]", " ", text)
    return re.sub(r"[\s_-]+", "-", text).strip("-")


# We match against accent-stripped text, so the patterns must be accent-stripped
# too — otherwise 'fête' and 'marché' silently never match. Compiled once here
# rather than trusting every rule author to remember.
_COMPILED_RULES = [
    (re.compile(strip_accents(pattern)), cat) for pattern, cat in _CATEGORY_RULES
]


def classify(*parts: Optional[str]) -> str:
    """Guess a category from any text we have (title, type label, venue, note)."""
    hay = strip_accents(" ".join(p for p in parts if p).lower())
    for rx, cat in _COMPILED_RULES:
        if rx.search(hay):
            return cat
    return "autre"


# ------------------------------------------------------------------- towns

# The 06 communes we care about, plus common spelling variants seen in the wild.
_TOWN_CANON = {
    "nice": "Nice", "beaulieu-sur-mer": "Beaulieu-sur-Mer", "beaulieu": "Beaulieu-sur-Mer",
    "villefranche-sur-mer": "Villefranche-sur-Mer", "villefranche": "Villefranche-sur-Mer",
    "eze": "Èze", "eze-village": "Èze", "eze-sur-mer": "Èze",
    "cap-d-ail": "Cap-d'Ail", "cap-dail": "Cap-d'Ail",
    "saint-jean-cap-ferrat": "Saint-Jean-Cap-Ferrat", "st-jean-cap-ferrat": "Saint-Jean-Cap-Ferrat",
    "cagnes-sur-mer": "Cagnes-sur-Mer", "saint-laurent-du-var": "Saint-Laurent-du-Var",
    "st-laurent-du-var": "Saint-Laurent-du-Var", "vence": "Vence",
    "saint-paul-de-vence": "Saint-Paul-de-Vence", "st-paul-de-vence": "Saint-Paul-de-Vence",
    "antibes": "Antibes", "juan-les-pins": "Antibes", "cannes": "Cannes", "menton": "Menton",
    "grasse": "Grasse", "monaco": "Monaco", "beausoleil": "Beausoleil",
    "roquebrune-cap-martin": "Roquebrune-Cap-Martin", "la-turbie": "La Turbie",
    "tourrette-levens": "Tourrette-Levens", "luceram": "Lucéram", "sospel": "Sospel",
    "saint-martin-vesubie": "Saint-Martin-Vésubie", "levens": "Levens", "valdeblore": "Valdeblore",
    "la-gaude": "La Gaude", "castagniers": "Castagniers", "gourdon": "Gourdon",
    "roubion": "Roubion", "consegudes": "Conségudes", "cabris": "Cabris",
    "auribeau-sur-siagne": "Auribeau-sur-Siagne", "saint-vallier-de-thiey": "Saint-Vallier-de-Thiey",
    "la-trinite": "La Trinité", "drap": "Drap", "carros": "Carros", "colomars": "Colomars",
    "falicon": "Falicon", "aspremont": "Aspremont", "isola": "Isola", "isola-2000": "Isola 2000",
    "auron": "Auron", "la-colmiane": "La Colmiane", "roquebilliere": "Roquebillière",
    "saint-jeannet": "Saint-Jeannet", "le-broc": "Le Broc", "belvedere": "Belvédère",
}

# Postcode -> town, used when a source gives us a code but a vague place name.
_CP_HINT = {
    "06000": "Nice", "06100": "Nice", "06200": "Nice", "06300": "Nice",
    "06310": "Beaulieu-sur-Mer", "06230": "Villefranche-sur-Mer", "06360": "Èze",
    "06320": "Cap-d'Ail", "06800": "Cagnes-sur-Mer", "06700": "Saint-Laurent-du-Var",
    "06140": "Vence", "06600": "Antibes", "06400": "Cannes", "06500": "Menton",
    "06130": "Grasse", "06690": "Tourrette-Levens", "06440": "Lucéram", "06380": "Sospel",
    "06450": "Saint-Martin-Vésubie", "06670": "Castagniers", "06620": "Gourdon",
    "06420": "Roubion", "06510": "Conségudes", "06530": "Cabris",
    "06810": "Auribeau-sur-Siagne", "06460": "Saint-Vallier-de-Thiey", "06610": "La Gaude",
    "06570": "Saint-Paul-de-Vence",
}


def canon_town(raw: Optional[str], postcode: Optional[str] = None) -> str:
    """Map messy town strings onto one canonical spelling.

    `raw` may itself be a bare postcode — the tango source hands us those.
    """
    if raw:
        hit = _TOWN_CANON.get(slugify(raw))
        if hit:
            return hit
        if re.fullmatch(r"\d{5}", raw.strip()):     # raw is really a postcode
            postcode = postcode or raw.strip()
    if postcode:
        hit = _CP_HINT.get(str(postcode).strip()[:5])
        if hit:
            return hit
    return (raw or "").strip() or "Unknown"


# ------------------------------------------------------------------- dates

_FR_MONTHS = {
    "janvier": 1, "fevrier": 2, "février": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6,
    "juillet": 7, "aout": 8, "août": 8, "septembre": 9, "octobre": 10,
    "novembre": 11, "decembre": 12, "décembre": 12,
}
_EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTHS = {**_FR_MONTHS, **_EN_MONTHS}


def parse_date(text: str, default_year: Optional[int] = None) -> Optional[date]:
    """Parse the date shapes our sources actually emit.

    Handles: 2026-07-18 | 20260718 | 18/07/2026 | '18 Juillet 2026' | '18 juillet'
    | 'Sat, 11 Jul' | '11 July 2026'. Returns None rather than guessing wildly.
    """
    if not text:
        return None
    s = str(text).strip()

    m = re.search(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", s)
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))

    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)  # WP ACF: 20260718
    if m:
        return _safe_date(int(m[1]), int(m[2]), int(m[3]))

    m = re.search(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b", s)
    if m:
        return _safe_date(int(m[3]), int(m[2]), int(m[1]))

    # "18 Juillet 2026" / "11 July" / "Sat, 11 Jul"
    m = re.search(r"\b(\d{1,2})(?:er)?\s+([A-Za-zÀ-ÿ]+)\.?(?:\s+(\d{4}))?", s)
    if m:
        mon = _MONTHS.get(m[2].lower().strip("."))
        if mon:
            year = int(m[3]) if m[3] else (default_year or _rolling_year(mon))
            return _safe_date(year, mon, int(m[1]))

    # "July 11, 2026"
    m = re.search(r"\b([A-Za-zÀ-ÿ]+)\.?\s+(\d{1,2})(?:,)?(?:\s+(\d{4}))?", s)
    if m:
        mon = _MONTHS.get(m[1].lower().strip("."))
        if mon:
            year = int(m[3]) if m[3] else (default_year or _rolling_year(mon))
            return _safe_date(year, mon, int(m[2]))
    return None


def _safe_date(y: int, m: int, d: int) -> Optional[date]:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def _rolling_year(month: int) -> int:
    """A bare '2 August' means the next one, not one in the past."""
    today = date.today()
    return today.year if month >= today.month else today.year + 1


def parse_time(text: Optional[str]) -> Optional[str]:
    """'19h30' | '19:30' | '7:00pm' -> '19:30'."""
    if not text:
        return None
    s = str(text).strip().lower()

    m = re.search(r"\b(\d{1,2})\s*[:.]?\s*(\d{2})?\s*(am|pm)\b", s)
    if m:
        h = int(m[1]) % 12
        if m[3] == "pm":
            h += 12
        return f"{h:02d}:{int(m[2] or 0):02d}"

    m = re.search(r"\b(\d{1,2})\s*[h:]\s*(\d{2})?", s)
    if m:
        h, mi = int(m[1]), int(m[2] or 0)
        if 0 <= h <= 23 and 0 <= mi <= 59:
            return f"{h:02d}:{mi:02d}"
    return None


# ------------------------------------------------------------------- event

_NOISE = re.compile(r"\b(gratuit|free|nouveau|new|complet|sold ?out|annulé|cancelled)\b", re.I)


def _title_key(title: str) -> str:
    """Normalised title for dedup: strip badges, punctuation, accents, articles."""
    t = _NOISE.sub(" ", title or "")
    t = slugify(t)
    t = re.sub(r"\b(le|la|les|l|du|de|des|un|une|the|a|of|at|au|aux)\b", "", t)
    return re.sub(r"-+", "-", t).strip("-")


@dataclass
class Event:
    title: str
    start: date
    town: str
    source: str
    end: Optional[date] = None
    time: Optional[str] = None
    venue: Optional[str] = None
    category: str = "autre"
    url: Optional[str] = None
    note: Optional[str] = None
    price: Optional[str] = None
    free: bool = False
    image: Optional[str] = None
    outdoor: bool = False
    #: Zoom calls, webinars, "[En ligne]" replays. They come back from Meetup's
    #: location search even though they have no connection to Nice whatsoever —
    #: a Lyon meetup restreamed online is not an event in Nice. Kept rather than
    #: dropped so a visitor can opt into them, but hidden by default.
    online: bool = False
    submitted_by: Optional[str] = None      # set for community submissions
    approved: bool = True                   # submissions land False until reviewed
    fingerprint: str = field(default="", init=False)

    def __post_init__(self) -> None:
        if isinstance(self.start, datetime):
            self.start = self.start.date()
        if isinstance(self.end, datetime):
            self.end = self.end.date()
        if self.end and self.end < self.start:
            self.end = None
        self.title = re.sub(r"\s+", " ", (self.title or "").strip())
        self.town = canon_town(self.town)
        if self.category not in CATEGORIES:
            self.category = classify(self.title, self.note, self.venue)
        self.fingerprint = self._fingerprint()

    def _fingerprint(self) -> str:
        """Same event from two sources must collide here.

        Deliberately excludes venue and url: sources disagree on venue wording
        ('Théâtre de Verdure' vs 'Theatre de Verdure, Nice') and always disagree
        on url. Title+date+town is the stable core.
        """
        raw = f"{_title_key(self.title)}|{self.start.isoformat()}|{slugify(self.town)}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]

    @property
    def is_multiday(self) -> bool:
        return bool(self.end and self.end != self.start)

    def to_row(self) -> dict:
        d = asdict(self)
        d["start"] = self.start.isoformat()
        d["end"] = self.end.isoformat() if self.end else None
        d["fingerprint"] = self.fingerprint
        return d
