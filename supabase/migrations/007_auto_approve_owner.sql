-- 007 — auto-approve the owner's own submissions
--
-- Submissions from a trusted email skip the manual queue: they are approved the
-- moment they land, so they appear on the next daily build without you ticking
-- anything in the Table Editor. Everyone else still lands unapproved.
--
-- Paste this whole file into Supabase -> SQL Editor -> Run. Safe to run twice.
--
-- SECURITY NOTE (accepted tradeoff): email is not authenticated. Anyone who
-- types a trusted address into the public form is auto-approved, so treat this
-- as a convenience, not a security control. You can still un-approve or delete
-- anything from the Table Editor. The trusted list lives here in the database,
-- never in the public page.

-- 1. The trusted list. Add or remove addresses here later with plain INSERT/DELETE.
create table if not exists public.trusted_submitters (
  email text primary key,
  note  text
);

insert into public.trusted_submitters (email, note)
values ('mzampitelli@gmail.com', 'site owner')   -- <- change/add the email(s) you submit events with
on conflict (email) do nothing;

-- Keep the list private: RLS on, and no anon policy at all, so the public key
-- can neither read nor write it. Triggers and the service_role key still can.
alter table public.trusted_submitters enable row level security;

-- 2. The rule. AFTER INSERT, not BEFORE: the "anon can submit" policy requires
-- approved=false at insert time (WITH CHECK), so the row must land unapproved to
-- pass that gate. This trigger then flips it. SECURITY DEFINER runs as the table
-- owner and bypasses RLS for the UPDATE; the fixed search_path is the standard
-- hardening for a SECURITY DEFINER function.
create or replace function public.auto_approve_owner()
returns trigger
language plpgsql
security definer
set search_path = public
as $$
begin
  if new.email is not null
     and exists (
       select 1 from public.trusted_submitters t
       where lower(t.email) = lower(new.email)
     ) then
    update public.submissions set approved = true where id = new.id;
  end if;
  return null;   -- AFTER trigger: the return value is ignored
end;
$$;

drop trigger if exists trg_auto_approve_owner on public.submissions;
create trigger trg_auto_approve_owner
  after insert on public.submissions
  for each row execute function public.auto_approve_owner();
