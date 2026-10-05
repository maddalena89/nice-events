"""Where each venue is, so events can be dots on a map.

Looked up once per venue from OpenStreetMap's Nominatim and cached in
data/places.json, which is committed. A nightly run only ever looks up venues it
has never seen, so the file grows by a handful a week and the service is barely
touched. Nominatim asks for at most one request a second and a real contact in
the User-Agent; both are honoured below.

A venue that cannot be found is remembered as a miss, with the date, so the next
run does not ask again and again. Misses are retried after RETRY_DAYS, because
venues do get added to OpenStreetMap.

Nothing here can break a build: no network, a slow answer, a changed format —
the cache is used as it stands and events without a point simply have no dot.
"""
from __future__ import annotations

import json
import logging
import re
import time
import unicodedata
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)

CACHE = Path("data/places.json")      # only for the one-off import of an old file
URL = "https://nominatim.openstreetmap.org/search"
UA = "whatsonnice.com event map (hello@whatsonnice.com)"
PAUSE = 1.1                      # Nominatim's rule: one request a second, at most
RETRY_DAYS = 60

#: The 06 and Monaco, generously. Anything outside is the wrong "Nice" — there is
#: one in Belgium and a Saint-Laurent in Quebec — and is thrown away.
BOX = (43.35, 6.55, 44.40, 7.75)      # south, west, north, east

#: Town centres, for an event whose venue cannot be placed. Marked approximate so
#: the map can draw it differently; better than no dot for "Nice, somewhere".
TOWN_FALLBACK_ZOOM = 14


def _clean(venue: str) -> str:
    """Trim a venue string down to something a map can find.

    Sources paste whole addresses, floor numbers and opening hours into the venue
    field: "Fairmont Avenue des Spélugues, 98000 Monaco Salon Mistrau". Keep the
    first two comma-parts, drop postcodes and leading street numbers.
    """
    v = re.sub(r"\s+", " ", venue or "").strip()
    v = re.sub(r"\b\d{5}\b", " ", v)                       # postcodes
    parts = [p.strip() for p in v.split(",") if p.strip()]
    v = ", ".join(parts[:2]) if parts else v
    v = re.sub(r"^\d+\s*(bis|ter)?\s+", "", v, flags=re.I)  # leading street number
    return v.strip(" ,-·")


def _key(venue: str, town: str) -> str:
    """One key per real place, whatever punctuation the source used.

    The page tidies venue text before it draws it ("Raoul Mille – Gare du Sud"
    becomes "...- Gare du Sud"), while the lookup saw the raw text, so the two
    never matched and every event fell back to its town centre (5 Oct 2026).
    Accents, case and every punctuation mark are folded away here so both forms
    land on the same key."""
    s = unicodedata.normalize("NFD", f"{venue}|{town}").encode("ascii", "ignore").decode()
    s = s.replace("|", " ~ ")                     # keep venue and town apart
    return re.sub(r"[^a-z0-9~]+", " ", s.lower()).strip()


def load(conn=None) -> dict:
    """The cache: {key: {"lat","lon","venue","town",...}}. From the database when
    given a connection (the real path), else from the old JSON file."""
    if conn is not None:
        out = {}
        for r in conn.execute("SELECT key, venue, town, lat, lon, seen_on FROM places"):
            out[r["key"] if not isinstance(r, tuple) else r[0]] = {
                "venue": r["venue"], "town": r["town"], "lat": r["lat"], "lon": r["lon"],
                ("found_on" if r["lat"] is not None else "missed_on"): r["seen_on"]}
        return out
    try:
        return json.loads(CACHE.read_text())
    except (OSError, ValueError):
        return {}


def save(cache: dict, conn=None) -> None:
    if conn is not None:
        conn.executemany(
            "INSERT INTO places (key, venue, town, lat, lon, seen_on) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET venue=excluded.venue, town=excluded.town, "
            "lat=excluded.lat, lon=excluded.lon, seen_on=excluded.seen_on",
            [(k, v.get("venue"), v.get("town"), v.get("lat"), v.get("lon"),
              v.get("found_on") or v.get("missed_on") or date.today().isoformat())
             for k, v in cache.items()])
        conn.commit()
        return
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(cache, ensure_ascii=False, indent=0, sort_keys=True))


def _in_box(lat: float, lon: float) -> bool:
    s, w, n, e = BOX
    return s <= lat <= n and w <= lon <= e


def _variants(venue: str, town: str) -> list[str]:
    """The forms to try, shortest-but-still-specific last.

    Sources write venues in every shape: "Fairmont Avenue des Spélugues, 98000
    Monaco Salon Mistrau" (a hotel with its address and a room name), "anthéa,
    Antipolis Théâtre d'Antibes" (the name, then what it is). Trying the whole
    string, then its first part, then the name with its type word, finds most of
    them; what is left is usually not in OpenStreetMap at all.
    """
    where = "Monaco" if town.lower() == "monaco" else f"{town}, France"
    first = re.split(r"[,·—–-]", venue)[0].strip()
    first = re.sub(r"^\d+\s*(bis|ter)?\s+", "", first, flags=re.I)
    out = [f"{_clean(venue)}, {where}", f"{first}, {where}"]
    # "Bibliothèque Raoul Mille - Gare du Sud": the tail is the district, and the
    # library is mapped under its own name alone.
    head = re.split(r"\s+[-–—]\s+", venue)[0].strip()
    if head and head != first:
        out.append(f"{head}, {where}")
    # "Semeuse (Théâtre de la)" — the city writes the name first and what it is
    # in brackets. Put it back the way a map has it: "Théâtre de la Semeuse".
    m = re.match(r"^(.+?)\s*\((.+?)\)", venue)
    if m:
        kind_, name_ = m.group(2).strip(), m.group(1).strip()
        if re.search(r"\b(de la|du|des|de|d')$", kind_, re.I):   # "Théâtre de la" + "La Tour"
            name_ = re.sub(r"^(la|le|les|l')\s*", "", name_, flags=re.I)
        out.append(f"{kind_} {name_}, {where}")
    kind = re.search(r"(th[ée][âa]tre|mus[ée]e|biblioth[èe]que|cin[ée]ma|galerie|salle|"
                     r"[ée]glise|chapelle|villa|palais|parc|jardin|stade|port|plage)", venue, re.I)
    if kind and kind.group(0).lower() not in first.lower():
        out.append(f"{kind.group(0)} {first}, {where}")
    seen, uniq = set(), []
    for q in out:
        q = re.sub(r"\s+", " ", q).strip()
        if len(q) > len(where) + 3 and q not in seen:
            seen.add(q); uniq.append(q)
    return uniq


def _ask(client: httpx.Client, q: str) -> Optional[tuple[float, float]]:
    s, w, n, e = BOX
    r = client.get(URL, params={"q": q, "format": "jsonv2", "limit": 1,
                                "viewbox": f"{w},{n},{e},{s}", "bounded": 1})
    if r.status_code != 200:
        log.warning("geocode: HTTP %s for %r", r.status_code, q)
        return None
    hits = r.json()
    if not hits:
        return None
    lat, lon = float(hits[0]["lat"]), float(hits[0]["lon"])
    return (lat, lon) if _in_box(lat, lon) else None


def lookup_missing(pairs: list[tuple[str, str]], cache: dict,
                   budget: int = 500, today: Optional[date] = None) -> dict:
    """Fill in every (venue, town) the cache does not know yet. Returns the cache."""
    today = today or date.today()
    todo = []
    for venue, town in pairs:
        if not venue or not town or town.lower() == "online":
            continue
        k = _key(venue, town)
        hit = cache.get(k)
        if hit and (hit.get("lat") is not None or
                    hit.get("missed_on", "") > (today - timedelta(days=RETRY_DAYS)).isoformat()):
            continue
        todo.append((k, venue, town))
    if not todo:
        return cache
    log.info("geocode: %d venue(s) to look up", len(todo))
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=20.0) as client:
            for i, (k, venue, town) in enumerate(todo[:budget]):
                hit = None
                for q in _variants(venue, town):
                    try:
                        hit = _ask(client, q)
                    except Exception as e:                  # one bad answer, carry on
                        log.warning("geocode: %s — %s", venue[:40], e)
                    time.sleep(PAUSE)
                    if hit:
                        break
                cache[k] = ({"lat": round(hit[0], 6), "lon": round(hit[1], 6), "venue": venue,
                             "town": town, "found_on": today.isoformat()} if hit else
                            {"lat": None, "venue": venue, "town": town,
                             "missed_on": today.isoformat()})
                time.sleep(PAUSE)
    except Exception as e:
        log.warning("geocode: stopped early (%s)", e)
    return cache


def lookup_towns(towns: list[str], cache: dict, today: Optional[date] = None) -> dict:
    """A point for each town itself, so an event with no findable venue still has
    a dot — drawn as approximate, because it only says "somewhere in Vence"."""
    today = today or date.today()
    todo = [t for t in dict.fromkeys(towns)
            if t and t.lower() != "online" and cache.get(_key("", t), {}).get("lat") is None]
    if not todo:
        return cache
    log.info("geocode: %d town centre(s) to look up", len(todo))
    try:
        with httpx.Client(headers={"User-Agent": UA}, timeout=20.0) as client:
            for town in todo:
                q = "Monaco" if town.lower() == "monaco" else f"{town}, Alpes-Maritimes, France"
                try:
                    hit = _ask(client, q)
                except Exception as e:
                    log.warning("geocode: town %s — %s", town, e)
                    hit = None
                cache[_key("", town)] = ({"lat": round(hit[0], 6), "lon": round(hit[1], 6),
                                          "venue": "", "town": town, "found_on": today.isoformat()}
                                         if hit else {"lat": None, "venue": "", "town": town,
                                                      "missed_on": today.isoformat()})
                time.sleep(PAUSE)
    except Exception as e:
        log.warning("geocode: towns stopped early (%s)", e)
    return cache


def point_for(venue: Optional[str], town: Optional[str], cache: dict) -> Optional[dict]:
    """{"lat","lon"} for an event, or None. Exact venue first, then the town."""
    if venue and town:
        hit = cache.get(_key(venue, town))
        if hit and hit.get("lat") is not None:
            return {"lat": hit["lat"], "lon": hit["lon"]}
    if town:
        hit = cache.get(_key("", town)) or cache.get(_key(town, town))
        if hit and hit.get("lat") is not None:
            return {"lat": hit["lat"], "lon": hit["lon"], "approx": True}
    return None
