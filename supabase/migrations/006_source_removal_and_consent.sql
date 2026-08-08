-- 006 — a removal route for sources, and the paperwork the weekly email needs.
--
-- Two unrelated-looking things, one reason: both are cheap now and expensive
-- later. Paste into Supabase → SQL Editor → Run. Safe to run twice.
--
-- ---------------------------------------------------------------------------
-- PART 1 — 'source': "I run one of the sites you scrape, take me out"
--
-- The site gathers publicly listed events from other people's calendars and
-- links back to them. That is a friendly arrangement right up until one of them
-- would rather not be included, and at that point the only thing that matters is
-- how easy it was for them to say so. A visible one-click removal route turns
-- what could become a legal letter into a two-line email, and honouring it the
-- same day keeps it that way. It costs one CHECK constraint.
--
-- PART 2 — consent for the weekly email
--
-- The 'hello' rows are people who agreed to receive something. Under the GDPR
-- that agreement has to be provable and withdrawable:
--   provable     — created_at is the timestamp, and the form now states plainly
--                  what they are agreeing to before they press the button
--                  (see MSG_MODES.hello.hint in the template). Consent obtained
--                  without that notice is not consent, which is why the copy and
--                  this migration ship together.
--   withdrawable — every send must carry a working unsubscribe link, so each
--                  subscriber needs a token that identifies them without
--                  exposing their address in the URL, and a place to record that
--                  they used it.
-- Do not delete unsubscribed rows. Keeping the row with unsubscribed_at set is
-- what stops a later import quietly re-adding someone who already left.
-- ---------------------------------------------------------------------------

-- --- Part 1: allow the new kind ------------------------------------------
alter table public.messages drop constraint if exists kind_known;
alter table public.messages add constraint kind_known
  check (kind in ('bug', 'hello', 'source'));

-- RLS must allow it too, or the form posts and the row is silently rejected.
drop policy if exists "anon can message" on public.messages;
create policy "anon can message"
  on public.messages for insert to anon
  with check (kind in ('bug', 'hello', 'source') and handled = false);

-- A removal request is the one kind that must never sit unnoticed in a table.
-- Filter by this in the Table Editor, or point an alert at it.
create index if not exists messages_source_pending_idx
  on public.messages (created_at desc)
  where kind = 'source' and handled = false;

-- --- Part 2: unsubscribe plumbing ----------------------------------------
alter table public.messages
  add column if not exists unsubscribe_token uuid not null default gen_random_uuid(),
  add column if not exists unsubscribed_at   timestamptz;

-- The token is a capability: whoever holds it can unsubscribe that person. It is
-- generated server-side and must never be readable by the public. There is still
-- NO anon select policy on this table, and there must not be one — the rows hold
-- email addresses and the anon key is printed inside the webpage.

-- The list to actually send to: said yes, has an address, hasn't left.
create or replace view public.newsletter_recipients as
  select id, email, created_at as consented_at, unsubscribe_token
  from public.messages
  where kind = 'hello'
    and email is not null
    and unsubscribed_at is null;

-- The view inherits the base table's RLS, and anon has no select policy there,
-- so this is readable only with the service key. Stated explicitly because a
-- view over a protected table is exactly the kind of thing that gets a
-- well-meaning "grant select to anon" later and leaks the whole list.
revoke all on public.newsletter_recipients from anon;
