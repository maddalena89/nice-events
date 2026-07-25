-- What's on in Nice — messages table (bug reports + "say hi" / newsletter).
-- Paste the whole file into Supabase → SQL Editor → Run. Safe to run twice.
--
-- Same security model as submissions: the public may INSERT and nothing else.
-- The anon key is public, so every rule below assumes a hostile caller. You read
-- the rows by hand in the Table Editor (filter by `kind`); flip `handled` when
-- you've dealt with one.

create table if not exists public.messages (
  id          uuid primary key default gen_random_uuid(),
  created_at  timestamptz not null default now(),

  kind        text not null,              -- 'bug' or 'hello'
  body        text,                       -- the message (what's wrong / a note)
  email       text,                       -- optional, so you can reply / add to list
  page_url    text,                       -- where they were when they clicked
  handled     boolean not null default false,

  -- --- constraints: the actual gate ------------------------------------
  constraint kind_known check (kind in ('bug','hello')),
  constraint body_len   check (body     is null or char_length(body)     <= 2000),
  constraint email_len2 check (email    is null or char_length(email)    <= 160),
  constraint page_len   check (page_url is null or char_length(page_url) <= 400),

  -- An email, if given, must at least look like one. Blocks obvious junk.
  constraint email_shape check (email is null or email ~* '^[^@\s]+@[^@\s]+\.[^@\s]+$'),

  -- Reject empty pings: a message must carry a body or an email (or both).
  constraint has_content check (
    coalesce(body,  '') <> '' or coalesce(email, '') <> ''
  )
);

create index if not exists messages_triage_idx
  on public.messages (kind, created_at desc);

alter table public.messages enable row level security;

-- Anonymous visitors may INSERT, and only as an unhandled bug/hello. Nobody can
-- read, update, or self-mark handled.
drop policy if exists "anon can message" on public.messages;
create policy "anon can message"
  on public.messages for insert to anon
  with check (kind in ('bug','hello') and handled = false);
