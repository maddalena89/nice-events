-- 009: two emails the site never sent.
--
--   1. To Maddalena, the moment a submission arrives, so it can be approved
--      quickly instead of being found days later in the Table Editor.
--   2. To the submitter, when their event goes live, with a link straight to it.
--
-- Both are sent through Resend as hello@whatsonnice.com, straight from the
-- database: no Edge Function to deploy, nothing to run in a terminal.
--
-- BEFORE THIS CAN SEND ANYTHING (checked 2026-09-18: none of it exists yet):
--   * a Resend account, with whatsonnice.com added and verified. Resend gives DNS
--     records to add in Cloudflare; until they verify, Resend refuses to send as
--     hello@whatsonnice.com. The domain today only RECEIVES mail (Cloudflare
--     Email Routing), it has never been set up to send.
--   * a Resend API key with "Sending access", restricted to whatsonnice.com.
--
-- HOW TO APPLY (Supabase dashboard -> SQL Editor, no terminal):
--   1. Paste this whole file -> Run.
--   2. Store the two private values, replacing the text in quotes, and Run:
--
--        select vault.create_secret('re_PASTE_RESEND_KEY', 'resend_api_key',
--                                   'Sends site email as hello@whatsonnice.com');
--        select vault.create_secret('you@example.com', 'notify_owner_email',
--                                   'Where new-submission alerts go');
--
--      The owner address lives in the vault rather than in this file because
--      this file is in a PUBLIC repository.
--
-- Until the key is stored, nothing is sent and nothing fails. A submission, an
-- approval or a publish never waits on Resend and is never rolled back because
-- of it: pg_net sends after the transaction commits, and every error here is
-- swallowed. The worst case is the old behaviour, silence.

create extension if not exists pg_net with schema extensions;

-- ---------------------------------------------------------------------------
-- Where the submission ended up on the site, and whether its owner was told.
-- live_fingerprint is written by the daily/fast scrape when it publishes the row
-- (niceevents/scrapers/submissions.py) and becomes the ?e= link in the email.
alter table public.submissions
  add column if not exists live_fingerprint text,
  add column if not exists live_notified_at timestamptz;

-- ---------------------------------------------------------------------------
-- The helpers live in a PRIVATE schema on purpose. Supabase exposes every
-- function in `public` over its web API to anyone holding the site's public key,
-- and that key is published inside the site's own HTML. A "send an email"
-- function in `public` would let anyone on the internet send mail as
-- hello@whatsonnice.com. `private` is not exposed.
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;

-- Submitted text goes into HTML email, and a submitter controls it. Escape it,
-- or a title like </b><a href=...> becomes a link in your inbox.
create or replace function private.html(t text)
returns text
language sql
immutable
as $$
  select replace(replace(replace(replace(replace(coalesce(t, ''),
         '&', '&amp;'), '<', '&lt;'), '>', '&gt;'), '"', '&quot;'), '''', '&#39;')
$$;

-- One line of plain text: a subject header must not contain a line break.
create or replace function private.one_line(t text, n int)
returns text
language sql
immutable
as $$
  select left(regexp_replace(coalesce(t, ''), '\s+', ' ', 'g'), n)
$$;

create or replace function private.send_email(to_addr text, subj text, html text)
returns void
language plpgsql
security definer
set search_path = private, extensions
as $$
declare
  api_key   text;
  from_addr text;
begin
  select decrypted_secret into api_key
    from vault.decrypted_secrets where name = 'resend_api_key' limit 1;
  if coalesce(api_key, '') = '' or coalesce(to_addr, '') = '' then
    return;                                      -- not set up, or nobody to send to
  end if;
  select decrypted_secret into from_addr
    from vault.decrypted_secrets where name = 'notify_from' limit 1;
  from_addr := coalesce(nullif(from_addr, ''), 'What''s on in Nice <hello@whatsonnice.com>');

  perform net.http_post(
    url     := 'https://api.resend.com/emails',
    headers := jsonb_build_object(
                 'Authorization', 'Bearer ' || api_key,
                 'Content-Type',  'application/json'),
    body    := jsonb_build_object(
                 'from',    from_addr,
                 'to',      jsonb_build_array(to_addr),
                 'subject', subj,
                 'html',    html)
  );
exception when others then
  return;
end;
$$;

revoke all on function private.send_email(text, text, text) from public, anon, authenticated;

-- ---------------------------------------------------------------------------
-- 1. A new submission is waiting.
create or replace function private.notify_owner_new_submission()
returns trigger
language plpgsql
security definer
set search_path = private, public, extensions
as $$
declare
  owner_addr text;
  when_txt   text;
begin
  -- The owner's own submissions are approved on arrival (migration 007), so
  -- there is nothing to ask her to do.
  if coalesce(new.approved, false) then
    return new;
  end if;

  select decrypted_secret into owner_addr
    from vault.decrypted_secrets where name = 'notify_owner_email' limit 1;

  when_txt := to_char(new.start_date, 'FMDD FMMonth YYYY')
           || case when new.end_date is not null and new.end_date <> new.start_date
                   then ' to ' || to_char(new.end_date, 'FMDD FMMonth YYYY') else '' end
           || case when coalesce(new."time", '') <> '' then ', ' || new."time" else '' end;

  perform private.send_email(
    owner_addr,
    'New event to approve: ' || private.one_line(new.title, 90),
    '<p>Someone just submitted an event to What''s on in Nice.</p>'
    || '<p><b>' || private.html(new.title) || '</b><br>'
    || private.html(when_txt) || '<br>'
    || private.html(new.town)
    || case when coalesce(new.venue, '') <> '' then ' &middot; ' || private.html(new.venue) else '' end
    || '</p>'
    || case when coalesce(new.note, '') <> '' then '<p>' || private.html(new.note) || '</p>' else '' end
    || case when coalesce(new.url, '') <> ''
            then '<p>Their link: <a href="' || private.html(new.url) || '">' || private.html(new.url) || '</a></p>'
            else '' end
    || '<p>Submitted by ' || private.html(coalesce(new.email, 'no email given')) || '</p>'
    || '<p><a href="https://supabase.com/dashboard/project/oakujpknuiqlvstpmuhk/editor">'
    || 'Open the submissions table to approve it</a>. Once you tick approved, '
    || 'the site rebuilds on its own within a few minutes.</p>'
  );
  return new;
exception when others then
  return new;
end;
$$;

drop trigger if exists submissions_notify_owner on public.submissions;
create trigger submissions_notify_owner
  after insert on public.submissions
  for each row execute function private.notify_owner_new_submission();

-- ---------------------------------------------------------------------------
-- 2. It is live: tell the person who submitted it.
create or replace function private.notify_submitter_live()
returns trigger
language plpgsql
security definer
set search_path = private, public, extensions
as $$
declare
  link text;
begin
  -- Only on the flip from not published to published. The scrape flips each
  -- row exactly once, and live_notified_at guards against a manual untick and
  -- retick in the Table Editor sending it twice.
  if not coalesce(new.published, false) or coalesce(old.published, false) then
    return new;
  end if;
  if new.live_notified_at is not null
     or coalesce(new.email, '') = ''
     or new.unsubscribed_at is not null then
    return new;
  end if;

  link := 'https://whatsonnice.com/'
       || case when coalesce(new.live_fingerprint, '') <> ''
               then '?e=' || new.live_fingerprint else '' end;

  perform private.send_email(
    new.email,
    'Your event is on What''s on in Nice',
    '<p>Hello,</p>'
    || '<p>Thank you for adding <b>' || private.html(new.title) || '</b>. '
    || 'It is going up on What''s on in Nice now and will be on the site within a few minutes:</p>'
    || '<p><a href="' || private.html(link) || '">' || private.html(link) || '</a></p>'
    || '<p>Share the link so people can find it.</p>'
    || '<p style="color:#777">Bonjour, votre &eacute;v&eacute;nement est en ligne sur '
    || 'What''s on in Nice. Merci !</p>'
    || '<p>What''s on in Nice</p>'
  );

  -- Updating live_notified_at does not re-fire this trigger (it fires on
  -- `published`), nor the rebuild trigger from 008 (which fires on `approved`).
  update public.submissions set live_notified_at = now() where id = new.id;
  return new;
exception when others then
  return new;
end;
$$;

drop trigger if exists submissions_notify_live on public.submissions;
create trigger submissions_notify_live
  after update of published on public.submissions
  for each row execute function private.notify_submitter_live();

revoke all on function private.notify_owner_new_submission() from public, anon, authenticated;
revoke all on function private.notify_submitter_live()       from public, anon, authenticated;

-- To see whether Resend accepted recent emails (200 means sent):
--   select id, status_code, left(content::text, 200), created
--     from net._http_response order by created desc limit 5;
