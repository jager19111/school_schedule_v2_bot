/* web/static/js/app.js
 *
 * Phase 6 PWA glue (без business logic):
 * - регистрация Service Worker;
 * - foreground revalidation текущего экрана (ТЗ 51.13);
 * - revalidation после HTMX/SSE event (SSE добавится Phase 7);
 * - очистка application caches при logout.
 */

(function () {
  "use strict";

  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
  }

  function revalidateCurrentScreen() {
    // Персональные страницы всегда network-only в SW. Reload безопаснее,
    // чем ручное конструирование URL и не использует browser Date.
    if (document.visibilityState !== "visible") return;
    window.location.reload();
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/" })
        .catch(function () {
          // Регистрация PWA не должна ломать основное приложение.
        });
    });
  }

  // iOS/Android могут заморозить PWA в background, оборвать SSE и сменить
  // сеть. Возврат в foreground всегда запрашивает backend заново.
  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState === "visible") {
      revalidateCurrentScreen();
    }
  });

  window.addEventListener("pageshow", function (event) {
    // Safari back-forward cache: page может быть восстановлена устаревшей.
    if (event.persisted) revalidateCurrentScreen();
  });

  // Контракт с Phase 7: htmx SSE handler может dispatchEvent(new Event(...)).
  document.addEventListener("schedule:revalidate", revalidateCurrentScreen);

  // Logout: удалить shell-кэши не обязательно для безопасности (там нет
  // персональных данных), но помогает не оставлять state приложения.
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
  window.schoolSchedulePwa = { isStandalone: isStandalone, revalidate: revalidateCurrentScreen };
})();
