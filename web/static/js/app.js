/* web/static/js/app.js
 *
 * Общий PWA/runtime glue без business logic.
 *
 * Возможности:
 * - регистрация Service Worker;
 * - SSE invalidation;
 * - foreground revalidation для standalone PWA;
 * - Safari BFCache handling;
 * - polling fallback при отсутствии SSE;
 * - logout cache cleanup.
 *
 * Важно:
 * revalidation НЕ использует window.location.reload().
 * Вместо этого обновляется только #app-shell через HTMX, поэтому:
 *
 * - document не выгружается;
 * - #live-monitor и SSE connection сохраняются;
 * - global JS listeners не регистрируются заново;
 * - PWA не показывает full-page flash при foreground.
 */

(function () {
  "use strict";

  if (window.schoolSchedulePwaInstalled) {
    return;
  }

  window.schoolSchedulePwaInstalled = true;

  var POLLING_FALLBACK_MS = 60 * 1000;

  var pendingScheduleRevalidation = false;
  var shellRevalidationInFlight = false;
  var sseOpen = false;

  function isStandalone() {
    return (
      window.matchMedia("(display-mode: standalone)").matches
      || window.navigator.standalone === true
    );
  }

  function hasProtectedLiveForm() {
    return document.querySelector(
      'form[data-live-refresh="defer"]'
    ) !== null;
  }

  function getCurrentScreenUrl() {
    return (
      window.location.pathname
      + window.location.search
    );
  }

  function getAppShell() {
    var shell = document.getElementById("app-shell");

    return shell instanceof Element
      ? shell
      : null;
  }

  function getShellRevalidationSource() {
    var source = document.getElementById(
      "shell-revalidation"
    );

    return source instanceof Element
      ? source
      : null;
  }

  function canUseShellRevalidation() {
    return (
      typeof window.htmx !== "undefined"
      && typeof window.htmx.ajax === "function"
      && getAppShell() !== null
      && getShellRevalidationSource() !== null
    );
  }

  function queueScheduleRevalidation() {
    pendingScheduleRevalidation = true;
  }

  function runShellRevalidation() {
    var source = getShellRevalidationSource();

    if (!source || !canUseShellRevalidation()) {
      /*
       * На public/auth pages app shell может отсутствовать.
       *
       * Здесь намеренно нет window.location.reload(): если protected shell
       * отсутствует, приложение не должно самопроизвольно перезагружать
       * текущий document.
       */
      return false;
    }

    if (shellRevalidationInFlight) {
      queueScheduleRevalidation();
      return true;
    }

    shellRevalidationInFlight = true;
    pendingScheduleRevalidation = false;

    /*
     * htmx.ajax отправляет обычный HTMX request:
     *
     * HX-Request: true
     * HX-Target: app-shell
     *
     * Server-side select_page_or_fragment_template() вернёт full page.
     * Option select извлечёт только #app-shell из response.
     *
     * URL/history не меняются: revalidation обновляет уже открытую страницу.
     */
    window.htmx.ajax(
      "GET",
      getCurrentScreenUrl(),
      {
        source: source,
        target: "#app-shell",
        select: "#app-shell",
        swap: "outerHTML",
        headers: {
          "HX-Target": "app-shell",
        },
      }
    );

    return true;
  }

  function revalidateCurrentScreen() {
    /*
     * Background tab нельзя обновлять immediately: браузер может заморозить
     * document, а пользователь не увидит результат. Сохраняем invalidation
     * до следующего foreground.
     */
    if (document.visibilityState !== "visible") {
      queueScheduleRevalidation();
      return;
    }

    /*
     * Открытая form важнее instant refresh. Form должна быть явно помечена:
     *
     * data-live-refresh="defer"
     */
    if (hasProtectedLiveForm()) {
      queueScheduleRevalidation();
      return;
    }

    if (!runShellRevalidation()) {
      /*
       * Если shell отсутствует, просто сохраняем pending state.
       * Это безопаснее full document reload.
       */
      queueScheduleRevalidation();
    }
  }

  function sseConnected() {
    /*
     * Основной источник состояния — собственные SSE lifecycle events.
     *
     * body.htmx-request остаётся fallback для текущей версии htmx SSE
     * extension и для initial transition до первого htmx:sseOpen.
     */
    var host = document.body;

    return (
      sseOpen
      || !!(
        host
        && host.classList
        && host.classList.contains("htmx-request")
      )
    );
  }

  function registerServiceWorker() {
    if (!("serviceWorker" in navigator)) {
      return;
    }

    window.addEventListener("load", function () {
      navigator.serviceWorker
        .register("/service-worker.js", { scope: "/" })
        .catch(function () {
          /*
           * PWA enhancement не должен ломать application.
           */
        });
    });
  }

  function isShellRevalidationRequest(event) {
    var source = getShellRevalidationSource();

    return !!(
      source
      && event.detail
      && event.detail.elt === source
    );
  }

  function setupShellRevalidationLifecycle() {
    /*
     * htmx.ajax() является asynchronous.
     *
     * Снимаем in-flight lock только после фактического request completion,
     * а не через timeout. Это защищает PWA от concurrent SSE, foreground
     * и polling revalidation requests.
     */
    document.body.addEventListener(
      "htmx:afterRequest",
      function (event) {
        if (!isShellRevalidationRequest(event)) {
          return;
        }

        shellRevalidationInFlight = false;

        if (event.detail.failed === true) {
          queueScheduleRevalidation();
          return;
        }

        /*
         * Во время текущего request мог прийти ещё один ScheduleChanged.
         * После успешного swap запускаем один дополнительный refresh.
         */
        if (
          pendingScheduleRevalidation
          && document.visibilityState === "visible"
          && !hasProtectedLiveForm()
        ) {
          window.setTimeout(
            revalidateCurrentScreen,
            0
          );
        }
      }
    );

    [
      "htmx:responseError",
      "htmx:sendError",
      "htmx:timeout",
    ].forEach(function (eventName) {
      document.body.addEventListener(
        eventName,
        function (event) {
          if (!isShellRevalidationRequest(event)) {
            return;
          }

          shellRevalidationInFlight = false;
          queueScheduleRevalidation();
        }
      );
    });
  }

  function setupSseLifecycle() {
    /*
     * htmx-ext-sse dispatches lifecycle events. Храним собственное состояние,
     * не полагаясь только на CSS class htmx-request.
     */
    document.body.addEventListener(
      "htmx:sseOpen",
      function () {
        sseOpen = true;
      }
    );

    document.body.addEventListener(
      "htmx:sseClose",
      function () {
        sseOpen = false;
      }
    );

    document.body.addEventListener(
      "htmx:sseError",
      function () {
        sseOpen = false;
      }
    );
  }

  function setupLiveUpdates() {
    var monitor = document.getElementById("live-monitor");

    setupShellRevalidationLifecycle();
    setupSseLifecycle();

    /*
     * SSE event:
     *
     * schedule_changed
     * → #live-monitor GET /api/v1/live/revalidate
     * → successful response
     * → мягкая revalidation current #app-shell.
     */
    if (monitor) {
      monitor.addEventListener(
        "htmx:afterRequest",
        function (event) {
          var path = (
            event.detail
            && event.detail.requestConfig
            && event.detail.requestConfig.path
          );

          if (
            path === "/api/v1/live/revalidate"
            && event.detail.failed !== true
          ) {
            revalidateCurrentScreen();
          }
        }
      );
    }

    /*
     * Контракт для будущих integrations:
     *
     * document.dispatchEvent(new Event("schedule:revalidate"))
     */
    document.addEventListener(
      "schedule:revalidate",
      revalidateCurrentScreen
    );

    /*
     * Polling нужен только standalone PWA:
     * browser tab рассчитывает на normal SSE reconnect.
     */
    window.setInterval(function () {
      if (!isStandalone()) {
        return;
      }

      if (
        document.visibilityState === "visible"
        && !sseConnected()
      ) {
        revalidateCurrentScreen();
      }
    }, POLLING_FALLBACK_MS);
  }

  document.addEventListener(
    "visibilitychange",
    function () {
      if (document.visibilityState !== "visible") {
        return;
      }

      /*
       * Background tab получила invalidation.
       */
      if (pendingScheduleRevalidation) {
        revalidateCurrentScreen();
        return;
      }

      /*
       * Standalone PWA может потерять SSE из-за OS freeze, смены сети или
       * background suspension. При foreground revalidate всегда выполняется.
       */
      if (isStandalone()) {
        revalidateCurrentScreen();
      }
    }
  );

  window.addEventListener(
    "pageshow",
    function (event) {
      /*
       * Safari BFCache может вернуть старый DOM document.
       */
      if (
        event.persisted
        && (
          pendingScheduleRevalidation
          || isStandalone()
        )
      ) {
        revalidateCurrentScreen();
      }
    }
  );

  /*
   * Logout: удалить shell caches.
   *
   * Персональные routes не кэшируются Service Worker, но очистка Cache
   * Storage остаётся дополнительной защитой при logout.
   */
  document.addEventListener(
    "htmx:afterRequest",
    function (event) {
      var path = (
        event.detail
        && event.detail.requestConfig
        && event.detail.requestConfig.path
      );

      if (
        path !== "/api/v1/auth/logout"
        && path !== "/api/v1/auth/logout-all"
      ) {
        return;
      }

      if (!("caches" in window)) {
        return;
      }

      caches.keys().then(function (keys) {
        return Promise.all(
          keys.map(function (key) {
            return caches.delete(key);
          })
        );
      });
    }
  );

  registerServiceWorker();

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      setupLiveUpdates,
      { once: true }
    );
  } else {
    setupLiveUpdates();
  }

  window.schoolSchedulePwa = {
    isStandalone: isStandalone,
    revalidate: revalidateCurrentScreen,
    sseConnected: sseConnected
  };
})();