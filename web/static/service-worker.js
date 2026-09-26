/* web/static/service-worker.js
 *
 * Phase 6 PWA — static shell only (ТЗ 39, 49).
 *
 * СТРОГО НЕ кэшируем персональные страницы/API. Один URL может означать
 * данные разных users/sessions, поэтому Cache Storage нельзя использовать
 * для /, /schedule/*, /family/*, /extra-classes/* или /api/v1/*.
 *
 * Кэш: CSS, JS, manifest, icons, offline shell. Версия меняется при
 * обновлении любого списка файлов (deployment обязан bump CACHE_VERSION).
 */

"use strict";

const CACHE_VERSION = "school-schedule-shell-v1";
const SHELL_ASSETS = [
  "/offline.html",
  "/manifest.webmanifest",
  "/static/css/app.css",
  "/static/js/htmx.min.js",
  "/static/js/app.js",
  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-512.png",
  "/static/icons/apple-touch-icon.png"
];

function isPersonal(url) {
  return (
    url.pathname === "/" ||
    url.pathname.startsWith("/schedule/") ||
    url.pathname.startsWith("/school/") ||
    url.pathname.startsWith("/family") ||
    url.pathname.startsWith("/extra") ||
    url.pathname.startsWith("/api/") ||
    url.pathname === "/auth"
  );
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches.open(CACHE_VERSION)
      .then(function (cache) { return cache.addAll(SHELL_ASSETS); })
      .then(function () { return self.skipWaiting(); })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches.keys()
      .then(function (keys) {
        return Promise.all(
          keys
            .filter(function (key) { return key !== CACHE_VERSION; })
            .map(function (key) { return caches.delete(key); })
        );
      })
      .then(function () { return self.clients.claim(); })
  );
});

self.addEventListener("fetch", function (event) {
  const request = event.request;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  // Network-only: невозможно случайно выдать User B данные User A.
  if (isPersonal(url)) {
    event.respondWith(
      fetch(request).catch(function () {
        // Только navigation получает нейтральный offline shell.
        // Персональное расписание не подменяется snapshot'ом.
        if (request.mode === "navigate") {
          return caches.match("/offline.html");
        }
        return Response.error();
      })
    );
    return;
  }

  // Cache-first только для строго static shell assets. При cache miss — сеть;
  // успешный static response добавляется в cache для следующего открытия.
  if (url.pathname.startsWith("/static/") ||
      url.pathname === "/manifest.webmanifest" ||
      url.pathname === "/offline.html") {
    event.respondWith(
      caches.match(request).then(function (cached) {
        if (cached) return cached;
        return fetch(request).then(function (response) {
          if (response.ok) {
            const copy = response.clone();
            caches.open(CACHE_VERSION).then(function (cache) {
              cache.put(request, copy);
            });
          }
          return response;
        });
      })
    );
  }
});