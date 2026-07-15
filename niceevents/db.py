"""SQLite store with fingerprint dedup.

Two things matter here:

1. `first_seen` — never overwritten. This is what a "new since last week" email
   digest reads later, so it must stay honest.
2. Merge-on-conflict — when two sources describe the same event, we keep the
   richest field from each rather than letting whoever ran last win.
"""
from __future__ import annotations

import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Iterable, Iterator, Optional

from .models import Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    fingerprint  TEXT PRIMARY KEY,
    title        TEXT NOT NULL,
    start        TEXT NOT NULL,
    end          TEXT,
    time         TEXT,
    town         TEXT NOT NULL,
    venue        TEXT,
    category     TEXT NOT NULL,
    url          TEXT,
    note         TEXT,
    price        TEXT,
    free         INTEGER DEFAULT 0,
    image        TEXT,
    outdoor      INTEGER DEFAULT 0,
    source       TEXT NOT NULL,
    sources      TEXT,               -- comma-joined, when several agree
    submitted_by TEXT,
    approved     INTEGER DEFAULT 1,
    first_seen   TEXT NOT NULL,      -- never updated; drives the email digest
    last_seen    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_start    ON events(start);
CREATE INDEX IF NOT EXISTS idx_town     ON events(town);
CREATE INDEX IF NOT EXISTS idx_category ON events(category);
CREATE INDEX IF NOT EXISTS idx_first    ON events(first_seen);

CREATE TABLE IF NOT EXISTS runs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    scraper    TEXT NOT NULL,
    started_at TEXT NOT NULL,
    ok         INTEGER NOT NULL,
    found      INTEGER DEFAULT 0,
    added      INTEGER DEFAULT 0,
    error      TEXT
);
"""

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "events.db"


@contextmanager
def connect(path: Optional[Path] = None) -> Iterator[sqlite3.Connection]:
    p = Path(path or DB_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def _richer(new: Optional[str], old: Optional[str]) -> Optional[str]:
    """Prefer the more informative value; never replace something with nothing.

    Length is a fine proxy for venues and notes, where more detail genuinely
    helps. Do NOT use it for titles — see _better_title.
    """
    if not new:
        return old
    if not old:
        return new
    return new if len(str(new)) > len(str(old)) else old


def _better_title(new: str, old: str) -> str:
    """Pick the more readable of two titles for the same event.

    Longer is *wrong* here: "BROCANTE DU COURS SALEYA (Gratuit)" beats
    "Brocante du Cours Saleya" on length while being clearly worse. Score on
    shoutiness and badge noise instead, and keep the incumbent on a tie so
    titles don't churn between runs.
    """
    def penalty(t: str) -> int:
        letters = [c for c in t if c.isalpha()]
        upper_ratio = sum(c.isupper() for c in letters) / max(len(letters), 1)
        score = 0
        if upper_ratio > 0.7:            # SHOUTING
            score += 10
        if re.search(r"\((?:gratuit|free|new|nouveau)\)", t, re.I):
            score += 5                   # badge smuggled into the title
        if re.search(r"\s{2,}|\|\s*$|^\s*-", t):
            score += 2                   # scraping debris
        return score

    return new if penalty(new) < penalty(old) else old


def upsert(conn: sqlite3.Connection, events: Iterable[Event]) -> tuple[int, int]:
    """Insert or merge. Returns (added, merged)."""
    now = datetime.utcnow().isoformat(timespec="seconds")
    added = merged = 0

    for ev in events:
        row = conn.execute(
            "SELECT * FROM events WHERE fingerprint = ?", (ev.fingerprint,)
        ).fetchone()

        if row is None:
            conn.execute(
                """INSERT INTO events
                   (fingerprint,title,start,end,time,town,venue,category,url,note,price,
                    free,image,outdoor,source,sources,submitted_by,approved,first_seen,last_seen)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (ev.fingerprint, ev.title, ev.start.isoformat(),
                 ev.end.isoformat() if ev.end else None, ev.time, ev.town, ev.venue,
                 ev.category, ev.url, ev.note, ev.price, int(ev.free), ev.image,
                 int(ev.outdoor), ev.source, ev.source, ev.submitted_by,
                 int(ev.approved), now, now),
            )
            added += 1
            continue

        # Merge: keep the best of both, and remember every source that saw it.
        srcs = set((row["sources"] or row["source"] or "").split(","))
        srcs.discard("")
        srcs.add(ev.source)

        conn.execute(
            """UPDATE events SET
                 title=?, end=?, time=?, venue=?, url=?, note=?, price=?,
                 free=?, image=?, outdoor=?, sources=?, last_seen=?
               WHERE fingerprint=?""",
            (
                _better_title(ev.title, row["title"]),
                ev.end.isoformat() if ev.end else row["end"],
                ev.time or row["time"],
                _richer(ev.venue, row["venue"]),
                row["url"] or ev.url,              # first url wins: it's the one people clicked
                _richer(ev.note, row["note"]),
                ev.price or row["price"],
                int(ev.free or row["free"]),
                ev.image or row["image"],
                int(ev.outdoor or row["outdoor"]),
                ",".join(sorted(srcs)),
                now,
                ev.fingerprint,
            ),
        )
        merged += 1

    return added, merged


def log_run(conn, scraper: str, ok: bool, found: int = 0,
            added: int = 0, error: Optional[str] = None) -> None:
    conn.execute(
        "INSERT INTO runs (scraper, started_at, ok, found, added, error) VALUES (?,?,?,?,?,?)",
        (scraper, datetime.utcnow().isoformat(timespec="seconds"), int(ok), found, added, error),
    )


def prune_past(conn, keep_days: int = 2) -> int:
    """Drop events that finished more than keep_days ago."""
    cutoff = (date.today() - timedelta(days=keep_days)).isoformat()
    cur = conn.execute(
        "DELETE FROM events WHERE COALESCE(end, start) < ? AND submitted_by IS NULL", (cutoff,)
    )
    return cur.rowcount


def upcoming(conn, days: Optional[int] = None, include_pending: bool = False) -> list[sqlite3.Row]:
    today = date.today().isoformat()
    sql = "SELECT * FROM events WHERE COALESCE(end, start) >= ?"
    args: list = [today]
    if days:
        sql += " AND start <= ?"
        args.append((date.today() + timedelta(days=days)).isoformat())
    if not include_pending:
        sql += " AND approved = 1"
    sql += " ORDER BY start, town, title"
    return conn.execute(sql, args).fetchall()


def new_since(conn, since_iso: str) -> list[sqlite3.Row]:
    """Events first seen after `since_iso` — the email digest query."""
    return conn.execute(
        """SELECT * FROM events
           WHERE first_seen > ? AND COALESCE(end, start) >= ? AND approved = 1
           ORDER BY start, town""",
        (since_iso, date.today().isoformat()),
    ).fetchall()


def stats(conn) -> dict:
    total = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE COALESCE(end,start) >= ? AND approved=1",
        (date.today().isoformat(),),
    ).fetchone()["c"]
    by_cat = {
        r["category"]: r["c"]
        for r in conn.execute(
            """SELECT category, COUNT(*) c FROM events
               WHERE COALESCE(end,start) >= ? AND approved=1
               GROUP BY category ORDER BY c DESC""",
            (date.today().isoformat(),),
        )
    }
    towns = conn.execute(
        "SELECT COUNT(DISTINCT town) c FROM events WHERE COALESCE(end,start) >= ? AND approved=1",
        (date.today().isoformat(),),
    ).fetchone()["c"]
    pending = conn.execute(
        "SELECT COUNT(*) c FROM events WHERE approved = 0"
    ).fetchone()["c"]
    return {"total": total, "by_category": by_cat, "towns": towns, "pending": pending}
