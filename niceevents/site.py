"""Static site generator.

Renders the DB into dist/index.html + dist/events.json.

The page is deliberately one self-contained file with the data inlined: no API,
no server, no build step at view time. That's what makes it hostable free on
GitHub Pages and instant to load.

Submissions: a static host can't accept a POST, so the form hands off to
whatever SUBMIT_ENDPOINT you configure (Formspree, Netlify, a Worker). With no
endpoint set it degrades to a prefilled GitHub issue link, which needs no
backend at all. See README.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import sqlite3
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape

from . import db
from .cancellations import mark_cancelled
from .suppress import drop_suppressed
from .models import CATEGORIES, _title_key, classify, slugify
from .overrides import apply_override

TPL_DIR = Path(__file__).resolve().parent.parent / "templates"

SITE_TITLE = os.environ.get("SITE_TITLE", "What's on in Nice")
SUBMIT_ENDPOINT = os.environ.get("SUBMIT_ENDPOINT", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "")  # e.g. "maddalena/nice-events"

# Supabase. Both of these are baked into the published HTML on purpose — the
# anon key is an identifier, not a password, and Row Level Security is what
# actually guards the table (see supabase/schema.sql). The service_role key is
# a different animal entirely: it bypasses RLS, is read only by the scrape step
# from a GitHub *secret*, and must never reach this module or the template.
def _clean_supabase_url(raw: str) -> str:
    """Normalise to the Supabase project root (…supabase.co).

    A common misconfiguration is pasting the full REST endpoint
    (…supabase.co/rest/v1) as SUPABASE_URL. The client then appends
    "/rest/v1/submissions" again, producing "…/rest/v1/rest/v1/submissions",
    which PostgREST rejects with PGRST125 "Invalid path specified in request URL".
    Stripping a trailing /rest[/v1] here makes either form work.
    """
    u = (raw or "").strip().rstrip("/")
    for suffix in ("/rest/v1", "/rest"):
        if u.endswith(suffix):
            u = u[: -len(suffix)]
    return u.rstrip("/")


SUPABASE_URL = _clean_supabase_url(os.environ.get("SUPABASE_URL", ""))
SUPABASE_ANON_KEY = os.environ.get("SUPABASE_ANON_KEY", "")


def _canonical_host() -> str:
    """Production host for absolute short links (whatsonnice.com/<slug>).

    Env override wins; otherwise read it from static/CNAME so the printed link and
    QR are correct even when the site is built and previewed somewhere else.
    """
    h = os.environ.get("SITE_HOST", "").strip()
    if h:
        return h
    cname = Path(__file__).resolve().parent.parent / "static" / "CNAME"
    if cname.is_file():
        lines = cname.read_text(encoding="utf-8").strip().splitlines()
        return lines[0].strip() if lines else ""
    return ""


def _collapse_overlaps(events: list[dict]) -> list[dict]:
    """Merge same-title, same-town events whose dates overlap into one row.

    Two sources describing the same run — a curated multi-day entry (e.g. a
    festival "19–26 Jul") and a scraper that lists it once per night — have
    different start dates, so they get different fingerprints and survive as
    separate rows: the exact "why is this doubled?" the DB-level dedup can't
    catch. Here, at render time, we group by normalised title + town, sweep the
    date ranges, and fold any overlapping cluster into a single event spanning
    their union. Non-overlapping repeats (a weekly class on separate nights)
    keep their own rows — they don't overlap, so they're left alone.
    """
    def d(s: str) -> date:
        return date.fromisoformat(s)

    # Cluster near-duplicate titles within a town: the same event from two sources
    # often differs only in wording ("Coun - Libera l'Art" vs "Coun. Libera l'Art
    # au Palais Lascaris", or "…un prêt d'exception" vs "…un prêt d'exception au
    # musée"). Exact-key grouping misses these, so also merge when one normalised
    # title is a word-boundary prefix of another (>= 8 chars, so short generic
    # titles aren't swallowed). The date sweep below still keeps non-overlapping
    # repeats apart.
    MIN_PREFIX = 8
    by_town: dict[str, list[dict]] = {}
    for e in events:
        by_town.setdefault(e.get("town", ""), []).append(e)

    def _root_key(sorted_keys: list[str], root: dict[str, str], tk: str) -> str:
        for shorter in sorted_keys:
            if shorter == tk:
                break                                   # only strictly shorter keys precede it
            # The prefix must be a real, multi-word title (>= 3 words), so a
            # one-word series name ("Belaprem") never swallows its per-night acts
            # ("Belaprem — Do Brasil"), while "Coun - Libera l'Art" still absorbs
            # "Coun. Libera l'Art au Palais Lascaris".
            if len(shorter) >= MIN_PREFIX and shorter.count("-") >= 2 and tk.startswith(shorter + "-"):
                return root.get(shorter, shorter)
        return tk

    groups: dict[tuple, list[dict]] = {}
    for town, evs in by_town.items():
        keys = sorted({_title_key(e.get("title", "")) for e in evs}, key=len)
        root: dict[str, str] = {}
        for k in keys:
            root[k] = _root_key(keys, root, k)
        for e in evs:
            ck = root[_title_key(e.get("title", ""))]
            groups.setdefault((ck, town), []).append(e)

    out: list[dict] = []
    for evs in groups.values():
        if len(evs) == 1:
            out.append(evs[0])
            continue
        evs.sort(key=lambda e: (e["start"], e.get("end") or e["start"]))
        cluster: list[dict] = []
        c_start = c_end = None
        for e in evs:
            s, en = d(e["start"]), d(e.get("end") or e["start"])
            if cluster and s <= c_end:                 # overlaps the open cluster
                cluster.append(e)
                c_end = max(c_end, en)
            else:
                if cluster:
                    out.append(_merge_cluster(cluster, c_start, c_end))
                cluster, c_start, c_end = [e], s, en
        if cluster:
            out.append(_merge_cluster(cluster, c_start, c_end))

    out.sort(key=lambda e: (e["start"], e.get("title", "")))
    return out


_MONTHS_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _fmt_day(iso: str) -> str:
    _, m, d = iso.split("-")
    return f"{int(d)} {_MONTHS_ABBR[int(m)]}"


#: How far ahead counts as "what's on now". Inside this window a repeating event
#: keeps one row per date; beyond it the remaining dates fold into a single row.
#: Matches the six-week window the site promises.
#:
#: This number is the whole trade-off, so it is one edit to tune: raise it and the
#: page carries more real dates, lower it and the page is shorter but goes back to
#: hiding dates behind an "Also on" line.
_NEAR_DAYS = 42


def _adjacent_blocks(evs: list[dict]) -> list[list[dict]]:
    """Split date-sorted events into blocks of consecutive (or same) nights.

    A theatre run playing Thursday, Friday and Saturday arrives as three rows and
    is ONE thing playing three nights. A milonga on three consecutive Thursdays is
    three separate nights out. The gap between dates is what tells them apart.
    """
    blocks: list[list[dict]] = []
    for e in evs:
        s = date.fromisoformat(e["start"])
        if blocks:
            last = blocks[-1]
            last_end = max(date.fromisoformat(x.get("end") or x["start"]) for x in last)
            # A theatre run is one production across several nights and every
            # night links to the same page. A bar crawl that runs every Friday
            # AND every Saturday is two separate bookings that happen to be
            # next to each other, and merging them published "7 - 8 August"
            # for a tour whose link only covers the 7th. Same listing, one
            # run; different listings, different nights out.
            same_listing = (
                not e.get("url")
                or any(x.get("url") == e.get("url") for x in last)
            )
            if (s - last_end).days <= 1 and same_listing:
                last.append(e)
                continue
        blocks.append([e])
    return blocks


def _run_row(block: list[dict]) -> dict:
    """One row for a block of consecutive nights: a single date, or a span."""
    if len(block) == 1:
        return block[0]
    start = date.fromisoformat(block[0]["start"])
    end = max(date.fromisoformat(e.get("end") or e["start"]) for e in block)
    return _merge_cluster(block, start, end)


def _fold_tail(rows: list[dict]) -> dict:
    """Fold far-future repeats into one row, with the other dates in the note."""
    first = rows[0]
    start = date.fromisoformat(first["start"])
    end = date.fromisoformat(first.get("end") or first["start"])
    base = _merge_cluster(rows, start, end)
    others = [r["start"] for r in rows[1:]]
    if others:
        shown = others[:4]
        summ = "Also on " + ", ".join(_fmt_day(x) for x in shown)
        if len(others) > len(shown):
            summ += " +%d more" % (len(others) - len(shown))
        base["note"] = (base["note"] + " · " + summ) if base.get("note") else summ
    base["recurring"] = True
    return base


def _collapse_recurring(events: list[dict], today: Optional[date] = None) -> list[dict]:
    """Tidy repeats at the SAME venue without hiding the ones happening soon.

    Grouped by title + venue + town. Venue is load-bearing: it's what tells "the
    Musée Matisse tour, on many dates" apart from "two different brocantes that
    happen to share a generic name". Events with no venue are left exactly as they
    are — without one we can't tell a genuine repeat from a coincidence.

    Each group is then handled in two steps.

    1. Consecutive nights fold into ONE row spanning them. A show playing 10, 11
       and 12 September is one run, and three identical cards in a row is noise.

    2. Whatever repeats are left keep a row EACH inside the next `_NEAR_DAYS`; only
       the dates beyond that fold into a single "Also on …" row.

    Step 2 is the fix for a real bug, so please don't collapse it back. This
    function used to fold every date of a repeat into one row anchored on the
    first, which meant the published feed carried 6 of the 41 tango milongas the
    scraper had correctly found: every milonga after the first of its kind simply
    was not on the site on the night it happened. On a what's-on, an event that
    does not appear on its own date has been lost, however tidy the page looks.
    """
    today = today or date.today()
    horizon = today + timedelta(days=_NEAR_DAYS)

    groups: dict[tuple, list[dict]] = {}
    out: list[dict] = []
    for e in events:
        v = slugify(e.get("venue") or "")
        if not v:
            out.append(e)
            continue
        groups.setdefault((_title_key(e.get("title", "")), v, e.get("town", "")), []).append(e)

    for evs in groups.values():
        if len(evs) == 1:
            out.append(evs[0])
            continue
        evs.sort(key=lambda e: (e["start"], e.get("end") or e["start"]))
        runs = [_run_row(b) for b in _adjacent_blocks(evs)]
        near = [r for r in runs if date.fromisoformat(r["start"]) <= horizon]
        far = [r for r in runs if date.fromisoformat(r["start"]) > horizon]
        out.extend(near)
        if far:
            out.append(_fold_tail(far))

    out.sort(key=lambda e: (e["start"], e.get("title", "")))
    return out


def _merge_cluster(members: list[dict], start: date, end: date) -> dict:
    """One event out of an overlapping cluster: earliest entry wins the copy,
    missing fields filled from the rest, date range widened to the union."""
    base = dict(members[0])                              # earliest start (already sorted)
    for m in members[1:]:
        for f in ("venue", "note", "url", "time", "category", "image"):
            if not base.get(f) and m.get(f):
                base[f] = m[f]
        base["free"] = bool(base.get("free") or m.get("free"))
        base["outdoor"] = bool(base.get("outdoor") or m.get("outdoor"))
    base["start"] = start.isoformat()
    if end > start:
        base["end"] = end.isoformat()
    else:
        base.pop("end", None)
    return base


# Short, human-friendly slug for a card's real short link (whatsonnice.com/<slug>).
# Drops event-type filler and articles, keeps the first couple of distinctive
# words: "Vernissage de l'artiste Jasmine" -> "jasmine". MUST match the JS
# fallback in the template (cardSlug) so a card built before the next scrape and
# one built after point at the same place.
_CARD_STOP = set((
    "vernissage exposition expo concert soiree spectacle atelier festival brocante "
    "marche visite balade projection l la le les de des du au aux un une et the a of "
    "at in on and with avec artiste artist en fete"
).split())


# No em/en dashes in any displayed title — collapse them to a plain " - ". Source
# titles occasionally carry them ("Ellsworth Kelly — At the Edge of Water"); this
# normalises everything the site shows (listing, feed, cards) in one place.
_DASH_RE = re.compile(r"\s*[—–]\s*")


def _tidy_text(t: str) -> str:
    """Fix the things scraped free text drags in: HTML entities (&quot;), fake-bold
    or fullwidth unicode (𝒅𝒊𝒎𝒂𝒏𝒄𝒉𝒆𝒔 -> dimanches), stray markdown bold markers
    from social sources, em/en dashes (never wanted), and runs of whitespace."""
    t = html.unescape(t or "")
    t = unicodedata.normalize("NFKC", t)
    t = t.replace("**", "").replace("__", "")
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)   # [label](url) -> label
    t = re.sub(r"#{1,6}\s*", "", t)                   # ## heading markers
    t = _DASH_RE.sub(" - ", t)
    return re.sub(r"\s+", " ", t).strip()


# Promoters shout and decorate. Neither reaches the page: one editorial voice
# runs through the whole listing, whatever the source did.
_EMOJI_RE = re.compile(
    "["
    "\U0001F000-\U0001FAFF"      # pictographs, emoticons, symbols
    "\U00002600-\U000027BF"      # miscellaneous symbols and dingbats
    "\U00002B00-\U00002BFF"      # arrows and shapes
    "\U00002190-\U000021FF"      # arrows
    "\U00002300-\U000023FF"      # technical, clocks, hourglasses
    "\U0001F1E6-\U0001F1FF"      # regional indicators (flags)
    "\U0000FE0F\U0000200D\U000020E3"
    "]"
)

# Capitals that are meant to be capitals.
_KEEP_CAPS = {
    "DJ", "MC", "VIP", "AI", "IA", "EDM", "NFT", "XXL", "B2B", "VO", "VF",
    "MAMAC", "TNN", "OGC", "FC", "PACA", "MJC", "CCAS", "SNCF", "CNRS",
    "UNESCO", "LGBT", "LGBTQ", "UK", "USA", "CD", "DVD", "EP", "BD",
}
_ROMAN_RE = re.compile(r"^[IVXLCDM]+$")
_VOWEL_RE = re.compile(r"[AEIOUYÀÂÄÉÈÊËÎÏÔÖÙÛÜ]", re.I)

# Joiners stay lowercase inside a de-shouted title, so "LA NUIT DES MUSEES"
# reads "La Nuit des Musées" and not "La Nuit Des Musées". Never applied to the
# first word. Deliberately only joiners: putting real words like "festival" in
# here would quietly lowercase them mid-title.
_TITLE_JOINERS = {
    "a", "à", "au", "aux", "d", "de", "des", "du", "l", "la", "le", "les",
    "et", "en", "un", "une", "sur", "sous", "pour", "avec", "dans", "par",
    "the", "of", "at", "in", "on", "and", "with", "for", "to", "from",
}


def _deshout(t: str) -> str:
    """Give a shouted title its case back.

    Only fires when the title really is shouted, 60 percent or more of its
    letters in capitals, so "MILONGA de la Liberté" and every ordinary title
    are left exactly as they are. Acronyms, roman numerals and two-letter
    words keep their capitals: the point is to stop the page being yelled at,
    not to rewrite names.
    """
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 6:
        return t
    if sum(1 for c in letters if c.isupper()) / len(letters) < 0.6:
        return t

    def fix(word: str, first: bool) -> str:
        core = word.strip(".,!?:;\"'()[]«»")
        if not core.isalpha():
            return word
        if core.upper() in _KEEP_CAPS or _ROMAN_RE.match(core):
            return word
        # No vowel means it is not a word: PSG, OGC, TNN, SNCF, CRS. This
        # catches the acronyms nobody thought to list, which matters because
        # "OGC NICE / PSG" turning into "Ogc Nice / Psg" is worse than
        # leaving the whole title shouted.
        if len(core) <= 5 and not _VOWEL_RE.search(core):
            return word
        if not first and core.lower() in _TITLE_JOINERS:
            return word.lower()
        if not first and len(core) <= 2:   # initials
            return word
        # The capital is at the first LETTER, not the first character, or a
        # quoted word comes back as "la Nueva".
        i = next(j for j, ch in enumerate(word) if ch.isalpha())
        return word[:i] + word[i].upper() + word[i + 1:].lower()

    # A word after an opening quote or bracket starts a phrase, so it is
    # capitalised like a first word: MILONGA "LA NUEVA" -> Milonga "La Nueva".
    words = t.split()
    return " ".join(
        fix(w, i == 0 or w[:1] in "\"'(«[")
        for i, w in enumerate(words)
    )


def _clean_title(t: str) -> str:
    t = _DASH_RE.sub(" - ", _tidy_text(t))
    t = _EMOJI_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    # A title that ended in an emoji otherwise keeps a dangling separator.
    # Only a separator standing on its own goes: "... | 2/-" keeps its hyphen.
    t = re.sub(r"^[-–—·|]+\s*", "", t)
    t = re.sub(r"\s+[-–—·|]+$", "", t)
    return _deshout(t.strip())


# The note column is a grab-bag: many scrapers prefix it with the time and a
# category label ("19:00 · Concert · real description"), both of which the page
# already shows elsewhere (the date pill, the category tab). Strip that prefix so
# the note reads as a plain description.
_TIME_LEAD = re.compile(r"^\s*\d{1,2}[:h]\d{2}(?:\s*[–-]\s*\d{1,2}[:h]\d{2})?\s*·\s*")
_LABEL_LEAD = re.compile(r"^\s*([^\s·][^·]{0,24}?)\s*·\s*")
# A note segment that is nothing but a start time ("21h00", "20:00", "21h").
_BARE_TIME = re.compile(r"^\d{1,2}\s*[h:]\s*\d{0,2}\s*$", re.I)
_CAT_LABELS = frozenset((
    "concert atelier theatre spectacle projection brocante ballet vide-grenier "
    "rencontre exposition opera lecture animation danse humour conference visite "
    "festival stage cirque comedie recital expo scene marche sport social business "
    "one-man-show cabaret jazz cine cinema film"
).split())

# Free-entry vs paid, inferred from words when the scraper didn't set the flag.
_FREE_POS = re.compile(r"(gratuit\w*|entr[ée]es?\s+libres?|acc[eè]s\s+libres?|free\s+entry)", re.I)
_PRICE = re.compile(r"(\d+[\.,]?\d*\s*(€|euros?)|\btarif|\bpayant|prix\s*:\s*\d)", re.I)

# The chips the page shows. "brocante" (Brocantes & vide-greniers) is folded into
# the "marche" chip, renamed "Brocantes & fêtes" and surfaced first, so those
# events live with the markets and fêtes. "brocante" stays a valid scraper/DB
# category; we remap it to "marche" only at build time (in _row_to_dict) so the
# events group under the merged chip. The page then prepends an "All the events"
# chip in front of these (see the template).
_DISPLAY_CATEGORIES = {
    "marche": "Brocantes & fêtes",
    **{k: v for k, v in CATEGORIES.items() if k not in ("brocante", "marche")},
}


def _ascii_fold(w: str) -> str:
    w = unicodedata.normalize("NFD", w)
    return "".join(c for c in w if not unicodedata.combining(c)).lower()


def _note_full(note: str) -> str:
    """Tidy a note and drop its redundant leading time / category label, but do
    NOT shorten it yet — free/paid detection wants the whole text first."""
    t = _tidy_text(note)
    # A note that is nothing but a bare time ("00:00", "21h00") is junk from a
    # scraper that had no real description, not something to show under a title.
    if _BARE_TIME.match(t.strip()):
        return ""
    t = _TIME_LEAD.sub("", t).strip()
    m = _LABEL_LEAD.match(t)
    if m and _ascii_fold(m.group(1)) in _CAT_LABELS:
        t = t[m.end():].strip()
    # Drop any standalone time segment ("· 21h00 ·"): the start time is shown on
    # its own line, so a time repeated inside the note is just a duplicate.
    if "·" in t:
        parts = [p.strip() for p in t.split("·")]
        parts = [p for p in parts if p and not _BARE_TIME.match(p)]
        t = " · ".join(parts)
    return t


def _shorten(t: str, limit: int = 150) -> str:
    """A short, tidy description: end on a sentence if there's one, else on a word
    boundary with an ellipsis. Never an em dash."""
    if len(t) <= limit:
        return t
    window = t[: limit + 1]
    for p in (". ", "! ", "? ", "; "):
        i = window.rfind(p)
        if i >= 60:
            return t[: i + 1].strip()
    i = window.rfind(" ")
    if i < 40:
        i = limit
    return t[:i].rstrip(" ,;:·-–—") + "…"


def _card_slug(title: str) -> str:
    t = unicodedata.normalize("NFD", title or "")
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    words = re.sub(r"[^a-z0-9\s]", " ", t).split()
    keep = [w for w in words if w not in _CARD_STOP and len(w) > 1]
    return "-".join((keep or words)[:2])


def _assign_slugs(events: list[dict]) -> None:
    """Give every event a unique `slug` in place. Collisions get -2, -3, … in a
    stable order (by start then title) so a given event keeps its slug run to run."""
    seen: dict[str, int] = {}
    for e in sorted(events, key=lambda e: (e.get("start", ""), e.get("title", ""))):
        base = _card_slug(e.get("title", "")) or (e.get("fingerprint", "") or "event")[:8]
        n = seen.get(base, 0) + 1
        seen[base] = n
        e["slug"] = base if n == 1 else f"{base}-{n}"


def _row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["free"] = bool(d.get("free"))
    d["outdoor"] = bool(d.get("outdoor"))
    d["online"] = bool(d.get("online"))
    for k in ("sources", "first_seen", "last_seen", "approved", "submitted_by"):
        d.pop(k, None)

    # A bare 00:00 is almost always "time unknown" defaulted to midnight, not a
    # real midnight start. Drop it so the page never claims a false time.
    if (d.get("time") or "").strip() == "00:00":
        d["time"] = None

    # Tidy the venue too (entities, dashes) but never shorten it.
    if d.get("venue"):
        d["venue"] = _tidy_text(d["venue"])

    # Fold brocantes into the markets & fêtes chip for display.
    if d.get("category") == "brocante":
        d["category"] = "marche"

    # Fix categories at display time. Meetup never gives an authoritative type, so
    # its stored category is only a guess and often wrong (a generic "meetup" or a
    # coffee morning is not nightlife); re-derive it from the title and default a
    # generic result to Social & expat, where these gatherings belong. For other
    # sources, only upgrade a row still stuck in the generic "autre" bucket when
    # the title clearly matches a real category. This never overrides a specific
    # category a source stated on purpose.
    if d.get("source") == "meetup":
        guess = classify(d.get("title"), d.get("venue"))
        d["category"] = guess if guess != "autre" else "social"
    elif d.get("category") == "autre":
        guess = classify(d.get("title"), d.get("venue"))
        if guess != "autre":
            d["category"] = guess
    # Hand-pinned category corrections win over everything above.
    apply_override(d)

    # Normalise the description: tidy entities/unicode, drop the redundant
    # time+category prefix, infer free/paid from the full text, then keep it short.
    full = _note_full(d.get("note"))
    if not d["free"] and _FREE_POS.search(full) and not _PRICE.search(full):
        d["free"] = True
    d["note"] = _shorten(full)

    return {k: v for k, v in d.items() if v not in (None, "", 0) or k in ("start", "title", "town")}


def _source_report(conn: sqlite3.Connection, events: list[dict]) -> dict:
    """Per-source health, published next to the feed as dist/sources.json.

    The recurring failure on this site is a scraper going silently to zero: the
    page still looks full because the healthy sources carry it, and the loss is
    only noticed days later when someone goes looking for a specific event. The
    information needed to catch it on the day already existed in two places that
    nobody could see together — the `runs` table (what the scraper fetched, and
    whether it raised) lived only inside the Action, and the published counts
    lived only in the feed. This joins them and publishes the result.

    Every REGISTERED source gets a row, including the ones that produced nothing.
    A dead source has to appear as a zero, not as an absence: absence is exactly
    what hid this for a week.

    `status` is the summary worth alerting on:
      failed  — the scraper raised, the error is in the row
      empty   — it ran cleanly and found nothing (broken, or genuinely nothing on)
      stale   — it found events but none of them reached the feed
      ok      — events published
    """
    from .scrapers import REGISTRY

    published: dict[str, int] = {}
    for e in events:
        name = (e.get("source") or "unknown").split(":")[0]
        published[name] = published.get(name, 0) + 1

    runs = db.last_runs(conn)
    out = []
    for name in sorted(set(REGISTRY) | set(published) | set(runs)):
        r = runs.get(name)
        found = r["found"] if r else None
        ok = bool(r["ok"]) if r else None
        count = published.get(name, 0)
        if r is not None and not ok:
            status = "failed"
        elif count:
            status = "ok"
        elif found:
            status = "stale"
        else:
            status = "empty"
        out.append({
            "name": name,
            "status": status,
            "published": count,
            "found": found,
            "added": r["added"] if r else None,
            "last_run": r["started_at"] if r else None,
            "error": (r["error"] if r else None) or None,
            "registered": name in REGISTRY,
        })
    return {
        "generated": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "published_total": len(events),
        "sources": out,
    }


#: How far ahead to describe events to search engines, and how many at most.
#: Structured data is a summary for a crawler, not a second copy of the feed:
#: the whole page is already inlined once, and repeating 2,000 events in JSON-LD
#: would roughly double the page weight to describe things nobody is searching
#: for yet. Sixty days and 150 events covers everything anyone is realistically
#: googling this week while adding ~60KB, not ~600KB.
_LD_DAYS = 60
_LD_MAX = 150


def _paris_offset(d: date) -> str:
    """UTC offset for Europe/Paris on a given date, as +HH:MM.

    Times on this site are local wall-clock times ("20:30" means half past eight
    in Nice). schema.org wants an offset or it is free to guess UTC, which would
    silently shift every evening event to a different day for readers abroad.
    """
    try:
        from zoneinfo import ZoneInfo
        off = datetime(d.year, d.month, d.day, 12, tzinfo=ZoneInfo("Europe/Paris")).utcoffset()
        total = int(off.total_seconds()) // 60
        return f"{'+' if total >= 0 else '-'}{abs(total) // 60:02d}:{abs(total) % 60:02d}"
    except Exception:
        # No tz database (rare, some slim containers). Europe/Paris is CEST from
        # the last Sunday in March to the last Sunday in October, CET otherwise.
        # March and October both have 31 days, so 25..31 always holds a Sunday.
        def last_sunday(year: int, month: int) -> date:
            end = date(year, month, 31)          # weekday(): Mon=0 … Sun=6
            return end - timedelta(days=(end.weekday() - 6) % 7)
        summer = last_sunday(d.year, 3) <= d < last_sunday(d.year, 10)
        return "+02:00" if summer else "+01:00"


def _ld_datetime(day: str, time_: Optional[str]) -> str:
    """ISO 8601 for one event date. Date only when the source gave no time —
    inventing 00:00 would claim a midnight start we do not actually know."""
    d = date.fromisoformat(day)
    if not time_:
        return day
    return f"{day}T{time_}:00{_paris_offset(d)}"


def _event_ld(e: dict, base: str) -> dict:
    """One schema.org/Event object.

    Only facts the database actually holds. Nothing is inferred to make the
    markup look richer: a wrong price or a made-up organiser is worse than an
    absent one, both for the reader and for the site's standing with Google.
    """
    ld: dict = {
        "@type": "Event",
        "name": e.get("title", ""),
        "startDate": _ld_datetime(e["start"], e.get("time")),
        "eventStatus": "https://schema.org/EventCancelled" if e.get("cancelled")
                       else "https://schema.org/EventScheduled",
    }
    # Only a genuinely LATER end date. Some rows carry end == start, and emitting
    # that as a bare date next to a timed start ("…T17:30+02:00" ending
    # "2026-08-06") reads as an event finishing at midnight before it began —
    # invalid, and Search Console rejects the item for it.
    if e.get("end") and e["end"] > e["start"]:
        ld["endDate"] = _ld_datetime(e["end"], None)

    if e.get("online"):
        ld["eventAttendanceMode"] = "https://schema.org/OnlineEventAttendanceMode"
        ld["location"] = {"@type": "VirtualLocation", "url": e.get("url") or base + "/"}
    else:
        ld["eventAttendanceMode"] = "https://schema.org/OfflineEventAttendanceMode"
        ld["location"] = {
            "@type": "Place",
            "name": e.get("venue") or e.get("town", ""),
            "address": {
                "@type": "PostalAddress",
                "addressLocality": e.get("town", ""),
                "addressRegion": "Alpes-Maritimes",
                "addressCountry": "FR",
            },
        }

    if e.get("note"):
        ld["description"] = e["note"]
    if e.get("slug"):
        # Where this event lives on THIS site. Deliberately the resolved query
        # form rather than the pretty /slug short link: the short link is served
        # by 404.html and bounces via JavaScript, and pointing a crawler at a
        # redirect chain is a good way to have the markup quietly ignored.
        ld["url"] = f"{base}/?e={e['slug']}"
    img = e.get("image")
    if isinstance(img, str) and img.startswith("http"):
        ld["image"] = img
    if e.get("free"):
        ld["isAccessibleForFree"] = True
    return ld


def _events_jsonld(events: list[dict], base: str, today: Optional[date] = None) -> str:
    """The <script type="application/ld+json"> payload, or "" if there's nothing
    to say. Returns a JSON array — the documented shape for several events living
    on one page."""
    if not base:
        return ""
    today = today or date.today()
    horizon = today + timedelta(days=_LD_DAYS)
    soon = [
        e for e in events
        if e.get("start") and today <= date.fromisoformat(e["start"]) <= horizon
    ]
    soon.sort(key=lambda e: (e["start"], e.get("title", "")))
    if not soon:
        return ""
    out = [_event_ld(e, base) for e in soon[:_LD_MAX]]
    for o in out:
        o["@context"] = "https://schema.org"
    blob = json.dumps(out, ensure_ascii=False, separators=(",", ":"))
    # This string is dropped inside a <script> element, so any "</script>" that
    # ever appears in a scraped title would end the block early and spill the
    # rest of the JSON onto the page. json.dumps does not escape these, so do it
    # here. The escapes are still valid JSON and parse back to the same text.
    return blob.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def _sitemap(base: str, updated: date) -> str:
    """A deliberately tiny sitemap.

    Only real, crawlable URLs go in. The per-event short links
    (whatsonnice.com/<slug>) are NOT listed: they have no file behind them, they
    are served by 404.html and redirected with JavaScript, and filling a sitemap
    with 2,000 soft-404s is actively harmful. When events get their own real
    pages, that is the moment to list them here.
    """
    pages = [
        ("/", "daily", "1.0"),
        ("/privacy.html", "yearly", "0.3"),
    ]
    urls = "\n".join(
        f"  <url>\n"
        f"    <loc>{base}{path}</loc>\n"
        f"    <lastmod>{updated.isoformat()}</lastmod>\n"
        f"    <changefreq>{freq}</changefreq>\n"
        f"    <priority>{pri}</priority>\n"
        f"  </url>"
        for path, freq, pri in pages
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"{urls}\n"
        "</urlset>\n"
    )


def build(conn: sqlite3.Connection, out_dir: str = "dist") -> tuple[int, str]:
    rows = db.upcoming(conn)
    # Remove phantom / dead listings first, before anything else looks at them.
    dicts = mark_cancelled(drop_suppressed([_row_to_dict(r) for r in rows]))
    # Cancelled events stay as their own struck-through row, and must NOT be folded
    # into a collapsed range, or a single cancelled date would disappear into an
    # otherwise-active run of the same event.
    cancelled = [e for e in dicts if e.get("cancelled")]
    active = [e for e in dicts if not e.get("cancelled")]
    events = _collapse_recurring(_collapse_overlaps(active)) + cancelled
    for e in events:                      # no em dashes in any displayed title
        e["title"] = _clean_title(e.get("title", ""))
    _assign_slugs(events)                 # stable, unique short link per event
    stats = db.stats(conn)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    # Machine-readable feed — free to ship, useful later for the email digest
    # and for anyone who wants to build on it.
    (out / "events.json").write_text(
        json.dumps(
            {
                "generated": datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "count": len(events),
                "events": events,
            },
            ensure_ascii=False,
            indent=1,
        ),
        encoding="utf-8",
    )

    # Per-source health, published so a dead scraper is visible from outside the
    # Action on the day it dies. Tiny file, deliberately at a stable path.
    (out / "sources.json").write_text(
        json.dumps(_source_report(conn, events), ensure_ascii=False, indent=1),
        encoding="utf-8",
    )

    # Sitemap. Written here rather than kept in static/ so <lastmod> is the day
    # the site was actually built, which is the only part of it search engines
    # really act on. robots.txt (in static/) points at this file.
    host = _canonical_host()
    base = f"https://{host}" if host else ""
    if base:
        (out / "sitemap.xml").write_text(_sitemap(base, date.today()), encoding="utf-8")

    env = Environment(
        loader=FileSystemLoader(TPL_DIR),
        autoescape=select_autoescape(["html"]),
    )
    tpl = env.get_template("index.html.jinja")

    # Supabase first: it's the only mode a passer-by can use without an account.
    # GITHUB_REPO is always set in CI, so without this ordering the github mode
    # would quietly win and keep asking strangers to sign up for GitHub.
    if SUPABASE_URL and SUPABASE_ANON_KEY:
        submit_mode = "supabase"
    elif SUBMIT_ENDPOINT:
        submit_mode = "endpoint"
    elif GITHUB_REPO:
        submit_mode = "github"
    else:
        submit_mode = "none"

    # AI poster reader endpoint. Explicit POSTER_AI_URL wins; otherwise, if
    # Supabase is configured, default to its read-poster function so deploying the
    # function is all it takes to switch the snap-a-flyer from on-device OCR to AI.
    # Empty string -> the form keeps using in-browser OCR only.
    poster_ai_url = os.environ.get("POSTER_AI_URL", "")
    poster_ai_key = os.environ.get("POSTER_AI_KEY", "")
    if not poster_ai_url and SUPABASE_URL and SUPABASE_ANON_KEY:
        poster_ai_url = f"{SUPABASE_URL}/functions/v1/read-poster"
        poster_ai_key = SUPABASE_ANON_KEY

    html = tpl.render(
        title=SITE_TITLE,
        events_json=json.dumps(events, ensure_ascii=False, separators=(",", ":")),
        categories=_DISPLAY_CATEGORIES,
        cat_json=json.dumps(_DISPLAY_CATEGORIES, ensure_ascii=False),
        stats=stats,
        updated=date.today().strftime("%-d %B %Y") if os.name != "nt"
                else date.today().strftime("%d %B %Y"),
        submit_mode=submit_mode,
        submit_endpoint=SUBMIT_ENDPOINT,
        github_repo=GITHUB_REPO,
        supabase_url=SUPABASE_URL,
        supabase_anon_key=SUPABASE_ANON_KEY,
        canonical_host=host,
        canonical_url=f"{base}/" if base else "",
        # Structured data for search engines. Built here, in Python, on purpose:
        # baked into the served HTML it is read on the first crawl, whereas
        # anything assembled by JavaScript depends on the crawler choosing to
        # render the page, which is slower and not guaranteed.
        events_jsonld=_events_jsonld(events, base),
        cf_analytics_token=os.environ.get("CF_ANALYTICS_TOKEN", ""),
        poster_ai_url=poster_ai_url,
        poster_ai_key=poster_ai_key,
        source_count=len({(r["source"] or "").split(":")[0] for r in rows}),
    )
    (out / "index.html").write_text(html, encoding="utf-8")

    # PWA + static assets: manifest, service worker, icons. Copied verbatim from
    # static/ so the site is installable to a phone home screen and opens offline.
    # Missing static dir is not an error — the site works fine without the PWA.
    static = Path(__file__).resolve().parent.parent / "static"
    if static.is_dir():
        for f in static.iterdir():
            if f.is_file():
                shutil.copy2(f, out / f.name)

    return len(events), str(out)
