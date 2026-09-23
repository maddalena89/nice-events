"""Community submissions — read back out of Supabase.

The other half of the add-event form. The form (in templates/index.html.jinja)
inserts into public.submissions with the anon key; this reads the rows Maddalena
has ticked `approved` in the Supabase Table Editor and feeds them into the same
pipeline as every scraped source, so they get the same dedup, merge and stats
treatment for free.

Moderation is a human ticking a box. There is no automatic approval and there
should not be: the form checks a URL is well-formed, which tells you nothing
about whether the event is real.

Auth: SUPABASE_SERVICE_KEY bypasses Row Level Security — it is the one key that
can read submitter emails and flip `approved`. It lives in a GitHub *secret* and
is only ever read here, in CI. It must never reach site.py or the template, both
of which get baked into a public HTML file.

If either env var is missing this yields nothing and says so once. That's the
right behaviour for a fresh clone with no Supabase set up — it must not be an
error, or every local build breaks.
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
from datetime import date
from typing import Iterator, Optional

import httpx

# Strip a trailing /rest or /rest/v1 that someone may have pasted onto
# SUPABASE_URL. Without this we'd build ".../rest/v1/rest/v1/submissions", which
# PostgREST rejects (the request comes back 401/404 and no submissions load).
_REST_TAIL = re.compile(r"/rest(/v1)?/?$")


def _key_privilege(key: str) -> str:
    """Is this key allowed to bypass RLS? 'privileged' | 'weak' | 'unknown'.

    Read from the key itself, because the alternative doesn't work: "RLS hid
    every row" and "the table is genuinely empty" both come back as HTTP 200 and
    an empty list, and no query can separate them. The key, though, says what it
    is on the tin, in both Supabase generations:

      * current — ``sb_secret_…`` (privileged) vs ``sb_publishable_…`` (weak)
      * legacy  — a JWT whose payload carries ``{"role": "service_role"|"anon"}``

    The JWT is decoded, never verified. That is deliberate: this is our own
    config being classified, not a token being trusted, and a signature check
    would need a secret we don't have. Nothing is authorised on the strength of
    what this returns — it only decides which error message is honest.
    """
    k = (key or "").strip()
    if k.startswith("sb_secret_"):
        return "privileged"
    if k.startswith("sb_publishable_"):
        return "weak"
    parts = k.split(".")
    if len(parts) == 3:                                  # shaped like a JWT
        try:
            pad = parts[1] + "=" * (-len(parts[1]) % 4)  # base64url needs padding
            role = json.loads(base64.urlsafe_b64decode(pad)).get("role")
        except Exception:
            return "unknown"
        if role == "service_role":
            return "privileged"
        if role:                                         # anon, authenticated, …
            return "weak"
    return "unknown"

from ..models import CATEGORIES, Event, canon_town, parse_date
from .base import HttpScraper, register

log = logging.getLogger(__name__)

# Only the columns we need. Notably NOT `email` — it's the submitter's private
# contact detail, it has no business in a public events feed, and the surest way
# to never leak it is to never load it.
_COLS = "id,title,start_date,end_date,time,town,venue,category,url,note"


@register
class Submissions(HttpScraper):
    name = "submissions"
    label = "Community submissions"
    delay = 0.0          # our own database; no politeness delay needed
    use_proxy = False    # Supabase is our backend — never route it through SCRAPER_PROXY

    def _cfg(self) -> tuple[Optional[str], Optional[str]]:
        url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
        url = _REST_TAIL.sub("", url)          # tolerate a pasted /rest/v1 suffix
        key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
        return (url or None), (key or None)

    def fetch(self) -> Iterator[Event]:
        base, key = self._cfg()
        if not base or not key:
            log.info("%s: SUPABASE_URL / SUPABASE_SERVICE_KEY not set — skipping", self.name)
            return

        # Supabase refuses the new sb_secret_ keys when the request looks like a
        # browser ("Forbidden use of secret API key in browser"). HttpScraper's
        # shared client sends a Chrome UA + text/html Accept to get past venue
        # blocks, which trips that guard — so present as a plain server client
        # here. Request headers override the client's for the same name in httpx.
        headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "User-Agent": "niceevents-submissions/1.0",
            "Accept": "application/json",
        }
        url = (f"{base}/rest/v1/submissions"
               f"?approved=eq.true&select={_COLS}&order=created_at.asc")

        # Call Supabase directly (use_proxy=False) and surface the real status.
        # A silent skip here is what hid a non-working SUPABASE_SERVICE_KEY for
        # weeks: the read came back "0 rows, no error" and nobody could tell a
        # bad key from an empty queue. Raise loudly instead — the run isolates a
        # failing source, and the message lands in sources.json's `error` field.
        try:
            r = self.client.get(url, headers=headers)
        except httpx.HTTPError as e:
            raise RuntimeError(f"{self.name}: request to Supabase failed: {e}") from e
        if r.status_code != 200:
            hint = (" — the key was rejected; SUPABASE_SERVICE_KEY must be the "
                    "service_role / sb_secret_ key" if r.status_code in (401, 403) else "")
            raise RuntimeError(
                f"{self.name}: Supabase HTTP {r.status_code} reading approved rows{hint}"
                f": {r.text[:120]}")
        try:
            rows = r.json()
        except Exception:
            raise RuntimeError(f"{self.name}: submissions response wasn't JSON: {r.text[:120]}")

        # An anon/publishable key authenticates fine (HTTP 200) but Row Level
        # Security then hides every row, so an empty result is ambiguous: no
        # approved events, or a key that can't see the table at all?
        #
        # The probe that used to live here — read one row of ANY kind, raise if
        # none came back — could not answer that, and was never going to: an
        # empty table returns exactly what a blindfolded key returns. So it
        # reported a broken key every single day for a site whose submissions
        # table was simply still empty, which is the ordinary state of a form
        # nobody has used yet. Ask the KEY what it is instead; that is knowable.
        if not rows:
            priv = _key_privilege(key)
            if priv == "weak":
                raise RuntimeError(
                    f"{self.name}: SUPABASE_SERVICE_KEY is an anon / publishable key, so "
                    f"Row Level Security hides every row. It must be the service_role / "
                    f"sb_secret_ key.")
            if priv == "unknown":
                # Unrecognised key shape, so fall back to the probe — but report
                # both things an empty table can mean instead of asserting one.
                probe = self.client.get(f"{base}/rest/v1/submissions?select=id&limit=1",
                                        headers=headers)
                if probe.status_code == 200 and not probe.json():
                    raise RuntimeError(
                        f"{self.name}: 0 rows visible and the key's type could not be "
                        f"identified — either SUPABASE_SERVICE_KEY is not the "
                        f"service_role / sb_secret_ key, or the submissions table is "
                        f"empty. Open the table in Supabase to tell which.")
            # Privileged key, nothing approved: an empty queue, not a fault. This
            # must stay a clean `empty` in sources.json — a source that cries
            # `failed` every day is a source nobody reads any more.
            log.info("%s: no approved submissions waiting", self.name)
            return

        today = date.today()
        published: list[tuple[str, str]] = []
        over = 0

        for row in rows:
            ev = self._to_event(row, today)
            if ev is None:
                over += 1
                continue
            published.append((row["id"], ev.fingerprint))
            yield ev

        # Say what was seen and what was left out. Without this line, "found 1"
        # against three approved rows in the Table Editor is a mystery: on 23 Sep
        # 2026 an approved submission was missing from the site and the log could
        # not say whether it had been skipped, was already over, or had simply
        # been approved after the run.
        log.info("%s: %d approved row(s), %d live, %d already over or unusable",
                 self.name, len(rows), len(published), over)

        # Mark what we published, so the Table Editor shows at a glance which
        # approved rows are actually live. Best-effort: if this fails the events
        # are already yielded and the site is fine, so it must not raise.
        if published:
            self._mark_published(base, headers, published)

    def _to_event(self, row: dict, today: date) -> Optional[Event]:
        title = (row.get("title") or "").strip()
        start = parse_date(str(row.get("start_date") or ""))
        if not title or not start:
            log.warning("%s: row %s has no usable title/date — skipped",
                        self.name, row.get("id"))
            return None

        end = parse_date(str(row.get("end_date"))) if row.get("end_date") else None
        # Past events aren't wrong, they're just over. Same rule as every other
        # source: an event is live until its END date passes.
        if (end or start) < today:
            log.info("%s: row %s (%s) ended %s — already over, not published",
                     self.name, row.get("id"), title[:40], (end or start).isoformat())
            return None

        cat = row.get("category") or "autre"
        if cat not in CATEGORIES:
            # The DB has a CHECK for this, so reaching here means the constraint
            # was changed without updating CATEGORIES. Don't drop the event over
            # a taxonomy mismatch.
            log.warning("%s: unknown category %r on row %s — filing under 'autre'",
                        self.name, cat, row.get("id"))
            cat = "autre"

        return Event(
            title=title,
            start=start,
            end=end,
            time=(row.get("time") or None),
            town=canon_town(row.get("town")),
            venue=(row.get("venue") or None),
            category=cat,
            url=(row.get("url") or None),
            note=(row.get("note") or None),
            source=self.name,
            submitted_by="community",
            approved=True,          # we only ever query approved=eq.true
        )

    def _mark_published(self, base: str, headers: dict,
                        rows: list[tuple[str, str]]) -> None:
        """Flag each newly published row, and record which event it became.

        `live_fingerprint` is what lets Supabase email the submitter a link to
        THEIR event (whatsonnice.com/?e=<fingerprint>) rather than the home page;
        migration 009 sends that email when `published` flips to true.

        One request per row, because each row gets its own fingerprint. There are
        a handful at most. The `published=eq.false` filter is load-bearing: it
        makes the flip happen once per row, so the "your event is live" email is
        sent once and never again on later runs.

        Before migration 009 is applied the column does not exist and PostgREST
        rejects the whole request, which would leave rows unflagged. So on a
        refusal, retry with `published` alone. Best-effort throughout: the events
        are already yielded and the site is fine whatever happens here.
        """
        hdrs = {**headers, "Content-Type": "application/json", "Prefer": "return=minimal"}
        for row_id, fp in rows:
            url = f"{base}/rest/v1/submissions?id=eq.{row_id}&published=eq.false"
            try:
                r = self.client.patch(url, headers=hdrs,
                                      json={"published": True, "live_fingerprint": fp})
                if r.status_code >= 400:
                    self.client.patch(url, headers=hdrs, json={"published": True})
            except Exception as e:
                log.info("%s: couldn't flag row %s published (harmless) — %s",
                         self.name, row_id, e)
