-- A tiny key/value table for runtime settings the scraper reads at run time,
-- so config can change without editing code or the GitHub workflow.
--
-- First use: the scrape proxy. Editing the Action workflow needs a token
-- permission we don't have, so the proxy URL lives here instead and the daily
-- run reads it with the Supabase service key (which bypasses RLS).
--
-- The value is a credential, so it is NOT stored in this file. Set it once from
-- the Supabase SQL editor:
--   insert into public.app_config (key, value)
--   values ('scraper_proxy', 'http://user:pass@host:port')
--   on conflict (key) do update set value = excluded.value;

create table if not exists public.app_config (
    key   text primary key,
    value text
);

-- No public access. Only the service key (which bypasses RLS) may read it.
alter table public.app_config enable row level security;
