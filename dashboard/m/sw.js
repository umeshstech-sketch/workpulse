// Offline shell for the WorkPulse mobile app. Data always comes live from the laptop (never cached).
const SHELL = "wp-shell-v2";
const FILES = ["/m/", "/m/m.css", "/m/m.js", "/m/manifest.webmanifest", "/m/icon-192.png"];
self.addEventListener("install", (e) => e.waitUntil(caches.open(SHELL).then((c) => c.addAll(FILES))));
self.addEventListener("activate", (e) => e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== SHELL).map((k) => caches.delete(k))))));
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (url.pathname.startsWith("/api/")) return;  // live data only
  e.respondWith(fetch(e.request).catch(() => caches.match(e.request)));
});
