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

import logging
import os
from datetime import date
from typing import Iterator, Optional

from ..models import CATEGORIES, Event, canon_town, parse_date
from .base import HttpScraper, register

log = logging.getLogger(__name__)

# Only the columns we need. Notably NOT `email` — it's the submitter's private
# contact detail, it has no business in a public events feed, and the surest way
# to never leak it is to never load it.
_COLS = "id,title,start_date,end_date,town,venue,category,url,note"


@register
class Submissions(HttpScraper):
    name = "submissions"
    label = "Community submissions"
    delay = 0.0          # our own database; no politeness delay needed

    def _cfg(self) -> tuple[Optional[str], Optional[str]]:
        url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
        key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
        return (url or None), (key or None)

    def fetch(self) -> Iterator[Event]:
        base, key = self._cfg()
        if not base or not key:
            log.info("%s: SUPABASE_URL / SUPABASE_SERVICE_KEY not set — skipping", self.name)
            return

        headers = {"apikey": key, "Authorization": f"Bearer {key}"}
        r = self.get(
            f"{base}/rest/v1/submissions"
            f"?approved=eq.true&select={_COLS}&order=created_at.asc",
            headers=headers,
        )
        if not r:
            log.warning("%s: could not read submissions", self.name)
            return

        try:
            rows = r.json()
        except Exception:
            log.warning("%s: submissions response wasn't JSON", self.name)
            return

        today = date.today()
        published: list[str] = []

        for row in rows:
            ev = self._to_event(row, today)
            if ev is None:
                continue
            published.append(row["id"])
            yield ev

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
            town=canon_town(row.get("town")),
            venue=(row.get("venue") or None),
            category=cat,
            url=(row.get("url") or None),
            note=(row.get("note") or None),
            source=self.name,
            submitted_by="community",
            approved=True,          # we only ever query approved=eq.true
        )

    def _mark_published(self, base: str, headers: dict, ids: list[str]) -> None:
        try:
            ids_csv = ",".join(f'"{i}"' for i in ids)
            self.client.patch(
                f"{base}/rest/v1/submissions?id=in.({ids_csv})&published=eq.false",
                headers={**headers, "Content-Type": "application/json",
                         "Prefer": "return=minimal"},
                json={"published": True},
            )
        except Exception as e:
            log.info("%s: couldn't flag rows published (harmless) — %s", self.name, e)
