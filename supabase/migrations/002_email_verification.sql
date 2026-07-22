-- 002 — verify the PERSON by email, not the event by a link.
--
-- The old rule: a submission needs a `url` as "proof". But a link proves nothing
-- (anyone can paste one) and it turns away the most valuable submitters — the
-- organiser who has a poster and a phone, not a web page. New rule: the link is
-- OPTIONAL, and instead we confirm the submitter owns the email they gave. A real
-- address that answers a click is cheap for an honest person and annoying for a
-- spammer, and it costs us nothing (transactional email free tier).
--
-- Nothing appears on the site until BOTH are true: the submitter clicked the
-- confirm link (email_verified) AND Maddalena approved it (approved). Verification
-- stops drive-by spam; approval is still the human editorial gate.
--
-- Paste into Supabase → SQL Editor → Run. Safe to run on the existing table.

alter table public.submissions
  alter column url drop not null,                          -- link no longer required
  alter column email set not null,                         -- email now required
  add column if not exists email_verified boolean not null default false,
  add column if not exists verify_token uuid not null default gen_random_uuid();

-- The link, when given, must still be a real http(s) URL (blocks javascript:/data:
-- XSS). When absent, that's fine now.
-- Length via char_length, NOT a {min,max} regex bound: Postgres caps regex
-- repetition counts at 255, so '{4,400}' raises 2201B and every INSERT fails.
alter table public.submissions drop constraint if exists url_is_http;
alter table public.submissions add constraint url_is_http
  check (url is null or (char_length(url) <= 400 and url ~* '^https?://[^ ]+$'));

-- A basic shape check on the email so obviously-fake input is rejected at the DB.
alter table public.submissions drop constraint if exists email_shape;
alter table public.submissions add constraint email_shape
  check (email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$');

-- Only publish rows that are BOTH confirmed and approved. The daily build query
-- becomes:  ?approved=eq.true&email_verified=eq.true   (see submissions.py note).
create index if not exists submissions_publish_idx
  on public.submissions (approved, email_verified, created_at desc);

-- RLS: anonymous insert must not be able to self-verify or self-approve or set a
-- token of their choosing. verify_token is server-generated; email_verified and
-- approved must start false. (If you route inserts through the submit-event Edge
-- Function with the service key instead, that bypasses RLS — keep this policy as
-- defence in depth either way.)
drop policy if exists "anon can submit" on public.submissions;
create policy "anon can submit"
  on public.submissions for insert to anon
  with check (
    approved = false
    and published = false
    and email_verified = false
  );

-- verify_token is a capability (whoever holds it can confirm that row), so it must
-- never be readable by the public. There is still NO anon select policy — the
-- build reads with the service_role key, which bypasses RLS. Do not add one.
