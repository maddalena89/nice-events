"""The weekly email.

Weighted heavily towards "does it refuse when it should". Everything else in
this project can be re-run after a mistake; a bad send cannot be recalled, and
mail nobody can unsubscribe from is the one failure here with real legal teeth.
So the refusals are tested harder than the happy path.
"""
from datetime import date

import pytest

from niceevents import digest

SITE = "https://whatsonnice.com"


def _ev(**kw):
    base = {"title": "A milonga", "start": "2026-08-09", "time": "21:00",
            "town": "Nice", "venue": "Le Petit Bal", "free": False}
    base.update(kw)
    return base


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No test may accidentally pick up real credentials from the environment."""
    for k in ("SUPABASE_URL", "SUPABASE_SERVICE_KEY", "RESEND_API_KEY",
              "UNSUBSCRIBE_URL", "FROM_EMAIL", "REPLY_TO_EMAIL", "SITE_URL"):
        monkeypatch.delenv(k, raising=False)


# --- refusals: the important half -----------------------------------------

def test_dry_run_is_the_default_and_sends_nothing():
    sent, failed = digest.send([_ev()], [{"email": "a@b.com", "token": "t"}])
    assert (sent, failed) == (0, 0)


def test_refuses_to_send_without_a_working_unsubscribe_url(monkeypatch):
    """The hard stop. Mail with a dead unsubscribe link is worse than no mail."""
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    sent, failed = digest.send([_ev()], [{"email": "a@b.com", "token": "t"}], dry_run=False)
    assert sent == 0 and failed == 1


def test_refuses_to_send_without_a_mail_provider(monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_URL", "https://x.fn/unsubscribe")
    sent, failed = digest.send([_ev()], [{"email": "a@b.com", "token": "t"}], dry_run=False)
    assert sent == 0 and failed == 1


def test_an_empty_digest_is_never_sent(monkeypatch):
    """'Here's what's new' with nothing new trains a list to ignore you."""
    monkeypatch.setenv("UNSUBSCRIBE_URL", "https://x.fn/unsubscribe")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    assert digest.send([], [{"email": "a@b.com", "token": "t"}], dry_run=False) == (0, 0)


def test_no_subscribers_is_not_an_error(monkeypatch):
    monkeypatch.setenv("UNSUBSCRIBE_URL", "https://x.fn/unsubscribe")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    assert digest.send([_ev()], [], dry_run=False) == (0, 0)


def test_an_absurdly_large_digest_stops_and_asks(monkeypatch):
    """A rebuilt database resets first_seen on every row and makes the whole
    catalogue look new — a dry run on the live data produced 2,346 'new' events
    for exactly that reason. Sending that is not recoverable."""
    monkeypatch.setenv("UNSUBSCRIBE_URL", "https://x.fn/unsubscribe")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    lots = [_ev(title=f"T{i}") for i in range(digest._SANITY_MAX + 1)]
    assert digest.send(lots, [{"email": "a@b.com", "token": "t"}], dry_run=False) == (0, 0)


def test_the_size_guard_can_be_overridden_deliberately(monkeypatch):
    """It has to be possible to say 'yes, really' — just not by accident."""
    posted = []

    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, **kw):
            posted.append(kw["json"]["to"])
            class R: status_code = 200
            return R()

    monkeypatch.setenv("UNSUBSCRIBE_URL", "https://x.fn/unsubscribe")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    monkeypatch.setattr(digest.httpx, "Client", lambda **kw: FakeClient())
    monkeypatch.setattr(digest.time, "sleep", lambda s: None)

    lots = [_ev(title=f"T{i}") for i in range(digest._SANITY_MAX + 1)]
    sent, failed = digest.send(lots, [{"email": "a@b.com", "token": "tok"}],
                               dry_run=False, force=True)
    assert (sent, failed) == (1, 0)
    assert posted == [["a@b.com"]]


def test_each_recipient_gets_their_own_unsubscribe_link(monkeypatch):
    """The reason this sends one email per person instead of one BCC: a shared
    link means one person leaving takes the whole list with them."""
    payloads = []

    class FakeClient:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def post(self, url, **kw):
            payloads.append(kw["json"])
            class R: status_code = 200
            return R()

    monkeypatch.setenv("UNSUBSCRIBE_URL", "https://x.fn/unsubscribe")
    monkeypatch.setenv("RESEND_API_KEY", "re_fake")
    monkeypatch.setattr(digest.httpx, "Client", lambda **kw: FakeClient())
    monkeypatch.setattr(digest.time, "sleep", lambda s: None)

    digest.send([_ev()],
                [{"email": "a@b.com", "token": "tok-a"},
                 {"email": "c@d.com", "token": "tok-c"}], dry_run=False)

    assert len(payloads) == 2
    assert "tok-a" in payloads[0]["html"] and "tok-c" in payloads[1]["html"]
    assert "tok-c" not in payloads[0]["html"]
    # No placeholder may survive into a real send.
    for p in payloads:
        assert digest._UNSUB not in p["html"] and digest._UNSUB not in p["text"]
    # And the headers behind Gmail's own unsubscribe button are present.
    assert payloads[0]["headers"]["List-Unsubscribe"] == "<https://x.fn/unsubscribe?token=tok-a>"
    assert payloads[0]["headers"]["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_missing_supabase_config_yields_no_recipients_rather_than_raising():
    assert digest.recipients() == []


# --- the message itself ----------------------------------------------------

def test_both_parts_carry_an_unsubscribe_placeholder():
    """Substituted per recipient. If the placeholder is missing from either part,
    that reader gets mail with no way out."""
    _, html, text = digest.render([_ev()], SITE, when=date(2026, 8, 6))
    assert digest._UNSUB in html
    assert digest._UNSUB in text


def test_there_is_always_a_plain_text_part():
    """Some people read mail as text, and an HTML-only message is markedly more
    likely to be filtered as spam."""
    _, _, text = digest.render([_ev()], SITE)
    assert "A milonga" in text and "Le Petit Bal" in text


def test_subject_counts_correctly_and_handles_the_singular():
    s1, _, _ = digest.render([_ev()], SITE)
    s3, _, _ = digest.render([_ev(), _ev(title="B"), _ev(title="C")], SITE)
    assert s1 == "One new thing on in Nice"
    assert s3 == "3 new things on in Nice"


def test_titles_are_escaped_not_injected():
    _, html, _ = digest.render([_ev(title='Bal <script>alert(1)</script>')], SITE)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_long_lists_are_truncated_with_an_honest_count():
    events = [_ev(title=f"Thing {i}") for i in range(digest._MAX_IN_EMAIL + 7)]
    subject, html, text = digest.render(events, SITE)
    # The subject still tells the truth about the total…
    assert str(len(events)) in subject
    # …while the body says how many it didn't show.
    assert "7 more" in html and "7 more" in text


def test_no_tracking_pixel_and_no_remote_images():
    """The privacy notice promises no tracking. This is that promise, asserted."""
    _, html, _ = digest.render([_ev()], SITE)
    assert "<img" not in html.lower()


def test_events_are_grouped_and_ordered_by_date():
    events = [_ev(title="Later", start="2026-08-20"),
              _ev(title="Sooner", start="2026-08-09")]
    _, _, text = digest.render(sorted(events, key=lambda e: e["start"]), SITE)
    assert text.index("Sooner") < text.index("Later")


def test_free_events_are_flagged():
    _, html, text = digest.render([_ev(free=True)], SITE)
    assert "Free" in html and "free" in text


# --- recipients ------------------------------------------------------------

def test_duplicate_addresses_collapse(monkeypatch):
    """Someone who said hi twice must not get the email twice — that breaks the
    'one email a week' promise made on the form."""
    class FakeResponse:
        status_code = 200
        @staticmethod
        def json():
            return [
                {"email": "A@Example.com", "unsubscribe_token": "t1"},
                {"email": "a@example.com", "unsubscribe_token": "t2"},
                {"email": "b@example.com", "unsubscribe_token": "t3"},
                {"email": "c@example.com", "unsubscribe_token": None},   # unusable
            ]

    monkeypatch.setenv("SUPABASE_URL", "https://p.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc")
    monkeypatch.setattr(digest.httpx, "get", lambda *a, **k: FakeResponse())

    out = digest.recipients()
    assert [p["email"] for p in out] == ["a@example.com", "b@example.com"]


def test_a_pasted_rest_suffix_on_the_url_is_tolerated(monkeypatch):
    """The same misconfiguration site.py already guards against: pasting the full
    REST endpoint as SUPABASE_URL, which would produce /rest/v1/rest/v1/…"""
    seen = {}

    class FakeResponse:
        status_code = 200
        @staticmethod
        def json():
            return []

    def fake_get(url, **kw):
        seen["url"] = url
        return FakeResponse()

    monkeypatch.setenv("SUPABASE_URL", "https://p.supabase.co/rest/v1")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "svc")
    monkeypatch.setattr(digest.httpx, "get", fake_get)

    digest.recipients()
    assert seen["url"].count("/rest/v1") == 1
