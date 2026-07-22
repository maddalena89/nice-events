# What's on in Nice — product roadmap

From a daily scraper with a clean list, to something people rely on, contribute
to, and that can eventually pay for itself — without turning into the kind of
site nobody wants to use. The north star is woloho's: **useful first, human,
ad-light, and honest about money.**

This doc is the plan. It's opinionated about *sequence*, because the order is
where most side-projects go wrong: they build accounts and payments before they
have an audience, and die with a great backend nobody logs into.

---

## Where we are after this session

Already shipped in the repo (front-end, tested, no deploy needed):

- **Le Bistrot Poète** events added (the vernissage + the exhibition to 7 Sept).
- **Mobile photo picker fixed** — you can now pick from the album, not only shoot.
- **Shareable event card** — a blue, rounded PNG generated in-browser on any
  event and right after a submission. Native share sheet on phones, download on
  desktop. This is the growth loop: every card carries `whatsonnice.com`.
- **About page** — a warm, passion-project note, reachable from the top bar and
  the footer.

Scaffolded in the repo (real code, needs your Supabase deploy — see below):

- **AI poster prefill** — `supabase/functions/read-poster/`
- **Email-verified submissions** — `supabase/migrations/002_email_verification.sql`,
  `supabase/functions/submit-event/`, `supabase/functions/confirm-submission/`

The guiding constraint stays the same as the README's: **a static site on GitHub
Pages, with Supabase as the only backend.** Everything below fits inside that —
no VPS, no server to wake up at 3am.

---

## Phase 0 — the submission glow-up (next, ~1 focused weekend)

This is the half you asked for. Two changes, one deploy.

### 0a. AI reads the poster

Today the "snap a flyer" uses in-browser OCR (Tesseract). It's fine on flat text
and hopeless on real posters. `read-poster` sends the photo to a vision model and
gets back clean fields.

**The form side is already wired** (this session): the snap handler downscales the
photo, POSTs it to the endpoint, fills the form from `fields`, and falls back to
on-device OCR if the call fails. `site.py` points it at your Supabase
`read-poster` function automatically once Supabase is configured (override with
`POSTER_AI_URL` / `POSTER_AI_KEY`). So all that's left is the deploy:
1. `supabase functions deploy read-poster`
2. `supabase secrets set ANTHROPIC_API_KEY=…`
3. Rebuild/publish. That's it — the snap button starts using AI, OCR stays as the
   fallback.

**Cost:** ~$0.001–0.01 per poster on a small vision model — only spent when
someone actually taps "read this". Add a per-IP daily cap (e.g. 20/day) in the
function before promoting it widely.

**Why it matters:** the single biggest lever on submissions is making it a
10-second act — snap, glance, send. Most people will never fill a 7-field form;
almost everyone will photograph a poster.

### 0b. Email verifies the person, not a link

You were right: the link-as-proof is both a weak signal and a barrier. New rule:
link optional, **email required and confirmed by a click.** The flow:

submit → `submit-event` inserts the row + emails a confirm link → they click →
`confirm-submission` flips `email_verified` → the build publishes rows that are
**both** `email_verified` and `approved` (you still eyeball each one).

**Deploy:**
1. Run `migrations/002_email_verification.sql` in the Supabase SQL editor.
2. `supabase functions deploy submit-event confirm-submission`
3. Sign up for Resend (free tier: 3k emails/month) and verify the
   `whatsonnice.com` sending domain; `supabase secrets set RESEND_API_KEY=…
   CONFIRM_BASE_URL=… FROM_EMAIL=…`
4. Point the form at `submit-event` instead of the direct REST insert, and drop
   the "Link (proof) *" required marker (it's optional now).
5. One-line change in `submissions.py`: add `&email_verified=eq.true` to the
   query so only confirmed rows publish.

**Cost:** free at this scale. **Payoff:** kills drive-by spam, and captures a
verified email on every submission — which is the seed of the newsletter list
(with consent; see Phase 1).

> The confirmation email is also your first, best newsletter touch. Add a single
> checkbox — "Email me the weekly what's-on digest" — and you're building the
> list as a side-effect of a thing people already want to do.

---

## Phase 1 — the newsletter (the real growth engine)

Newsletter before accounts. Always. An email list is the highest-leverage,
lowest-maintenance asset a listings site can have: it works on every phone, needs
no login, survives algorithm changes, and is the thing sponsors and premium tiers
are *sold against* later. woloho is 80k people and thirteen years — all of it a
newsletter.

The groundwork already exists: `db.new_since()` and the `first_seen` column mean
"what's new since last Tuesday" is a real query. What's missing is (a) collecting
addresses and (b) sending.

**Build:**
- **Capture:** a `subscribers` table (email, confirmed, created_at, optional
  town/category prefs), a double-opt-in confirm exactly like submissions, and a
  small signup on the site — inline near the top, in the About dialog, and in the
  submission success state. One-click unsubscribe (legally required, and just
  decent).
- **Send:** a weekly GitHub Action after the Saturday scrape runs
  `run.py digest --days 7`, renders it, and sends via the same provider
  (Resend/Buttondown/Listmonk). Buttondown is the least-effort if you want
  hosted list management + an archive; Listmonk if you want to self-host free.
- **Content:** "This week in Nice & the 06" — the ~15 best new/soon events,
  human one-liners, links back. Curated, not a data dump. That curation *is* the
  product.

**Effort:** a weekend for capture + a weekend for the send pipeline.
**Cost:** free to ~€9/mo depending on provider and list size.
**Success metric:** subscribers and open rate. Nothing else matters yet.

---

## Phase 2 — light accounts (only if the newsletter earns it)

Do this **only** once the newsletter is growing — accounts are a cost (support,
auth, privacy) that only pays off with engaged regulars. Supabase Auth (magic
link / email OTP, free) means no passwords.

Light, in priority order:
- **Save / favourite** events (heart → a saved list).
- **Follow** a town or category → your digest is personalised to them.
- **"My submissions"** — organisers see the status of what they added.

This is the bridge to money: a follows-and-saves graph tells you which towns and
categories are worth a paid tier or a sponsor, and organiser accounts are the
foundation for self-serve paid listings.

**Defer:** full organiser CMS, public profiles, comments/reviews. Each is a
moderation burden; add only on real demand.

---

## Phase 3 — money (all three, in the order they become possible)

Your call was "all of them," and they genuinely stack — but each needs a
different asset to already exist, so they arrive in sequence, not at once. The
rule throughout, woloho-style: **the reader's experience never degrades.** No
pop-ups, no walls on the free list, no fake urgency. Money comes from people who
get value (organisers, sponsors), not from taxing readers.

### 3a. Featured / promoted listings — *first, needs only traffic*
Free for the public forever. An organiser pays a small fee to **pin or highlight**
their event (a "Featured" tab, a subtle accent, top-of-category for its dates).
Fits the current model perfectly: it's a flag on an existing row, sold self-serve
once organiser accounts exist (Phase 2), or by hand (a Stripe Payment Link + you
flip a `featured` boolean) before that.
- **Unlock:** meaningful local traffic + a few repeat organisers.
- **Price:** €5–20 per event / small monthly for a venue. Local, honest.
- **Guardrail:** featured events are clearly labelled and never displace the
  chronological truth of the free list — they're *added* emphasis, not reordering
  reality.

### 3b. Local sponsorships — *second, needs the newsletter*
A local business (a bookshop, a language school, a café) sponsors the **weekly
digest** or a **category** ("Tango & dance, brought to you by …"). Simplest
money to run: one relationship, one line of copy, a flat monthly rate. Sells
directly against the newsletter's open rate and the site's town reach.
- **Unlock:** a few thousand engaged subscribers / steady traffic.
- **Price:** €50–300/mo per slot depending on audience.
- **Guardrail:** one clearly-marked sponsor per issue, relevant to the audience.
  Never programmatic ad networks — that's the enshittification woloho warns about.

### 3c. Premium newsletter / membership — *last, needs a loyal audience*
The free weekly stays free forever. A paid tier (€3–5/mo) adds things regulars
value: a **midweek "just added"** edition, **early access** to hot events,
**personalised** digests by town/category (built on Phase 2 follows), an
**organiser toolkit** (better listing, analytics, the shareable card as branded
templates), or simply a **"support this project"** membership with a warm thank-
you and a supporter badge.
- **Unlock:** an audience that already opens every issue.
- **Guardrail:** the free product must stay genuinely good on its own. Premium is
  *more*, never *the un-crippled version*.

### 3d. Tip jar — *anytime, zero cost*
A "buy me a coffee" / Stripe / Liberapay link in the About dialog and footer, from
now. It won't fund a salary, but it signals the project is worth supporting and
covers hosting from day one. Costs nothing to add.

---

## Sequencing at a glance

```
now ──► Phase 0: AI prefill + email verification  (the ask)  + tip jar
          │
          ▼
        Phase 1: newsletter capture + weekly send   ◄── the growth engine
          │
          ├──► 3a Featured listings   (needs traffic)
          ├──► 3b Sponsorships        (needs the list)
          ▼
        Phase 2: light accounts (save / follow / my submissions)
          │
          ▼
        3c Premium / membership       (needs a loyal audience)
```

Money follows audience, audience follows the newsletter, the newsletter follows
great free listings + the frictionless snap-a-poster submission. Every phase
makes the next one possible, and none of it requires leaving GitHub Pages +
Supabase.

## The one rule that keeps it worth doing

Read the woloho "against enshittification" note and keep it pinned. The free
list stays free, complete, honest, and ad-network-free. Everything monetised is
*additive* and *clearly labelled*, sold to the people who get value from reach
(organisers, sponsors) — never extracted from readers by making the free thing
worse. That constraint is not a limit on the business; for this kind of project
it **is** the business.
