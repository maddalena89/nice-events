"""The source that owns a row may correct its own url (a dead nice.fr permalink
it later learns to replace), but a different source can never override the url a
visitor might already have clicked.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from niceevents import db
from niceevents.models import Event

DAY = date.today() + timedelta(days=10)


@pytest.fixture()
def conn(tmp_path):
    with db.connect(tmp_path / "t.db") as c:
        yield c


def _ev(source, url):
    return Event(title="Madagascar", start=DAY, town="Nice", venue="Cinema",
                 category="concert", source=source, url=url)


def test_owning_source_corrects_its_own_dead_url(conn):
    db.upsert(conn, [_ev("nice_fr", "https://www.nice.fr/agenda/madagascar/")])
    db.upsert(conn, [_ev("nice_fr", "https://www.nice.fr/mon-ete-cinema/")])
    assert conn.execute("SELECT url FROM events").fetchone()["url"] == \
        "https://www.nice.fr/mon-ete-cinema/"


def test_other_source_cannot_override_the_stored_url(conn):
    db.upsert(conn, [_ev("nice_fr", "https://www.nice.fr/agenda/madagascar/")])
    db.upsert(conn, [_ev("openagenda", "https://openagenda.example/madagascar")])
    assert conn.execute("SELECT url FROM events").fetchone()["url"] == \
        "https://www.nice.fr/agenda/madagascar/"
