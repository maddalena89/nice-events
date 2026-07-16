-- What's on in Nice — submissions table.
-- Paste the whole file into Supabase → SQL Editor → Run. Safe to run twice.
--
-- The security model in one line: the public may INSERT and nothing else.
-- The anon key is printed inside the webpage, so anyone can read it and call
-- this table directly. That is expected and fine — the key identifies the
-- project, it does not authorise anything. Row Level Security below is what
-- actually decides what a stranger can do, so the rules must hold up on the
-- assumption that the caller is hostile and is NOT using our form.
-- Every CHECK here therefore duplicates a check the form already does. The form
-- validation is a courtesy to honest users; these are the real ones.

create table if not exists public.submissions (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),

  title       text not null,
  start_date  date not null,
  end_date    date,
  town        text not null,
  venue       text,
  category    text not null,
  url         text not null,
  note        text,
  email       text,

  -- Moderation. You flip `approved` by hand in the Table Editor; the daily
  -- scrape publishes approved rows and sets `published` so it can tell you
  -- what's new without republishing everything.
  approved    boolean not null default false,
  published   boolean not null default false,

  -- --- constraints: these are the actual gate ---------------------------
  -- Lengths: stop someone pasting a novel into a text column.
  constraint title_len  check (char_length(title) between 3 and 200),
  constraint town_len   check (char_length(town)  between 2 and 80),
  constraint venue_len  check (venue is null or char_length(venue) <= 160),
  constraint note_len   check (note  is null or char_length(note)  <= 600),
  constraint email_len  check (email is null or char_length(email) <= 160),

  -- Proof link must be a real http(s) URL. Blocks javascript: and data: URIs,
  -- which would otherwise be a stored-XSS vector the moment we render the link.
  constraint url_is_http check (url ~* '^https?://[^ ]{4,400}$'),

  -- Category must be one we actually render. Anything else would land in a
  -- filter tab that doesn't exist.
  constraint category_known check (category in (
    'brocante','danse','concert','expo','scene','visite',
    'atelier','business','social','sport','marche','autre'
  )),

  -- Dates must be sane. No events in 1970, none in 2140, and no event that
  -- ends before it starts.
  constraint start_sane check (start_date >= date '2024-01-01'
                           and start_date <= (now() at time zone 'utc')::date + 730),
  constraint end_after_start check (end_date is null or end_date >= start_date)
);

create index if not exists submissions_triage_idx
  on public.submissions (approved, created_at desc);

alter table public.submissions enable row level security;

-- Anonymous visitors may INSERT. That is the entire public surface.
drop policy if exists "anon can submit" on public.submissions;
create policy "anon can submit"
  on public.submissions for insert to anon
  with check (
    -- Nobody self-approves. Without this, a hostile caller simply posts
    -- approved=true and walks straight onto the site.
    approved  = false
    and published = false
  );

-- Deliberately NO select policy for anon.
-- Submitters give us their email address; letting the public read this table
-- would publish those addresses to anyone who reads the key out of the page.
-- The build job reads with the service_role key, which bypasses RLS.

grant insert on public.submissions to anon;
