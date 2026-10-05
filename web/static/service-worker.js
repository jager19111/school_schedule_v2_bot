/* web/static/service-worker.js
 *
 * PWA static shell cache.
 *
 * Критическое правило безопасности:
 *
 * Персональные HTML screens и API никогда не попадают в Cache Storage.
 * Один URL может возвращать разные данные в зависимости от web session:
 *
 * - расписание;
 * - семья;
 * - выбранный ребёнок;
 * - дополнительные занятия;
 * - настройки;
 * - school data.
 *
 * Поэтому routes /, /schedule/*, /school/*, /family/*, /extra-classes/*,
 * /settings/*, /api/* и /auth/* всегда network-only.
 *
 * Кэшируются только versioned static assets и neutral offline page.
 */

"use strict";

/*
 * Версия меняется при любом изменении списка SHELL_ASSETS.
 *
 * При activate старые school-schedule-shell-* caches удаляются.
 */
const CACHE_VERSION = "school-schedule-shell-v7";

/*
 * URL должны ТОЧНО совпадать с URL из base.html.
 *
 * Query string является частью Cache Storage key:
 *
 * /static/js/app.js?v=7
 * !==
 * /static/js/app.js?v=5
 */
const SHELL_ASSETS = [
  "/offline.html",
  "/manifest.webmanifest",

  "/static/css/app.css?v=6",
  "/static/css/components/schedule.css?v=6",
  "/static/css/components/extra.css?v=6",

  "/static/js/htmx.min.js",
  "/static/js/htmx-ext-sse.min.js?v=3",
  "/static/js/app.js?v=7",
  "/static/js/schedule.js?v=7",
  "/static/js/extra.js?v=7",

  "/static/icons/icon-192.png",
  "/static/icons/icon-512.png",
  "/static/icons/icon-maskable-512.png",
  "/static/icons/apple-touch-icon.png",
];

function isPersonalRoute(url) {
  return (
    url.pathname === "/"
    || url.pathname.startsWith("/schedule/")
    || url.pathname.startsWith("/school/")
    || url.pathname.startsWith("/family")
    || url.pathname.startsWith("/extra-classes")
    || url.pathname.startsWith("/settings")
    || url.pathname.startsWith("/api/")
    || url.pathname.startsWith("/auth")
  );
}

function isStaticShellAsset(url) {
  return (
    url.pathname.startsWith("/static/")
    || url.pathname === "/manifest.webmanifest"
    || url.pathname === "/offline.html"
  );
}

self.addEventListener("install", function (event) {
  event.waitUntil(
    caches
      .open(CACHE_VERSION)
      .then(function (cache) {
        return cache.addAll(SHELL_ASSETS);
      })
      .then(function () {
        /*
         * Новый Service Worker не ждёт закрытия старых PWA windows.
         */
        return self.skipWaiting();
      })
  );
});

self.addEventListener("activate", function (event) {
  event.waitUntil(
    caches
      .keys()
      .then(function (keys) {
        return Promise.all(
          keys
            .filter(function (key) {
              return (
                key.startsWith("school-schedule-shell-")
                && key !== CACHE_VERSION
              );
            })
            .map(function (key) {
              return caches.delete(key);
            })
        );
      })
      .then(function () {
        /*
         * Новый worker берёт под контроль уже открытые pages/PWA windows.
         */
        return self.clients.claim();
      })
  );
});

self.addEventListener("fetch", function (event) {
  const request = event.request;

  if (request.method !== "GET") {
    return;
  }

  const url = new URL(request.url);

  if (url.origin !== self.location.origin) {
    return;
  }

  /*
   * Network-only для authenticated и персонализированных screens/API.
   *
   * Нельзя случайно вернуть User B content из Cache Storage,
   * ранее записанный User A.
   */
  if (isPersonalRoute(url)) {
    event.respondWith(
      fetch(request).catch(function () {
        /*
         * Offline page допустима только для native document navigation.
         *
         * Для HTMX fetch/xhr нельзя подставлять offline.html:
         * иначе fragment target получил бы полноценную offline page.
         */
        if (request.mode === "navigate") {
          return caches.match("/offline.html");
        }

        return Response.error();
      })
    );

    return;
  }

  /*
   * Cache-first только для безопасных static assets.
   *
   * Cache miss:
   * network → cache successful response → return response.
   */
  if (isStaticShellAsset(url)) {
    event.respondWith(
      caches.match(request).then(function (cached) {
        if (cached) {
          return cached;
        }

        return fetch(request).then(function (response) {
          if (response.ok) {
            const copy = response.clone();

            caches.open(CACHE_VERSION).then(function (cache) {
              return cache.put(request, copy);
            });
          }

          return response;
        });
      })
    );
  }
});