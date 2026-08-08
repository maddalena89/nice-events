"""The weekly email — building it, and sending it.

Shape of the thing: one email per recipient, not one BCC to everybody. That is
slower and it is the only way that works, because each person's unsubscribe link
carries their own token; a shared email means a shared link, and one person
leaving would take the whole list with them.

Three safety rails, all deliberate:

  * It will not send unless you pass --send. The default is a dry run that
    prints exactly what would go out and to how many people. An email is the one
    thing in this project you cannot take back.
  * It will not send an empty digest. A "here's what's new" with nothing new is
    how a list trains itself to ignore you.
  * Every send carries a working unsubscribe link AND the List-Unsubscribe
    headers Gmail and Outlook use for their built-in one-click button. If the
    unsubscribe endpoint is not configured, this refuses to send at all rather
    than posting mail nobody can escape.

AUTH: SUPABASE_SERVICE_KEY reads the subscriber list. It bypasses Row Level
Security and is the only key that can see those addresses, so — exactly as with
submissions.py — it lives in a GitHub secret, is read only here in CI, and must
never reach site.py or the template.
"""
from __future__ import annotations

import html
import logging
import os
import re
import sqlite3
import time
from datetime import date, datetime, timedelta
from typing import Iterable, Optional

import httpx

log = logging.getLogger(__name__)

_REST_TAIL = re.compile(r"/rest(/v1)?/?$")

#: Resend's free tier rate-limits to a couple of requests a second. At a few
#: hundred subscribers this pause costs a minute and avoids being throttled
#: halfway through a send, which would leave half the list emailed and no clean
#: way to know which half.
_SEND_PAUSE = 0.6

#: The email is a taste, not the whole site. Past roughly this many the message
#: stops being readable and starts being a wall, and the point of the last line
#: is to send people to the page anyway.
_MAX_IN_EMAIL = 24

_MONTHS = ["", "January", "February", "March", "April", "May", "June",
           "July", "August", "September", "October", "November", "December"]


def _env(name: str, default: str = "") -> str:
    return (os.environ.get(name) or default).strip()


def _site_url() -> str:
    return _env("SITE_URL", "https://whatsonnice.com").rstrip("/")


def _pretty_day(iso: str) -> str:
    d = date.fromisoformat(iso)
    return f"{d.day} {_MONTHS[d.month]}"


def _rows_to_events(rows: Iterable[sqlite3.Row]) -> list[dict]:
    """Only the fields the email shows. Notably nothing about the submitter."""
    out = []
    for r in rows:
        d = dict(r)
        out.append({
            "title": d.get("title") or "",
            "start": d.get("start") or "",
            "time": (d.get("time") or "").strip() or None,
            "town": d.get("town") or "",
            "venue": (d.get("venue") or "").strip() or None,
            "free": bool(d.get("free")),
        })
    out.sort(key=lambda e: (e["start"], e["town"], e["title"]))
    return out


# --------------------------------------------------------------------------
# Rendering.
#
# Every recipient's mail is identical apart from one link, so the body is built
# once with a placeholder and the token substituted per person. Building the
# whole thing per recipient would be several hundred string joins for nothing.
# --------------------------------------------------------------------------

_UNSUB = "{{UNSUB}}"


def render(events: list[dict], site: str, when: Optional[date] = None) -> tuple[str, str, str]:
    """(subject, html, plain text). Unsubscribe URL left as a placeholder."""
    when = when or date.today()
    shown, extra = events[:_MAX_IN_EMAIL], max(0, len(events) - _MAX_IN_EMAIL)
    subject = (f"{len(events)} new things on in Nice"
               if len(events) != 1 else "One new thing on in Nice")

    by_day: dict[str, list[dict]] = {}
    for e in shown:
        by_day.setdefault(e["start"], []).append(e)

    # --- plain text. Not an afterthought: some people read mail this way, and
    # a message with no text part is markedly likelier to be filtered as spam.
    tl = [f"What's new on in Nice — {when.day} {_MONTHS[when.month]} {when.year}", ""]
    for day, evs in by_day.items():
        tl.append(_pretty_day(day).upper())
        for e in evs:
            bits = [e["title"]]
            if e["venue"]:
                bits.append(e["venue"])
            bits.append(e["town"])
            if e["time"]:
                bits.append(e["time"])
            if e["free"]:
                bits.append("free")
            tl.append("  - " + " · ".join(bits))
        tl.append("")
    if extra:
        tl.append(f"...and {extra} more on the site.")
        tl.append("")
    tl += [f"Everything, always: {site}", "",
           "You're getting this because you asked for it on the site.",
           f"Unsubscribe in one click: {_UNSUB}"]
    text = "\n".join(tl)

    # --- html. Inline styles only, no external CSS, no images, no tracking
    # pixel. Mail clients strip <style> blocks, and a tracking pixel would make
    # a nonsense of the privacy notice.
    def esc(s: str) -> str:
        return html.escape(s or "")

    parts = [
        '<div style="background:#f4f2ed;padding:28px 16px;'
        'font-family:Helvetica Neue,Helvetica,Arial,sans-serif;color:#0e0e0e">',
        '<div style="max-width:560px;margin:0 auto">',
        '<div style="font-size:11px;letter-spacing:.18em;text-transform:uppercase;'
        f'color:#7d7970;border-bottom:1px solid #0e0e0e;padding-bottom:9px">'
        f'What&rsquo;s on in Nice · {when.day} {_MONTHS[when.month]} {when.year}</div>',
        '<h1 style="font-size:34px;line-height:1;letter-spacing:-.04em;font-weight:800;'
        'text-transform:uppercase;margin:22px 0 6px">New this week</h1>',
        f'<p style="margin:0 0 24px;color:#3a382f;font-size:15px">'
        f'{len(events)} thing{"s" if len(events) != 1 else ""} turned up since last time.</p>',
    ]
    for day, evs in by_day.items():
        parts.append(
            '<div style="font-size:11px;letter-spacing:.14em;text-transform:uppercase;'
            'font-weight:700;color:#1f3bff;margin:22px 0 6px">'
            f'{esc(_pretty_day(day))}</div>'
        )
        for e in evs:
            meta = " · ".join(filter(None, [
                esc(e["venue"]) if e["venue"] else None,
                esc(e["town"]),
                esc(e["time"]) if e["time"] else None,
                "Free" if e["free"] else None,
            ]))
            parts.append(
                '<div style="padding:9px 0;border-bottom:1px solid #d8d4cb">'
                f'<div style="font-size:16px;font-weight:600">{esc(e["title"])}</div>'
                f'<div style="font-size:13px;color:#7d7970;margin-top:2px">{meta}</div>'
                '</div>'
            )
    if extra:
        parts.append(
            f'<p style="margin:18px 0 0;color:#7d7970;font-size:14px">…and {extra} more.</p>'
        )
    parts += [
        f'<p style="margin:26px 0 0"><a href="{site}?utm_source=digest" '
        'style="display:inline-block;background:#1f3bff;color:#fff;text-decoration:none;'
        'font-weight:700;font-size:15px;padding:12px 20px;border-radius:6px">'
        'See everything that&rsquo;s on</a></p>',
        '<p style="margin:34px 0 0;padding-top:14px;border-top:1px solid #d8d4cb;'
        'font-size:12px;color:#7d7970;line-height:1.6">'
        'You&rsquo;re getting this because you left your address on the site and asked '
        'for it. One email a week, never shared with anyone.<br>'
        f'<a href="{_UNSUB}" style="color:#7d7970">Unsubscribe in one click</a> · '
        f'<a href="{site}/privacy.html" style="color:#7d7970">Privacy</a></p>',
        "</div></div>",
    ]
    return subject, "".join(parts), text


# --------------------------------------------------------------------------
# Recipients and sending
# --------------------------------------------------------------------------

def recipients(timeout: float = 20.0) -> list[dict]:
    """Everyone who said yes and hasn't left. Reads the newsletter_recipients
    view from migration 006, which already excludes unsubscribed rows."""
    base = _REST_TAIL.sub("", _env("SUPABASE_URL").rstrip("/"))
    key = _env("SUPABASE_SERVICE_KEY")
    if not base or not key:
        log.warning("SUPABASE_URL / SUPABASE_SERVICE_KEY not set — no recipients")
        return []
    r = httpx.get(
        f"{base}/rest/v1/newsletter_recipients?select=email,unsubscribe_token",
        headers={"apikey": key, "Authorization": f"Bearer {key}"},
        timeout=timeout,
    )
    if r.status_code != 200:
        log.error("could not read subscribers: %s %s", r.status_code, r.text[:200])
        return []
    seen, out = set(), []
    for row in r.json():
        email = (row.get("email") or "").strip().lower()
        # One person may have said hi twice. Emailing them twice is a small
        # betrayal of "one email a week", so collapse duplicates here.
        if email and email not in seen and row.get("unsubscribe_token"):
            seen.add(email)
            out.append({"email": email, "token": row["unsubscribe_token"]})
    return out


#: A digest this large is almost never real news. The usual cause is the events
#: database having been rebuilt or reseeded, which resets `first_seen` on every
#: row and makes the entire catalogue look brand new — a dry run on the live data
#: produced 2,346 "new" items for exactly that reason. Sending that would be one
#: unrecoverable mistake, so it stops and asks.
_SANITY_MAX = 200


def send(events: list[dict], people: list[dict], dry_run: bool = True,
         force: bool = False) -> tuple[int, int]:
    """Send the digest. Returns (sent, failed). Refuses rather than guesses."""
    site = _site_url()
    unsub_base = _env("UNSUBSCRIBE_URL")
    resend_key = _env("RESEND_API_KEY")
    sender = _env("FROM_EMAIL", "What's on in Nice <hello@whatsonnice.com>")
    reply_to = _env("REPLY_TO_EMAIL")

    if not events:
        log.info("nothing new — not sending. An empty digest teaches people to ignore you.")
        return 0, 0
    if not people:
        log.info("no subscribers — nothing to do.")
        return 0, 0

    subject, body_html, body_text = render(events, site)

    if dry_run:
        print(f"\n  DRY RUN — would send to {len(people)} {'person' if len(people)==1 else 'people'}")
        print(f"  Subject: {subject}\n")
        print("  " + "\n  ".join(body_text.splitlines()[:40]))
        print("\n  (pass --send to actually send)\n")
        return 0, 0

    # Hard stop. Mail nobody can unsubscribe from is the one failure here with
    # real consequences, so it is a refusal, not a warning.
    if not unsub_base:
        log.error("UNSUBSCRIBE_URL is not set — refusing to send. "
                  "Deploy the unsubscribe function first.")
        return 0, len(people)
    if not resend_key:
        log.error("RESEND_API_KEY is not set — cannot send.")
        return 0, len(people)
    if len(events) > _SANITY_MAX and not force:
        log.error(
            "%d 'new' events — that is more than a week of Nice produces. This "
            "usually means the database was rebuilt and every row looks newly "
            "seen. Check a dry run first; pass force=True if it really is right.",
            len(events),
        )
        return 0, 0

    sent = failed = 0
    with httpx.Client(timeout=30.0) as client:
        for p in people:
            link = f"{unsub_base}?token={p['token']}"
            payload = {
                "from": sender,
                "to": [p["email"]],
                "subject": subject,
                "html": body_html.replace(_UNSUB, link),
                "text": body_text.replace(_UNSUB, link),
                # The headers behind Gmail's and Outlook's own unsubscribe button.
                # Offering it there is what stops an irritated reader reaching for
                # "mark as spam" instead, which damages deliverability for everyone
                # still on the list.
                "headers": {
                    "List-Unsubscribe": f"<{link}>",
                    "List-Unsubscribe-Post": "List-Unsubscribe=One-Click",
                },
            }
            if reply_to:
                payload["reply_to"] = reply_to
            try:
                r = client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {resend_key}"},
                    json=payload,
                )
                if r.status_code < 300:
                    sent += 1
                else:
                    failed += 1
                    log.warning("send failed for one recipient: %s %s",
                                r.status_code, r.text[:160])
            except Exception as exc:                     # network, timeout, anything
                failed += 1
                log.warning("send errored for one recipient: %s", exc)
            time.sleep(_SEND_PAUSE)

    log.info("digest: %d sent, %d failed", sent, failed)
    return sent, failed


def collect(conn: sqlite3.Connection, days: int = 7, horizon: int = 60) -> list[dict]:
    """What's newly listed AND actually coming up.

    `db.new_since` answers "new to the database", which is not the same question.
    A run of it on the real data returned an exhibition that opened in February:
    perfectly valid, still on, and genuinely only just scraped — but listing it
    under "New this week" against a February date reads as a mistake, and the
    date headings in the email would open months in the past.

    So two extra filters. Nothing that has already started (it is not news), and
    nothing further out than the horizon (it is not yet useful). What is left is
    the honest answer to "what turned up this week that you might actually go to".
    """
    from . import db
    since = (datetime.utcnow() - timedelta(days=days)).isoformat(timespec="seconds")
    today = date.today()
    limit = today + timedelta(days=horizon)
    rows = [
        r for r in db.new_since(conn, since)
        if r["start"] and today <= date.fromisoformat(r["start"]) <= limit
    ]
    return _rows_to_events(rows)
