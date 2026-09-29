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

  var POLLING_FALLBACK_MS = 5 * 60 * 1000;

  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches ||
      window.navigator.standalone === true;
  }

  function hasProtectedLiveForm() {
    return document.querySelector(
      'form[data-live-refresh="defer"]'
    ) !== null;
  }

  function revalidateCurrentScreen() {
    // Не обновляем background tab.
    if (document.visibilityState !== "visible") return;

    /*
    * Открытая форма важнее background schedule update.
    *
    * Не показываем banner, не уведомляем пользователя и не копим pending
    * reload: после submit/cancel следующий server response или navigation
    * всё равно даст fresh data.
    */
    if (hasProtectedLiveForm()) return;

    window.location.reload();
  }

  function sseConnected() {
    // htmx-ext-sse держит класс htmx-request на sse-connect элементе
    // (body), пока соединение открыто. Это documented поведение
    // long-lived SSE connections в htmx.
    var host = document.body;
    return !!(host && host.classList && host.classList.contains("htmx-request"));
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) return;
    window.addEventListener("load", function () {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/" })
        .catch(function () { /* PWA не ломает приложение */ });
    });
  }

  function setupLiveUpdates() {
    var monitor = document.getElementById("live-monitor");

    // SSE invalidation -> лёгкий hx-get (204) -> revalidate (ТЗ 51.4).
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
      /*
      * Polling нужен только для standalone PWA, где ОС может оборвать SSE
      * в background. В browser tab SSE сам делает reconnect, а reload раз
      * в минуту слишком агрессивен.
      */
      if (!isStandalone()) return;

      if (
        document.visibilityState === "visible"
        && !sseConnected()
      ) {
        revalidateCurrentScreen();
      }
    }, POLLING_FALLBACK_MS);
  }

  // iOS/Android могут заморозить PWA в background, оборвать SSE и сменить
  // сеть. Возврат в foreground всегда запрашивает backend заново.
  document.addEventListener("visibilitychange", function () {
    /*
    * Foreground revalidation нужна прежде всего standalone PWA:
    * iOS/Android могут заморозить приложение, оборвать SSE или сменить сеть.
    *
    * В обычной browser tab это слишком агрессивно:
    * пользователь часто переключается между вкладками во время работы.
    */
    if (
      isStandalone()
      && document.visibilityState === "visible"
    ) {
      revalidateCurrentScreen();
    }
  });

  window.addEventListener("pageshow", function (event) {
    /*
    * BFCache revalidation полезна в standalone PWA.
    * В обычном browser history пользователь ожидает увидеть сохранённый
    * state страницы, особенно если вернулся к форме.
    */
    if (isStandalone() && event.persisted) {
      revalidateCurrentScreen();
    }
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
