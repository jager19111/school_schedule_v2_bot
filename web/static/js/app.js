/* web/static/js/app.js
 *
 * Phase 6/7 glue (без business logic):
 * - регистрация Service Worker (PWA);
 * - foreground revalidation (ТЗ 51.13): visibilitychange + Safari BFCache;
 * - SSE-реакция (ТЗ 51.4): #live-monitor выполняет hx-get на событие
 *   sse:schedule_changed, после ответа — revalidate текущего экрана;
 * - polling fallback (ТЗ 51.12): если SSE-соединение отсутствует
 *   (body без htmx-request), обновляем экран раз в 60 сек;
 * - logout: очистка Cache Storage.
 */

(function () {
  "use strict";

  var POLLING_FALLBACK_MS = 60000;

  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
  }

  function revalidateCurrentScreen() {
    // Персональные страницы всегда network-only в SW. Reload безопаснее,
    // чем ручное конструирование URL и не использует browser Date.
    if (document.visibilityState !== "visible") return;
    // Принудительная навигация пробивает BFCache в Safari лучше, чем .reload()
    window.location.href = window.location.pathname + window.location.search;
  }

  function sseConnected() {
    var host = document.body;
    return !!(host && host.classList && host.classList.contains("htmx-request"));
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/" })
        .then(function(registration) {
          // Принудительно проверяем обновления SW при каждом открытии
          registration.update();
        })
        .catch(function () { /* PWA не ломает приложение */ });
    });
  }

  function setupLiveUpdates() {
    var monitor = document.getElementById("live-monitor");

    if (monitor) {
      monitor.addEventListener("htmx:afterRequest", function (event) {
        if (event.detail && event.detail.elt === monitor &&
            event.detail.failed !== true) {
          revalidateCurrentScreen();
        }
      });
    }

    // Контракт для будущих интеграций (прямой SSE-клиент и т.п.).
    document.addEventListener("schedule:revalidate", revalidateCurrentScreen);

    // Polling fallback (ТЗ 51.12): SSE недоступен — периодическое
    // обновление текущего экрана, пока вкладка видима.
    window.setInterval(function () {
      if (document.visibilityState === "visible" && !sseConnected()) {
        revalidateCurrentScreen();
      }
    }, POLLING_FALLBACK_MS);

    // ГЛОБАЛЬНЫЙ ПЕРЕХВАТ ОШИБОК HTMX
    // Если мы нажали кнопку в момент рестарта бота
    document.body.addEventListener('htmx:responseError', function(evt) {
        if (evt.detail.xhr.status >= 500) window.location.reload();
    });
    
    // Если пропал интернет на телефоне
    document.body.addEventListener('htmx:sendError', function(evt) {
        window.location.reload();
    });
  }

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      revalidateCurrentScreen();
    }
  });

  window.addEventListener("pageshow", function (event) {
    // Safari back-forward cache: страница может быть восстановлена устаревшей.
    if (event.persisted) revalidateCurrentScreen();
  });

  // Logout: удалить shell-кэши (там нет персональных данных — defence in depth).
  document.addEventListener("htmx:afterRequest", function (event) {
    var path = event.detail && event.detail.requestConfig && event.detail.requestConfig.path;
    if (path === "/api/v1/auth/logout" || path === "/api/v1/auth/logout-all") {
      if ("caches" in window) {
        caches.keys().then(function (keys) {
          return Promise.all(keys.map(function (key) { return caches.delete(key); }));
        });
      }
    }
  });

  registerServiceWorker();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setupLiveUpdates);
  } else {
    setupLiveUpdates();
  }

  window.schoolSchedulePwa = {
    isStandalone: isStandalone,
    revalidate: revalidateCurrentScreen,
    sseConnected: sseConnected
  };
})();