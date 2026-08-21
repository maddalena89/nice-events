/* Service worker — makes the site installable, fast on a return visit, and
 * usable offline.
 *
 * Strategy, chosen for a site whose data refreshes once a day:
 *   - Pages -> STALE WHILE REVALIDATE. The cached copy is served immediately,
 *     so a return visit paints without waiting for ~230KB over the network,
 *     and a fresh copy is fetched in the background for next time. Because
 *     "next time" is not good enough when today's listings have changed, the
 *     worker tells any open page when the copy it is showing has gone stale and
 *     the page offers a refresh. Without that nudge someone could sit looking
 *     at yesterday's events with no way to know.
 *   - Static assets (icons, manifest) -> CACHE FIRST. They never change within
 *     a release, so serve them instantly.
 *   - Everything else, i.e. the JSON feeds -> NETWORK FIRST. events.json is a
 *     public feed; anyone reading it wants today's data, not a cached copy.
 *
 * Bump CACHE when the shell changes so old caches are cleaned out on activate.
 */
const CACHE = "nice-events-v3";
const SHELL = ["./", "./index.html", "./manifest.webmanifest",
               "./icon-192.png", "./icon-512.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())
  );
});

self.addEventListener("activate", (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

/* Has the server's copy actually changed since the one we cached?
 *
 * ETag first, Last-Modified second — GitHub Pages sends both. Never guess "yes"
 * when neither header is present: this decides whether to interrupt a reader
 * with a refresh prompt, and a prompt that appears on every page view is worse
 * than no prompt at all. */
function hasChanged(cached, fresh) {
  const a = cached.headers, b = fresh.headers;
  const ea = a.get("etag"), eb = b.get("etag");
  if (ea && eb) return ea !== eb;
  const ma = a.get("last-modified"), mb = b.get("last-modified");
  if (ma && mb) return ma !== mb;
  return false;
}

/* URLs whose cached copy we have since found to be out of date.
 *
 * A set as well as a postMessage, because of a race that is easy to miss: the
 * revalidation finishes within milliseconds of handing over the cached page,
 * which is long before that page has parsed ~880KB of HTML and attached its
 * message listener. The push alone is therefore usually shouted into an empty
 * room. Pages ask on startup instead, and the push is kept for the case it does
 * work — a page that was already open when the revalidation happened.
 *
 * In memory, so it does not survive the worker being shut down. That is the
 * right trade: the page asks seconds after the fetch, and the worst case is a
 * missed prompt, not a wrong one. */
const stale = new Set();

function tellPages(url) {
  stale.add(url);
  self.clients.matchAll({ type: "window" }).then((cs) =>
    cs.forEach((c) => c.postMessage({ type: "content-updated", url }))
  );
}

self.addEventListener("message", (e) => {
  const d = e.data;
  if (!d || d.type !== "is-stale" || !e.source) return;
  if (stale.has(d.url)) {
    stale.delete(d.url);                       // ask once; the prompt is now the page's job
    e.source.postMessage({ type: "content-updated", url: d.url });
  }
});

function staleWhileRevalidate(req) {
  return caches.open(CACHE).then((cache) =>
    cache.match(req).then((cached) => {
      const fetching = fetch(req)
        .then((res) => {
          if (res && res.ok && req.method === "GET") {
            // Compare BEFORE the body is consumed by cache.put — headers are
            // readable either way, but the clone has to be taken first.
            const copy = res.clone();
            if (cached && hasChanged(cached, res)) tellPages(req.url);
            cache.put(req, copy);
          }
          return res;
        })
        // Offline: whatever we already have is the answer. If we have nothing,
        // fall back to the shell so the app still opens.
        .catch(() => cached || cache.match("./index.html"));
      // The whole point: hand back the cached copy at once when there is one,
      // and let the network catch up in the background.
      return cached || fetching;
    })
  );
}

function networkFirst(req) {
  return fetch(req)
    .then((res) => {
      if (res && res.ok && req.method === "GET") {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return res;
    })
    .catch(() => caches.match(req).then((hit) => hit || caches.match("./index.html")));
}

function cacheFirst(req) {
  return caches.match(req).then((hit) => hit || fetch(req).then((res) => {
    if (res && res.ok) {
      const copy = res.clone();
      caches.open(CACHE).then((c) => c.put(req, copy));
    }
    return res;
  }));
}

self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;                 // never touch form POSTs
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;       // let cross-origin (CDN, Supabase) pass through

  // A navigation to any page on the site — the home page or a town/category
  // landing page. request.destination is "document" for all of them.
  const isPage = req.mode === "navigate" || req.destination === "document";
  const isAsset = /\.(png|ico|webmanifest|svg)$/.test(url.pathname);
  e.respondWith(isPage ? staleWhileRevalidate(req)
                       : isAsset ? cacheFirst(req)
                                 : networkFirst(req));
});
