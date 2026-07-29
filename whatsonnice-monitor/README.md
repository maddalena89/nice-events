# whatsonnice daily health monitor

A set-and-forget health check for **whatsonnice.com**. It runs on GitHub's
servers on a daily schedule, so it fires whether or not your computer is on.
It fetches `events.json`, confirms the data is fresh, scans for data problems,
and pushes the findings to your phone.

It is **read-only**. It never changes your code, your data, or the site.

## What it checks

- **Freshness** — if the data is more than 48 hours old, the scraper has
  probably stopped. This is flagged as the most important problem.
- **False midnights** — any event whose time is exactly `00:00`.
- **Past events still listed** — start date already in the past.
- **Likely duplicates** — same title, same date, same town.
- **Long continuous ranges** — a recurring event rendered as one long block
  (start and end more than ~10 days apart and the note says "Also on").
- **Empty descriptions** — missing or blank note.
- **Free vs price conflicts** — marked free but a euro amount appears, or
  marked paid but the text says it is free.

On a healthy day it stays quiet (no push). On a problem day it pushes a
grouped, scannable report naming the specific events and dates.

## One-time setup (about 10 minutes)

1. **Create a GitHub repo** (private is fine). Add these two files, keeping the
   folder layout:
   - `health_check.py`
   - `.github/workflows/health-check.yml`

2. **Set up the phone push (free, no account needed):**
   - Install the **ntfy** app on your phone (iOS or Android).
   - Pick a private, hard-to-guess topic name, e.g. `whatsonnice-9f3k2x`.
   - In the app, subscribe to that exact topic.
   - In your GitHub repo: **Settings -> Secrets and variables -> Actions ->
     New repository secret**. Name it `NTFY_TOPIC`, value = your topic name.

   Anyone who knows the topic name can read the pushes, so keep it random.

3. **Done.** The schedule in the workflow runs it daily at 05:00 UTC
   (~7am Nice in summer, ~6am in winter). To test it right now, go to the
   **Actions** tab -> **whatsonnice daily health check** -> **Run workflow**.

## Adjusting things

- **Time of day:** edit the `cron:` line in the workflow. It is in UTC, format
  `minute hour day month weekday`. For 7am Nice in winter use `0 6 * * *`.
- **Get a push every day (even when healthy):** set `NTFY_ALWAYS: "1"` in the
  workflow.
- **Backup alert:** because the script exits with an error when it finds
  problems, GitHub will also email you that the run "failed" — a second signal
  even if a push is missed. (You can turn this off in your GitHub notification
  settings if it is noisy.)

## If the field names are wrong

The script tries several common key names for each field. If your `events.json`
uses different names, the report prints "Field notes" telling you which checks
went inactive. Send me those notes and the exact key names and I will adjust the
script.

## What this does NOT do

It does not find new event sources or new events, and it does not touch your
scraper. It only watches the output. Source discovery is a separate task.
