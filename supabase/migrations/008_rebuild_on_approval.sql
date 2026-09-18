-- 008: approving a submission rebuilds the site, a few minutes later, on its own.
--
-- Before this, an approved submission waited for the daily 06:00 scrape, or for
-- someone to press "Run workflow" on GitHub. Now ticking `approved` in the Table
-- Editor asks GitHub for a SUBMISSIONS-ONLY rebuild: it publishes approved
-- submissions and redraws the site without re-reading every other source, so it
-- takes about three minutes instead of thirty-five.
--
-- HOW TO APPLY (once, in the Supabase dashboard, no terminal):
--   1. SQL Editor -> New query -> paste this whole file -> Run.
--   2. Store the GitHub token it uses, in the same editor, replacing the text in
--      quotes with the token and running it:
--
--        select vault.create_secret(
--          'PASTE_THE_GITHUB_TOKEN_HERE',
--          'github_dispatch_token',
--          'Starts a fast site rebuild when a submission is approved');
--
--      That token should be a NEW fine-grained GitHub token, repository
--      nice-events only, with exactly one permission: Actions -> Read and write.
--      It can start and cancel rebuilds and nothing else: it cannot change code,
--      change what a rebuild does, or read any secret. Keep it separate from the
--      token used for pushing code, so each one can do only its own job.
--
-- Until the token is stored, the trigger does nothing at all. An approval never
-- waits on GitHub and never fails because of it: the call is fire-and-forget
-- (pg_net queues it after the transaction commits), and any error inside the
-- function is swallowed rather than rolling the approval back.

create extension if not exists pg_net with schema extensions;

create or replace function public.rebuild_on_approval()
returns trigger
language plpgsql
security definer
set search_path = public, extensions
as $$
declare
  tok text;
begin
  -- Only when a row has JUST become publishable. That is either an insert that
  -- is already approved (the owner's own submissions, see 007) or a flip from
  -- unapproved to approved. Editing a typo on an already-approved row must not
  -- set off a rebuild.
  if not coalesce(new.approved, false) then
    return new;
  end if;
  if tg_op = 'UPDATE' and coalesce(old.approved, false) then
    return new;
  end if;

  select decrypted_secret into tok
    from vault.decrypted_secrets
   where name = 'github_dispatch_token'
   limit 1;
  if tok is null or tok = '' then
    return new;                                  -- not set up yet: do nothing
  end if;

  perform net.http_post(
    url     := 'https://api.github.com/repos/maddalena89/nice-events/actions/workflows/scrape.yml/dispatches',
    headers := jsonb_build_object(
                 'Authorization',        'Bearer ' || tok,
                 'Accept',               'application/vnd.github+json',
                 'X-GitHub-Api-Version', '2022-11-28',
                 'User-Agent',           'whatsonnice-supabase',
                 'Content-Type',         'application/json'),
    body    := jsonb_build_object(
                 'ref',    'main',
                 'inputs', jsonb_build_object('mode', 'submissions'))
  );
  return new;
exception when others then
  -- Never let a failed call undo the approval itself. The daily scrape still
  -- publishes the row the next morning, so the worst case is the old behaviour.
  return new;
end;
$$;

-- Nobody outside the database should be able to call this directly.
revoke all on function public.rebuild_on_approval() from public, anon, authenticated;

drop trigger if exists submissions_rebuild_on_approval on public.submissions;
create trigger submissions_rebuild_on_approval
  after insert or update of approved on public.submissions
  for each row execute function public.rebuild_on_approval();

-- To see whether GitHub accepted the most recent calls (204 means yes):
--   select id, status_code, left(content::text, 200), created
--     from net._http_response order by created desc limit 5;
