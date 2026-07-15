"""DOM helpers.

WHY THIS EXISTS — read before "simplifying" a scraper back to css("h2, li"):

selectolax's `css()` with a comma-separated selector returns nodes **grouped by
selector**, NOT in document order:

    css("h6, tr")  ->  [h6, h6, h6, tr, tr, tr]     # grouped
    (what you want)    [h6, tr, h6, tr, h6, tr]     # document order

Any scraper that walks "date heading, then the rows under it" breaks silently
on this: every heading is consumed before the first row, so `current_date` ends
up pinned to the LAST heading and every event gets the same wrong date. It does
not crash. It does not return zero. It returns confident garbage — which is the
worst failure mode there is.

This bit us on both brocabrac and tango: tango collapsed ~50 milongas onto one
date (deduping to 7), and brocabrac happily reported 64 brocantes all dated to
whatever the final heading said.

`traverse()` walks the real tree, so use these.
"""
from __future__ import annotations

from typing import Iterator

from selectolax.parser import HTMLParser, Node


def in_order(tree: HTMLParser, tags: set[str]) -> Iterator[Node]:
    """Yield nodes whose tag is in `tags`, in true document order."""
    for node in tree.root.traverse(include_text=False):
        if node.tag in tags:
            yield node


def cards_containing(tree: HTMLParser, container_tags: set[str], selector: str,
                     max_text: int = 4000) -> Iterator[Node]:
    """Yield the nearest container ancestor of each element matching `selector`.

    For listing pages: given every event link, find the <li>/<article>/<div>
    that wraps it — without the fragile "climb N parents until the text looks
    big enough" heuristic that returned zero against the live site.

    SECOND selectolax TRAP (this cost a rewrite): its Node objects are
    **recreated on every access**, so identity comparison is meaningless —
    `a is not b` is True even when a and b are the same element:

        [c for c in node.css("div") if c is not node]   # never excludes self!

    So we can't dedup or self-exclude by identity. We walk UP from each match
    instead, which needs neither.
    """
    seen_html: set[str] = set()
    for match in tree.css(selector):
        node = match.parent
        card = None
        while node is not None:
            if node.tag in container_tags:
                text = node.text() or ""
                if len(text) <= max_text:
                    card = node
                    break
                # Too big to be a card (nav/footer wrapper) — stop climbing.
                break
            node = node.parent
        if card is None:
            continue
        key = card.html or ""
        if key in seen_html:
            continue
        seen_html.add(key)
        yield card
