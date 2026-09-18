"""Community submissions: registration, mapping, and the security boundary.

The first test here exists because the scraper was written, worked, and was
never imported in scrapers/__init__.py — so REGISTRY didn't have it and it
silently never ran. Nothing failed. There was simply no such source, forever.
A registry that's a hand-maintained list of imports needs a test that reads the
directory instead.
"""
from __future__ import annotations

import ast
import importlib
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from niceevents.scrapers import REGISTRY
from niceevents.scrapers.submissions import Submissions

_SCRAPERS_DIR = Path(__file__).resolve().parent.parent / "niceevents" / "scrapers"

#: Scraper modules deliberately left out of __init__.py, with the reason. Kept
#: on disk rather than deleted — see the comment at the matching commented-out
#: import. Adding a name here is the documented way to retire a source; the test
#: below checks each entry is still true, so a stale one fails rather than rots.
RETIRED = {
    "tango": "retired 2026-08-06: tango-argentin.fr does not publish "
             "cancellations, so tango now comes from harvest",
}


def _classes_registered_by(path: Path) -> bool:
    """Does this module define a @register-ed scraper? Read, don't import.

    Importing to find out is what makes this whole area unreliable: @register
    fires on import and the result is process-global, so an import anywhere in
    the test session changes the answer.
    """
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.ClassDef):
            continue
        for dec in node.decorator_list:
            name = dec.id if isinstance(dec, ast.Name) else getattr(dec, "attr", None)
            if name == "register":
                return True
    return False


def _scraper_modules_on_disk() -> set[str]:
    """Modules in scrapers/ that define a source.

    Derived from @register rather than a hand-written skip list, so shared
    helpers (base.py, gcal.py) drop out on their own and a genuinely new
    scraper is required the moment it lands.
    """
    return {
        p.stem for p in sorted(_SCRAPERS_DIR.glob("*.py"))
        if not p.name.startswith("_") and _classes_registered_by(p)
    }


def _modules_imported_by_init() -> set[str]:
    """Sibling modules `__init__.py` imports, read from its source.

    Deliberately NOT `hasattr(pkg, name)`: a submodule imported anywhere in the
    session — by another test, or transitively by a sibling scraper — is set as
    an attribute on the package, so hasattr answers "did anything import this",
    not "does production import this". Reading the file asks the real question.
    """
    tree = ast.parse((_SCRAPERS_DIR / "__init__.py").read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1:
            if node.module:                      # from .base import REGISTRY
                names.add(node.module.split(".")[0])
            else:                                # from . import brocabrac
                names.update(alias.name for alias in node.names)
    return names


def test_every_scraper_module_is_imported_by_the_package():
    """Every scraper module in scrapers/ must be imported by __init__.py.

    Catches the "wrote it, forgot to import it" failure, which is invisible at
    runtime — an unregistered source looks exactly like a source that found no
    events.

    Note this checks *imported*, not "module name is a REGISTRY key": the two
    differ on purpose (tango.py registers as `tango_argentin`). Importing is the
    thing that runs @register, so importing is the thing to assert.
    """
    missing = _scraper_modules_on_disk() - _modules_imported_by_init() - set(RETIRED)
    assert not missing, (
        f"scraper modules never imported in __init__.py: {sorted(missing)}. "
        "Import them there, or add them to RETIRED with a reason if the "
        "omission is deliberate.")


def test_the_retired_list_still_describes_the_code():
    """An allowlist nobody checks is an allowlist that stops being true.

    Every RETIRED entry must still name a file that exists and is still left
    out of __init__.py — so re-registering a source, or deleting its module,
    fails here instead of quietly leaving a permanent hole in the test above.
    """
    for name, reason in RETIRED.items():
        assert (_SCRAPERS_DIR / f"{name}.py").exists(), (
            f"RETIRED lists {name!r} ({reason}) but {name}.py is gone — "
            "drop the entry.")
        assert name not in _modules_imported_by_init(), (
            f"RETIRED lists {name!r} ({reason}) but __init__.py imports it "
            "again — remove the entry so the source is checked like any other.")

    # Retirement means unregistered in production, which test_reconcile.py's
    # test_only_opt_in_scrapers_reconcile asserts in a clean interpreter (the
    # only place a REGISTRY assertion is trustworthy).


def test_submissions_is_registered():
    assert "submissions" in REGISTRY


def _row(**kw):
    row = {
        "id": "00000000-0000-0000-0000-000000000001",
        "title": "Milonga at the port",
        "start_date": "2099-01-01",
        "end_date": None,
        "town": "nice",
        "venue": "Quai Lunel",
        "category": "danse",
        "url": "https://example.org/milonga",
        "note": None,
    }
    row.update(kw)
    return row


def test_maps_a_row_to_an_event():
    ev = Submissions()._to_event(_row(), date(2026, 7, 15))
    assert ev is not None
    assert ev.title == "Milonga at the port"
    assert ev.town == "Nice"                 # canon_town applied
    assert ev.category == "danse"
    assert ev.source == "submissions"
    assert ev.submitted_by == "community"
    assert ev.approved is True


def test_unknown_category_falls_back_rather_than_dropping_the_event():
    """A taxonomy mismatch must not silently delete someone's event."""
    ev = Submissions()._to_event(_row(category="not_a_real_category"), date(2026, 7, 15))
    assert ev is not None
    assert ev.category == "autre"


def test_finished_events_are_dropped_but_running_ones_are_kept():
    today = date(2026, 7, 15)
    over = _row(start_date="2026-07-01", end_date="2026-07-10")
    assert Submissions()._to_event(over, today) is None

    # Started in the past, still running — an exhibition, not a mistake.
    running = _row(start_date="2026-07-01", end_date="2026-07-30")
    assert Submissions()._to_event(running, today) is not None


def test_row_with_no_usable_date_is_skipped_not_crashed():
    assert Submissions()._to_event(_row(start_date=""), date(2026, 7, 15)) is None
    assert Submissions()._to_event(_row(title="  "), date(2026, 7, 15)) is None


def test_yields_nothing_without_credentials(monkeypatch):
    """A fresh clone with no Supabase configured must build, not explode."""
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_KEY", raising=False)
    assert list(Submissions().fetch()) == []


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.text = payload, status, str(payload)

    def json(self):
        return self._payload


class _Client:
    """Stands in for HttpScraper.client, recording what got asked for."""

    def __init__(self, *pages):
        self._pages, self.gets = list(pages), []

    def get(self, url, headers=None):
        self.gets.append(url)
        return self._pages.pop(0) if self._pages else _Resp([])


def _wired(monkeypatch, key, *pages):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", key)
    s = Submissions()
    client = _Client(*pages)
    monkeypatch.setattr(type(s), "client", property(lambda self: client))
    return s, client


# A legacy anon JWT and a legacy service_role JWT — payload only, unsigned. The
# signature is never checked (see _key_privilege), so a placeholder is enough.
def _jwt(role):
    import base64 as b64
    import json as js
    body = b64.urlsafe_b64encode(js.dumps({"role": role}).encode()).rstrip(b"=").decode()
    return f"header.{body}.signature"


def test_empty_table_with_a_good_key_is_empty_not_broken(monkeypatch):
    """The regression this file existed without.

    A privileged key seeing zero approved rows means zero approved rows. The old
    probe called that a mis-set key, so `submissions` reported `failed` every day
    on a site whose form simply hadn't been used yet.
    """
    for key in ("sb_secret_abc123", _jwt("service_role")):
        s, client = _wired(monkeypatch, key, _Resp([]))
        assert list(s.fetch()) == []
        # It must not even bother probing — the key already answered the question.
        assert len(client.gets) == 1


def test_empty_result_with_a_weak_key_still_raises_loudly(monkeypatch):
    """The failure the probe was built to catch must keep being caught."""
    for key in ("sb_publishable_abc123", _jwt("anon")):
        s, _ = _wired(monkeypatch, key, _Resp([]))
        with pytest.raises(RuntimeError, match="anon / publishable"):
            list(s.fetch())


def test_unidentifiable_key_reports_both_possibilities(monkeypatch):
    """No guessing when the key's shape is unknown — say what it could be."""
    s, _ = _wired(monkeypatch, "some-opaque-token", _Resp([]), _Resp([]))
    with pytest.raises(RuntimeError, match="could not be identified"):
        list(s.fetch())


def test_unidentifiable_key_is_fine_when_the_table_has_rows(monkeypatch):
    """Rows exist but none are approved — a real queue state, not an error."""
    s, _ = _wired(monkeypatch, "some-opaque-token", _Resp([]), _Resp([{"id": "x"}]))
    assert list(s.fetch()) == []


def test_email_is_never_requested_from_the_database():
    """The submitter's email must not be loadable into a public events feed.

    Enforced by not selecting the column at all — the surest way not to leak a
    value is never to hold it.
    """
    from niceevents.scrapers import submissions as mod
    assert "email" not in mod._COLS.split(",")


def test_site_module_cannot_see_the_service_key(monkeypatch):
    """site.py renders a PUBLIC html file. The RLS-bypassing key must not be
    reachable from it, even by accident."""
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "super-secret-do-not-ship")
    import niceevents.site as site
    importlib.reload(site)
    source = open(site.__file__, encoding="utf-8").read()
    assert "SERVICE_KEY" not in source
    for name in dir(site):
        val = getattr(site, name)
        if isinstance(val, str):
            assert "super-secret-do-not-ship" not in val


# --- recording which event a submission became (for the "it's live" email) ---

class _PatchResp:
    def __init__(self, status):
        self.status_code = status


class _PatchRecorder:
    """Stands in for httpx: records every PATCH, answers with scripted statuses."""
    def __init__(self, statuses=None):
        self.calls, self.statuses = [], list(statuses or [])

    def patch(self, url, headers=None, json=None):
        self.calls.append((url, json))
        return _PatchResp(self.statuses.pop(0) if self.statuses else 204)


def _scraper_with(client):
    from niceevents.scrapers.submissions import Submissions
    s = Submissions.__new__(Submissions)
    s._client = client
    return s


def test_each_published_row_records_its_own_event():
    c = _PatchRecorder()
    _scraper_with(c)._mark_published("https://x.supabase.co", {},
                                     [("id-1", "fpA"), ("id-2", "fpB")])
    assert [j for _, j in c.calls] == [
        {"published": True, "live_fingerprint": "fpA"},
        {"published": True, "live_fingerprint": "fpB"},
    ]


def test_only_unpublished_rows_are_flipped_so_the_email_goes_once():
    c = _PatchRecorder()
    _scraper_with(c)._mark_published("https://x.supabase.co", {}, [("id-1", "fpA")])
    assert "published=eq.false" in c.calls[0][0]
    assert "id=eq.id-1" in c.calls[0][0]


def test_before_the_new_column_exists_rows_are_still_flagged():
    """Until migration 009 is applied, PostgREST rejects the unknown column. The
    row must still be marked published, as it always was."""
    c = _PatchRecorder(statuses=[400, 204])
    _scraper_with(c)._mark_published("https://x.supabase.co", {}, [("id-1", "fpA")])
    assert [j for _, j in c.calls] == [
        {"published": True, "live_fingerprint": "fpA"},
        {"published": True},
    ]


def test_a_network_failure_never_raises():
    class Boom:
        def patch(self, *a, **k):
            raise RuntimeError("network down")
    _scraper_with(Boom())._mark_published("https://x.supabase.co", {}, [("id-1", "fpA")])
