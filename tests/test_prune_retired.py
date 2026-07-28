"""Retired-source cleanup: rows from a removed scraper are dropped, but active
sources, merged rows, and human submissions survive."""
from __future__ import annotations

from datetime import date

from niceevents import db
from niceevents.models import Event


def _ev(title, source, submitted_by=None):
    return Event(title=title, start=date(2099, 8, 1), town="Villefranche-sur-Mer",
                 category="concert", source=source, submitted_by=submitted_by)


def test_prune_retired(tmp_path):
    with db.connect(tmp_path / "t.db") as conn:
        db.upsert(conn, [
            _ev("Live Act", "seed"),               # active source -> keep
            _ev("Ghost Act", "trinquette"),        # retired source -> drop
            _ev("Submitted Act", "trinquette", submitted_by="user@x"),  # human -> keep
        ])
        # A row seen by both a retired and an active source must survive.
        merged = _ev("Shared Act", "trinquette")
        db.upsert(conn, [merged])
        conn.execute("UPDATE events SET sources = ? WHERE fingerprint = ?",
                     ("seed,trinquette", merged.fingerprint))

        removed = db.prune_retired(conn, {"seed", "nice_fr"})
        titles = {r["title"] for r in conn.execute("SELECT title FROM events")}

    assert removed == 1
    assert "Ghost Act" not in titles
    assert titles == {"Live Act", "Submitted Act", "Shared Act"}
