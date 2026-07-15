# What's on in Nice — events scraper for the 06

Scrapes public event listings across Nice and the Alpes-Maritimes, dedups them,
and generates a static site you can host for free.

Covers: vide-greniers & brocantes · milongas & tango · concerts & club nights ·
museum exhibitions · design/business/AI meetups · expat socials · guided visits ·
workshops · village fêtes.

---

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium          # only needed for Meetup / RA / Eventbrite

python -m niceevents.run scrape --no-browser   # fast sources first (~2 min)
python -m niceevents.run scrape                # everything (~10-15 min)
python -m niceevents.run build                 # -> dist/index.html
open dist/index.html
```

Useful:

```bash
python -m niceevents.run scrape --only brocabrac tango -v   # one source, loudly
python -m niceevents.run scrape --headful                   # watch the browser
python -m niceevents.run stats                              # what's in the db
python -m niceevents.run digest --days 7                    # preview email digest
```

---

## Read this before you trust the numbers

**The scrapers have not been run against the live sites.** They were written
from real page structure I fetched and read, but the sandbox they were written
in has no network access to these hosts, so the parsers are unverified against
production HTML. The core logic (date parsing, town canonicalisation, dedup,
merge, site build) *is* covered by 47 passing tests — run `pytest`.

Expect the first real run to surface breakage. `--only <name> -v` on each source
is the fastest way to find it. A source returning **0 events** is the signal;
the runner warns loudly when that happens rather than quietly shipping an empty
site.

Rough confidence, highest to lowest:

| Source | How it works | Confidence |
|---|---|---|
| `nice_fr` | WordPress REST API, structured JSON | **High** — real API, not scraping |
| `brocabrac` | Server-rendered HTML, stable markup | **High** |
| `tango_argentin` | Server-rendered tables | **Good** |
| `explore_nca` | Server-rendered, paginated | **Good** — town detection is heuristic |
| `ra` | Playwright + `__NEXT_DATA__` | **Medium** — JSON shape guessed |
| `meetup` | Playwright + `__NEXT_DATA__` | **Medium** — JSON shape guessed |
| `museums` | JSON-LD, 11 venues | **Low** — varies wildly per venue |
| `eventbrite` | Playwright + JSON-LD | **Low** — actively bot-protected |

---

## Known gaps

**Cannes / Antibes / Menton / Grasse are thin.** `explore_nca` is the *Métropole*
tourist office, which stops at ~50 communes. Those four are separate
intercommunalités. Brocabrac covers them for brocantes; everything else needs a
scraper per tourist office. This is the biggest coverage hole and the most
tractable next job.

**Facebook and Instagram are not scraped, and won't be.** Both block automated
access and it violates their ToS — doing it risks the account, not just the
scrape. Meta shut the public Events API years ago. Anything claiming otherwise
is either breaking ToS or reselling stale data. The realistic path is the
submissions form: a human sees a Facebook event, submits it with the FB link as
proof. That's curation, not scraping, and it's fine.

**The old open-data feed is a trap.** `data.gouv.fr` still lists
*"[VDN] Agenda de la Ville de Nice en temps réel"* as a live real-time feed. It
404s and was last touched in 2020. Use the WordPress API instead — that's what
`nice_fr` does.

**Museums are the weakest link.** Eleven venues, eleven different CMSes. The
scraper tries JSON-LD then falls back to `<time>` tags. Venues that come back
empty need either a bespoke parser or a Playwright pass.

---

## Hosting — recommendation

**Use GitHub Actions + GitHub Pages.** Not a VPS.

- Actions runs the scrapers on cron. Playwright works there out of the box.
  Free tier is 2,000 min/month; a full daily run is ~15 min → ~450 min/month.
- Pages serves `dist/` publicly, free, on a real domain if you want one.
- The DB is committed back to the repo, so `first_seen` survives between runs —
  which is what the email digest will need later.
- Nothing to patch, nothing to pay for, nothing to wake up at 3am for.

A VPS (~€5/mo, Hetzner/Scaleway) only wins if you outgrow the Actions minutes or
want scraping more than a few times a day.

`.github/workflows/scrape.yml` is ready to go. To enable:

1. Push this repo to GitHub.
2. Settings → Pages → Source: *GitHub Actions*.
3. Settings → Actions → General → Workflow permissions: *Read and write*.
4. Actions tab → *Scrape and publish* → *Run workflow* to test it now.

---

## Submissions

A static site can't accept a form POST, so pick one before `build`:

```bash
# Option A — no backend at all: submissions open a prefilled GitHub issue
export GITHUB_REPO="yourname/nice-events"

# Option B — a real form endpoint (Formspree free tier, Netlify, a Worker)
export SUBMIT_ENDPOINT="https://formspree.io/f/xxxxxxx"
```

Option A is the honest starting point: free, auditable, no server, and you
review each one. Nothing appears on the site until you approve it:

```bash
python -m niceevents.run pending
python -m niceevents.run approve <fingerprint>
python -m niceevents.run reject  <fingerprint>
```

**On "validating with an image or a link":** the form checks *shape*, not truth
— that a URL is well-formed, that an image really decodes as an image. Nothing
automated can confirm an event is real. That's what the review step is for.
Don't let the site imply otherwise.

---

## Email digest (later)

The groundwork is in: `first_seen` is written once and never updated, so
"what's new since last Tuesday" is a real query, not a guess.

```bash
python -m niceevents.run digest --days 7
```

`db.new_since(conn, iso_timestamp)` returns the rows. To ship it you'd add a
sender (Buttondown, Listmonk, SES) and a subscriber list — that's the only
missing piece, and it needs somewhere to store addresses, which means either a
service or a small backend.

---

## Adding a source

1. Drop a module in `niceevents/scrapers/`.
2. Subclass `HttpScraper` (static HTML/JSON) or `BrowserScraper` (JS-rendered).
3. Decorate with `@register`, set `name` and `label`, yield `Event` objects.
4. Import it in `scrapers/__init__.py`.

Dedup is automatic — the `Event` fingerprint is `title + date + town`,
accent- and case-insensitive, with badges like "Gratuit" stripped. Two sources
describing the same night will collapse into one row, keeping the richest venue
and note from each and recording both source names.

```python
from ..models import Event
from .base import HttpScraper, register

@register
class Menton(HttpScraper):
    name = "menton"
    label = "Menton tourist office"

    def fetch(self):
        r = self.get("https://tourisme-menton.fr/agenda/")
        if not r:
            return
        yield Event(title="...", start=..., town="Menton", source=self.name)
```

---

## Layout

```
niceevents/
  models.py      Event, fingerprint, date/town/category normalisation
  db.py          SQLite, dedup-merge, prune, digest queries
  site.py        DB -> dist/index.html + events.json
  run.py         CLI
  scrapers/
    base.py         HttpScraper / BrowserScraper / registry
    brocabrac.py    vide-greniers & brocantes        [http]
    nice_fr.py      Ville de Nice + Jazz Fest        [http, REST API]
    tango.py        milongas                          [http]
    explore_nca.py  50 Métropole communes             [http]
    museums.py      Maeght, MAMAC, Matisse, Chagall…  [http, JSON-LD]
    meetup.py       design / business / AI / expat    [browser]
    ra.py           electronic & clubs                [browser]
    eventbrite.py   business, tech, conferences       [browser]
templates/
  index.html.jinja  the site
tests/
  test_core.py      47 tests: parsing, dedup, merge, build
```

## Etiquette

Rate-limited by default (1–3s between requests), one polite user-agent, no
login, no account actions, public pages only. Every listing links back to its
source. Keep it that way — this is a reading aid that sends traffic to the
people doing the actual work, not a replacement for them.
