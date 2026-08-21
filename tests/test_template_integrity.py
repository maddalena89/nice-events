"""The built page is actually a page.

Written after a blank site got past a green test suite.

A CSS rule of the form "@media(...){#id{...}}" contains the two characters that
open a Jinja comment. Jinja scans raw text, so it does not care that they sit
inside CSS — or inside a CSS comment. It opens a comment and, finding no close,
swallows the entire rest of the template. The build succeeds, writes a file of a
plausible size (most of the weight is the inline event data, which survives),
and reports the right event count. Every test passed. The site rendered a blank
page.

Nothing here is clever; it is the set of things whose absence means the page is
broken in a way no other test notices.
"""
import re
from pathlib import Path

import pytest

TPL_DIR = Path(__file__).resolve().parent.parent / "templates"
TEMPLATES = sorted(TPL_DIR.glob("*.jinja"))


@pytest.mark.parametrize("tpl", TEMPLATES, ids=lambda p: p.name)
def test_jinja_comment_markers_are_balanced(tpl):
    """The failure this file exists for, caught at its source.

    An id selector placed directly after an opening brace is the usual culprit;
    a space between them fixes it and changes nothing about the CSS.
    """
    text = tpl.read_text(encoding="utf-8")
    opens = text.count("{#")
    closes = text.count("#}")
    if opens == closes:
        return
    lines = [
        (i, ln.strip())
        for i, ln in enumerate(text.splitlines(), 1)
        if "{#" in ln and "#}" not in ln and not ln.strip().startswith("{#")
    ]
    pytest.fail(
        f"{tpl.name}: {opens} '<brace><hash>' vs {closes} closers — an unclosed "
        f"Jinja comment swallows the rest of the template.\n"
        f"Likely CSS, not a comment, on these lines: {lines or 'unknown'}"
    )


def _build_page(tmp_path):
    from niceevents import db
    from niceevents.site import build
    out = tmp_path / "dist"
    with db.connect(tmp_path / "t.db") as conn:
        build(conn, out_dir=str(out))
    return (out / "index.html").read_text(encoding="utf-8")


def test_built_page_has_its_structure(tmp_path):
    """An empty database still has to produce a whole page — the chrome, the
    filters and the scripts do not depend on there being any events."""
    html = _build_page(tmp_path)
    for needle in ("<body>", "</body>", "</html>", 'class="wrap"',
                   'id="list"', 'id="town-btn"', 'id="when"',
                   '<script id="data"', "function render()"):
        assert needle in html, f"missing from built page: {needle}"


def test_built_page_is_not_truncated(tmp_path):
    """Everything after a swallowed comment vanishes, so the tail is the tell."""
    html = _build_page(tmp_path)
    assert html.rstrip().endswith("</html>")
    # The closing tags must come after the app script, not before it.
    assert html.index('<script id="data"') < html.index("</body>")


def test_style_block_is_closed_and_substantial(tmp_path):
    html = _build_page(tmp_path)
    styles = re.findall(r"<style>(.*?)</style>", html, re.S)
    assert len(styles) == 1, f"expected one <style> block, found {len(styles)}"
    assert len(styles[0]) > 10_000, "stylesheet looks truncated"
