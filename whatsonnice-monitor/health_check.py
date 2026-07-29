#!/usr/bin/env python3
"""
Daily health monitor for whatsonnice.com.

Fetches events.json, checks freshness, scans for data anomalies, and reports.
Read-only. It never changes code or data.

Notifications:
  - If NTFY_TOPIC is set, a phone push is sent via https://ntfy.sh when there
    are problems (and, if NTFY_ALWAYS=1, also on healthy days).
  - The script exits 1 when problems are found, so a scheduler (e.g. GitHub
    Actions) can also flag the run and email you.

Because the exact field names in events.json may vary, this reads each event
defensively and tries several common key names. If it can't find the fields it
expects, it says so in the report instead of silently passing.
"""

import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone, timedelta

URL = "https://whatsonnice.com/events.json"
FRESH_HOURS = 48
LONG_RANGE_DAYS = 10

EURO_RE = re.compile(r"(\d+[.,]?\d*)\s*(?:€|eur\b|euros?\b)", re.IGNORECASE)
FREE_WORDS_RE = re.compile(r"\b(gratuit|gratuite|gratuits|free|entrée libre|entree libre)\b", re.IGNORECASE)


def first(d, *keys):
    """Return the first present, non-empty value among the given keys."""
    for k in keys:
        if k in d and d[k] not in (None, "", []):
            return d[k]
    return None


def parse_dt(value):
    """Best-effort parse of a date or datetime string. Returns a date or None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value, tz=timezone.utc).date()
        except Exception:
            return None
    s = str(value).strip()
    # Try full ISO first.
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date()
    except Exception:
        pass
    # Try common date-only formats.
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except Exception:
            continue
    return None


def parse_generated(value):
    if value is None:
        return None
    s = str(value).strip()
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def fetch():
    req = urllib.request.Request(
        f"{URL}?t={int(datetime.now(timezone.utc).timestamp())}",
        headers={"User-Agent": "whatsonnice-healthcheck/1.0"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


def norm_title(t):
    return re.sub(r"\s+", " ", str(t or "").strip().lower())


def run():
    problems = []  # list of (group, message)

    try:
        data = fetch()
    except Exception as e:
        return (["FETCH FAILED: could not retrieve events.json (%s). "
                 "The site may be down or the URL changed." % e], 1)

    events = data.get("events")
    if not isinstance(events, list):
        return (["STRUCTURE: no 'events' array found in the JSON. "
                 "Keys present: %s" % ", ".join(map(str, data.keys()))], 1)

    now = datetime.now(timezone.utc)
    today = now.date()

    # --- Freshness ---
    gen_raw = data.get("generated")
    gen = parse_generated(gen_raw)
    if gen is None:
        problems.append(("FRESHNESS",
                         "could not read a 'generated' timestamp (value: %r). "
                         "Cannot confirm the scraper is running." % gen_raw))
    else:
        age = now - gen
        if age > timedelta(hours=FRESH_HOURS):
            hrs = int(age.total_seconds() // 3600)
            problems.append(("FRESHNESS",
                             "data is %d hours old (generated %s). The daily "
                             "scraper has probably STOPPED. This is the most "
                             "important problem." % (hrs, gen.isoformat())))

    # Track whether we ever found the fields we expect, to warn if schema differs.
    saw_time = saw_date = saw_town = saw_note = False

    false_midnight = []
    past = []
    long_range = []
    empty_note = []
    price_conflict = []
    seen = {}
    dupes = []

    for i, ev in enumerate(events):
        if not isinstance(ev, dict):
            continue
        title = first(ev, "title", "name", "titre") or "(untitled #%d)" % i
        t = first(ev, "time", "heure", "start_time", "startTime")
        start = first(ev, "date", "start", "start_date", "startDate", "date_start", "dateDebut")
        end = first(ev, "end", "end_date", "endDate", "date_end", "dateFin")
        town = first(ev, "town", "city", "ville", "commune", "location", "lieu")
        note = first(ev, "note", "description", "desc", "details", "notes")
        free_flag = ev.get("free")
        price = first(ev, "price", "prix", "tarif", "cost")

        if t is not None:
            saw_time = True
        if start is not None:
            saw_date = True
        if town is not None:
            saw_town = True
        if note is not None:
            saw_note = True

        sd = parse_dt(start)
        ed = parse_dt(end)

        # False midnight
        if str(t).strip() == "00:00":
            false_midnight.append((title, start))

        # Past start date still listed
        if sd is not None and sd < today:
            past.append((title, sd.isoformat(), town))

        # Recurring rendered as one long range
        if sd and ed and (ed - sd).days > LONG_RANGE_DAYS:
            hay = " ".join(str(x) for x in (note, title) if x)
            if re.search(r"also on", hay, re.IGNORECASE):
                long_range.append((title, "%s to %s (%d days)"
                                   % (sd.isoformat(), ed.isoformat(), (ed - sd).days)))

        # Empty / missing note
        if note is None or str(note).strip() == "":
            empty_note.append((title, sd.isoformat() if sd else str(start)))

        # Free vs price contradiction
        note_str = str(note or "")
        has_euro = bool(EURO_RE.search(note_str)) or (
            price not in (None, "", 0, "0") and EURO_RE.search(str(price)))
        says_free_words = bool(FREE_WORDS_RE.search(note_str))
        is_free_flag = free_flag is True or (isinstance(free_flag, str)
                                             and free_flag.lower() in ("true", "yes", "1", "oui"))
        if is_free_flag and has_euro:
            price_conflict.append((title, "marked free but a price is mentioned"))
        elif (free_flag is False) and says_free_words and not has_euro:
            price_conflict.append((title, "marked not-free but text says it is free/gratuit"))

        # Duplicate detection
        key = (norm_title(title), sd.isoformat() if sd else str(start),
               norm_title(town))
        if key in seen:
            dupes.append((title, sd.isoformat() if sd else str(start), town))
        else:
            seen[key] = i

    def add(group, items, fmt):
        if items:
            lines = "\n".join("   - " + fmt(x) for x in items[:40])
            more = "" if len(items) <= 40 else "\n   ... and %d more" % (len(items) - 40)
            problems.append((group, "%d found:\n%s%s" % (len(items), lines, more)))

    add("FALSE MIDNIGHTS", false_midnight, lambda x: '"%s" (%s)' % (x[0], x[1]))
    add("PAST EVENTS STILL LISTED", past, lambda x: '"%s" on %s%s'
        % (x[0], x[1], (" [%s]" % x[2]) if x[2] else ""))
    add("LIKELY DUPLICATES", dupes, lambda x: '"%s" on %s%s'
        % (x[0], x[1], (" [%s]" % x[2]) if x[2] else ""))
    add("LONG CONTINUOUS RANGE (recurring?)", long_range, lambda x: '"%s" %s' % (x[0], x[1]))
    add("EMPTY DESCRIPTION", empty_note, lambda x: '"%s" (%s)' % (x[0], x[1]))
    add("FREE vs PRICE CONFLICT", price_conflict, lambda x: '"%s": %s' % (x[0], x[1]))

    # Schema sanity warnings (not counted as problems, but surfaced).
    warnings = []
    if not saw_time:
        warnings.append("no 'time' field seen on any event; false-midnight check may be inactive.")
    if not saw_date:
        warnings.append("no start-date field seen; date-based checks may be inactive.")
    if not saw_town:
        warnings.append("no town/city field seen; duplicate check is weaker.")
    if not saw_note:
        warnings.append("no description/note field seen; empty-note and price checks may be inactive.")

    # Build report
    n = len(events)
    header = "whatsonnice health check | %s UTC | %d events" % (
        now.strftime("%Y-%m-%d %H:%M"), n)
    if not problems:
        body = header + "\nAll healthy."
        if warnings:
            body += "\n\nField notes (adjust the script if these look wrong):\n" \
                    + "\n".join("   - " + w for w in warnings)
        return ([body], 0)

    parts = [header, ""]
    for group, msg in problems:
        parts.append("[%s] %s" % (group, msg))
    if warnings:
        parts.append("")
        parts.append("Field notes:")
        parts.extend("   - " + w for w in warnings)
    return (["\n".join(parts)], 1)


def notify(report, healthy):
    topic = os.environ.get("NTFY_TOPIC")
    if not topic:
        return
    if healthy and os.environ.get("NTFY_ALWAYS") != "1":
        return
    title = "whatsonnice OK" if healthy else "whatsonnice: issues found"
    priority = "default" if healthy else "high"
    try:
        req = urllib.request.Request(
            "https://ntfy.sh/%s" % topic,
            data=report.encode("utf-8"),
            headers={"Title": title, "Priority": priority,
                     "Tags": "white_check_mark" if healthy else "warning"},
        )
        urllib.request.urlopen(req, timeout=30).read()
    except Exception as e:
        print("ntfy push failed: %s" % e, file=sys.stderr)


def main():
    reports, code = run()
    report = "\n\n".join(reports)
    print(report)
    notify(report, healthy=(code == 0))
    sys.exit(code)


if __name__ == "__main__":
    main()
