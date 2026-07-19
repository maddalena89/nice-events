"""CLI.

    python -m niceevents.run scrape                 # every source
    python -m niceevents.run scrape --only brocabrac tango
    python -m niceevents.run scrape --no-browser    # skip Playwright sources
    python -m niceevents.run scrape --headful       # watch the browser work
    python -m niceevents.run build                  # generate dist/
    python -m niceevents.run stats
    python -m niceevents.run pending                # review submissions
"""
from __future__ import annotations

import argparse
import logging
import sys
import traceback
from datetime import date, datetime, timedelta

from . import db
from .models import CATEGORIES, is_nonevent
from .scrapers import REGISTRY

log = logging.getLogger("niceevents")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(levelname)-7s %(name)s │ %(message)s",
        stream=sys.stdout,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def cmd_scrape(args) -> int:
    names = args.only or list(REGISTRY)
    unknown = [n for n in names if n not in REGISTRY]
    if unknown:
        print(f"Unknown scraper(s): {', '.join(unknown)}")
        print(f"Available: {', '.join(sorted(REGISTRY))}")
        return 2

    total_added = total_found = 0
    failures: list[str] = []

    with db.connect(args.db) as conn:
        for name in names:
            cls = REGISTRY[name]
            if cls.needs_browser and args.no_browser:
                log.info("%-16s skipped (--no-browser)", name)
                continue

            kwargs = {}
            if cls.needs_browser:
                kwargs["headless"] = not args.headful

            log.info("%-16s starting%s", name, " [browser]" if cls.needs_browser else "")
            try:
                scraper = cls(**kwargs)
                events = list(scraper.fetch())
                if hasattr(scraper, "close"):
                    scraper.close()

                # Drop club admin (subscriptions, AGMs, school recitals). Human
                # submissions are exempt — a person already vetted those, and the
                # filter must never override a human's judgement.
                kept = [e for e in events
                        if e.submitted_by or not is_nonevent(e.title)]
                junk = len(events) - len(kept)
                if junk:
                    log.info("%-16s filtered %d non-event(s)", name, junk)
                events = kept

                added, merged = db.upsert(conn, events)
                db.log_run(conn, name, ok=True, found=len(events), added=added)
                total_added += added
                total_found += len(events)
                log.info("%-16s %3d found · %3d new · %3d merged",
                         name, len(events), added, merged)
                if not events:
                    log.warning("%-16s returned NOTHING — likely broken, check with -v", name)
            except Exception as e:
                failures.append(name)
                db.log_run(conn, name, ok=False, error=f"{type(e).__name__}: {e}")
                log.error("%-16s FAILED: %s", name, e)
                if args.verbose:
                    traceback.print_exc()

        if not args.keep_past:
            pruned = db.prune_past(conn)
            if pruned:
                log.info("pruned %d past events", pruned)

        s = db.stats(conn)

    print()
    print(f"  {total_found} scraped · {total_added} new · {s['total']} upcoming in db")
    print(f"  {s['towns']} towns")
    for cat, n in s["by_category"].items():
        print(f"    {CATEGORIES.get(cat, cat):<28} {n:>4}")
    if s["pending"]:
        print(f"\n  {s['pending']} submission(s) awaiting review — `run.py pending`")
    if failures:
        print(f"\n  FAILED: {', '.join(failures)}")
        return 1
    return 0


def cmd_build(args) -> int:
    from .site import build
    with db.connect(args.db) as conn:
        n, out = build(conn, out_dir=args.out)
    print(f"  built {out}/index.html with {n} events")
    return 0


def cmd_stats(args) -> int:
    with db.connect(args.db) as conn:
        s = db.stats(conn)
        print(f"\n  {s['total']} upcoming · {s['towns']} towns · {s['pending']} pending\n")
        for cat, n in s["by_category"].items():
            print(f"    {CATEGORIES.get(cat, cat):<28} {n:>4}")

        print("\n  last run per source:")
        rows = conn.execute("""
            SELECT scraper, MAX(started_at) at, ok, found, error
            FROM runs GROUP BY scraper ORDER BY scraper
        """).fetchall()
        for r in rows:
            mark = "ok  " if r["ok"] else "FAIL"
            extra = f" — {r['error'][:60]}" if r["error"] else f" · {r['found']} found"
            print(f"    {mark} {r['scraper']:<16} {r['at']}{extra}")
    return 0


def cmd_pending(args) -> int:
    """Review community submissions."""
    with db.connect(args.db) as conn:
        rows = conn.execute(
            "SELECT * FROM events WHERE approved = 0 ORDER BY first_seen"
        ).fetchall()
        if not rows:
            print("  nothing pending")
            return 0
        for r in rows:
            print(f"\n  [{r['fingerprint']}] {r['title']}")
            print(f"    {r['start']} · {r['town']} · {r['venue'] or '—'}")
            print(f"    proof: {r['url'] or ('image attached' if r['image'] else 'NONE')}")
            print(f"    by:    {r['submitted_by'] or 'anonymous'}")
        print(f"\n  approve:  run.py approve <fingerprint>")
        print(f"  reject:   run.py reject <fingerprint>")
    return 0


def cmd_approve(args) -> int:
    with db.connect(args.db) as conn:
        n = conn.execute("UPDATE events SET approved=1 WHERE fingerprint=?",
                         (args.fingerprint,)).rowcount
    print(f"  approved {n}")
    return 0 if n else 1


def cmd_reject(args) -> int:
    with db.connect(args.db) as conn:
        n = conn.execute("DELETE FROM events WHERE fingerprint=? AND approved=0",
                         (args.fingerprint,)).rowcount
    print(f"  rejected {n}")
    return 0 if n else 1


def cmd_digest(args) -> int:
    """Preview the email digest — events first seen in the last N days."""
    since = (datetime.utcnow() - timedelta(days=args.days)).isoformat(timespec="seconds")
    with db.connect(args.db) as conn:
        rows = db.new_since(conn, since)
    print(f"\n  {len(rows)} new since {since[:10]}\n")
    for r in rows:
        print(f"    {r['start']}  {r['town']:<22} {r['title'][:60]}")
    return 0


def main(argv=None) -> int:
    # Global flags live on a parent parser so they work on BOTH sides of the
    # subcommand: `run.py -v scrape` and `run.py scrape -v` are equivalent.
    # (Without this, argparse only accepts them before the subcommand, which is
    # not how anyone actually types.)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", default=None, help="path to sqlite file")
    common.add_argument("-v", "--verbose", action="store_true", help="show every request")

    p = argparse.ArgumentParser(prog="niceevents", description="Nice/06 events scraper",
                                parents=[common])
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        return sub.add_parser(name, parents=[common], **kw)

    s = add("scrape", help="run scrapers")
    s.add_argument("--only", nargs="+", metavar="NAME",
                   help=f"subset of: {', '.join(sorted(REGISTRY))}")
    s.add_argument("--no-browser", action="store_true", help="skip Playwright sources")
    s.add_argument("--headful", action="store_true", help="show the browser")
    s.add_argument("--keep-past", action="store_true", help="don't prune finished events")
    s.set_defaults(func=cmd_scrape)

    b = add("build", help="generate the static site")
    b.add_argument("--out", default="dist")
    b.set_defaults(func=cmd_build)

    add("stats", help="what's in the db").set_defaults(func=cmd_stats)
    add("pending", help="review submissions").set_defaults(func=cmd_pending)

    a = add("approve"); a.add_argument("fingerprint"); a.set_defaults(func=cmd_approve)
    j = add("reject");  j.add_argument("fingerprint"); j.set_defaults(func=cmd_reject)

    d = add("digest", help="preview the email digest")
    d.add_argument("--days", type=int, default=7)
    d.set_defaults(func=cmd_digest)

    args = p.parse_args(argv)
    _setup_logging(args.verbose)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
