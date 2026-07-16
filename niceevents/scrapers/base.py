"""Scraper base classes + registry.

Two flavours:
  HttpScraper      — source ships real HTML/JSON. Fast, no browser.
  BrowserScraper   — source renders in JS. Needs Playwright.

A scraper that raises is logged and skipped; one broken source must never take
the whole run down.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from typing import Iterator, Optional

import httpx

from ..models import Event

log = logging.getLogger(__name__)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

REGISTRY: dict[str, type["Scraper"]] = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls


class Scraper(ABC):
    name: str = "base"
    label: str = "Base"
    needs_browser: bool = False
    #: be a good citizen — seconds between requests to the same host
    delay: float = 1.0

    @abstractmethod
    def fetch(self) -> Iterator[Event]:
        ...


class HttpScraper(Scraper):
    """HTTP-backed source.

    The httpx client is built on first use, not in __init__. Constructing a
    scraper should be free: merely naming one shouldn't open a connection pool,
    read proxy environment variables, or import optional transport backends.
    (It used to, which made the pure mapping logic untestable — instantiating a
    scraper inside a test blew up on a SOCKS proxy var that had nothing to do
    with the code under test.)
    """

    def __init__(self, timeout: float = 30.0):
        self._timeout = timeout
        self._client: Optional[httpx.Client] = None
        self._last = 0.0

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                timeout=self._timeout,
                follow_redirects=True,
                headers={
                    "User-Agent": UA,
                    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
                },
            )
        return self._client

    def get(self, url: str, **kw) -> Optional[httpx.Response]:
        gap = time.monotonic() - self._last
        if gap < self.delay:
            time.sleep(self.delay - gap)
        try:
            r = self.client.get(url, **kw)
            self._last = time.monotonic()
            if r.status_code >= 400:
                log.warning("%s: %s -> HTTP %s", self.name, url, r.status_code)
                return None
            return r
        except httpx.HTTPError as e:
            log.warning("%s: %s -> %s", self.name, url, e)
            return None

    def close(self):
        # Don't touch the property — closing a scraper that never fetched
        # anything shouldn't create a client just to shut it again.
        if self._client is not None:
            self._client.close()
            self._client = None


class BrowserScraper(Scraper):
    """Playwright-backed. Import is lazy so the static scrapers run without it."""
    needs_browser = True
    delay = 2.0

    def __init__(self, headless: bool = True, timeout_ms: int = 45000):
        self.headless = headless
        self.timeout_ms = timeout_ms

    def _page_text(self, url: str, wait_for: Optional[str] = None,
                   scroll: int = 0) -> Optional[str]:
        """Render a page and hand back its HTML."""
        from playwright.sync_api import sync_playwright  # noqa: local import on purpose

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            ctx = browser.new_context(
                user_agent=UA,
                locale="fr-FR",
                viewport={"width": 1440, "height": 1000},
            )
            page = ctx.new_page()
            try:
                page.goto(url, timeout=self.timeout_ms, wait_until="domcontentloaded")
                if wait_for:
                    try:
                        page.wait_for_selector(wait_for, timeout=15000)
                    except Exception:
                        log.warning("%s: selector %r never appeared on %s",
                                    self.name, wait_for, url)
                for _ in range(scroll):
                    page.mouse.wheel(0, 4000)
                    page.wait_for_timeout(900)
                page.wait_for_timeout(1200)
                return page.content()
            except Exception as e:
                log.warning("%s: render failed for %s -> %s", self.name, url, e)
                return None
            finally:
                ctx.close()
                browser.close()
