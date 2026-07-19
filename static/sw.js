/* Service worker — makes the site installable and usable offline.
 *
 * Strategy, chosen for a site whose data refreshes daily:
 *   - Navigation + events.json  -> NETWORK FIRST. Online visitors always get the
 *     freshest listings; offline, they fall back to the last cached copy so the
 *     app still opens on the métro with no signal.
 *   - Static assets (icons, manifest) -> CACHE FIRST. They never change within a
 *     release, so serve them instantly.
 *
 * Bump CACHE when the shell changes so old caches are cleaned out on activate.
 */
const CACHE = "nice-events-v1";
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

function networkFirst(req) {
  return fetch(req)
    .then((res) => {
      // Stash a fresh copy for offline use (only same-origin GETs).
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

  const isAsset = /\.(png|ico|webmanifest|svg)$/.test(url.pathname);
  e.respondWith(isAsset ? cacheFirst(req) : networkFirst(req));
});
