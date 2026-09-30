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

  var POLLING_FALLBACK_MS = 60 * 1000;
  var pendingScheduleRevalidation = false;
  
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
    /*
    * SSE event может прийти в background tab. Нельзя reload hidden tab
    * немедленно: browser может заморозить page, а user не увидит update.
    *
    * Вместо потери invalidation сохраняем pending flag и reload выполняется
    * при следующем foreground.
    */
    if (document.visibilityState !== "visible") {
      pendingScheduleRevalidation = true;
      return;
    }

    /*
    * Открытая форма важнее мгновенного reload. Сохраняем pending state:
    * после cancel/submit либо следующего foreground current page получит
    * fresh authenticated response.
    */
    if (hasProtectedLiveForm()) {
      pendingScheduleRevalidation = true;
      return;
    }

    pendingScheduleRevalidation = false;
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
      /*
       * Session revoked — отдельный server-authoritative event.
       *
       * Не ждём HTMX 401 и не пытаемся reload current private page:
       * server-side session уже revoked, поэтому browser должен сразу
       * перейти на public auth gate.
       *
       * Event приходит только из authenticated same-origin SSE stream.
       * Даже если client-side JS искусственно dispatch'ит event, это
       * влияет только на собственный UI и не открывает доступ к данным.
       */
      /*
       * ScheduleChanged → hx-trigger на #live-monitor →
       * GET /api/v1/live/revalidate → 204 →
       * authenticated reload текущего экрана.
       */
      monitor.addEventListener("htmx:afterRequest", function (event) {
        var path =
          event.detail &&
          event.detail.requestConfig &&
          event.detail.requestConfig.path;

        if (
          path === "/api/v1/live/revalidate" &&
          event.detail.failed !== true
        ) {
          revalidateCurrentScreen();
        }
      });
    }

    /*
     * SessionRevoked посылает event в #live-monitor.
     * Его hx-get идёт на /api/v1/live/revalidate, но server-side session
     * уже revoked, поэтому endpoint отвечает JSON 401.
     *
     * Обычный SSE network disconnect сюда не попадёт: redirect происходит
     * только после authenticated request с явным 401 response.
     */

    // Контракт для будущих интеграций (прямой SSE-клиент и т.п.).
    document.addEventListener("schedule:revalidate", revalidateCurrentScreen);

    // Polling fallback (ТЗ 51.12): SSE недоступен — периодическое
    // обновление текущего экрана, пока вкладка видима.
    window.setInterval(function () {
      /*
      * Polling нужен только для standalone PWA, где ОС может оборвать SSE
      * в background. В browser tab SSE сам делает reconnect, а reload раз
      * Polling fallback выполняется раз в 60 секунд только в standalone PWA,
        когда htmx SSE connection отсутствует.
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

  document.addEventListener("visibilitychange", function () {
    if (document.visibilityState !== "visible") {
      return;
    }

    /*
    * Browser tab могла получить ScheduleChanged в background.
    * После возврата user должен увидеть current schedule, а не stale HTML.
    */
    if (pendingScheduleRevalidation) {
      revalidateCurrentScreen();
      return;
    }

    /*
    * Standalone PWA может быть заморожена ОС, потерять SSE или сменить
    * сеть в background. Для неё revalidation на foreground обязательна
    * даже без уже обработанного SSE event.
    */
    if (isStandalone()) {
      revalidateCurrentScreen();
    }
  });

  window.addEventListener("pageshow", function (event) {
    /*
    * Safari BFCache может вернуть старый document уже после missed
    * ScheduleChanged. Pending flag покрывает известный event, standalone
    * PWA покрывает OS freeze/network restoration.
    */
    if (
      event.persisted &&
      (
        pendingScheduleRevalidation ||
        isStandalone()
      )
    ) {
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
