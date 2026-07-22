-- 003 — form update: fix the link check, make the link optional, add a time field.
--
-- Run this whole file once in Supabase → SQL Editor → New query → Run. Safe to
-- run twice. This is what makes the redesigned "Add your event" form work:
--   * repairs the link check that always errored (Postgres caps regex repeat
--     counts at 255, so the old {4,400} raised 2201B and blocked every submit),
--   * makes the link optional (email now identifies the submitter),
--   * adds a start-time column the form writes.

-- 1) Repair the link check.
alter table public.submissions drop constraint if exists url_is_http;
alter table public.submissions add constraint url_is_http
  check (url is null or (char_length(url) <= 400 and url ~* '^https?://[^ ]+$'));

-- 2) Link is optional now.
alter table public.submissions alter column url drop not null;

-- 3) Start time (HH:MM, 24h).
alter table public.submissions add column if not exists "time" text;
alter table public.submissions drop constraint if exists time_shape;
alter table public.submissions add constraint time_shape
  check ("time" is null or "time" ~ '^([01][0-9]|2[0-3]):[0-5][0-9]$');
