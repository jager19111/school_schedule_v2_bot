/* web/static/js/app.js
 *
- Общий PWA/runtime glue без business logic.
 *
- Возможности:
- регистрация Service Worker;
- SSE invalidation;
- foreground revalidation для standalone PWA;
- Safari BFCache handling;
- polling fallback при отсутствии SSE;
- logout cache cleanup.
 *
- Важно:
- revalidation НЕ использует window.location.reload().
- Вместо этого обновляется только #app-shell через HTMX, поэтому:
 *
- document не выгружается;
- #live-monitor и SSE connection сохраняются;
- global JS listeners не регистрируются заново;
- PWA не показывает full-page flash при foreground.
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
  var lastWhiteScreenReloadAt = 0;


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
- На public/auth pages app shell может отсутствовать.
       *
- Здесь намеренно нет window.location.reload(): если protected shell
- отсутствует, приложение не должно самопроизвольно перезагружать
- текущий document.
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
- htmx.ajax отправляет обычный HTMX request:
     *
- HX-Request: true
- HX-Target: app-shell
     *
- Server-side select_page_or_fragment_template() вернёт full page.
- Option select извлечёт только #app-shell из response.
     *
- URL/history не меняются: revalidation обновляет уже открытую страницу.
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
- Background tab нельзя обновлять immediately: браузер может заморозить
- document, а пользователь не увидит результат. Сохраняем invalidation
- до следующего foreground.
     */
    if (document.visibilityState !== "visible") {
      queueScheduleRevalidation();
      return;
    }

    /*
- Открытая form важнее instant refresh. Form должна быть явно помечена:
     *
- data-live-refresh="defer"
     */
    if (hasProtectedLiveForm()) {
      queueScheduleRevalidation();
      return;
    }

    if (!runShellRevalidation()) {
      /*
- Если shell отсутствует, просто сохраняем pending state.
- Это безопаснее full document reload.
       */
      queueScheduleRevalidation();
    }
  }

  function sseConnected() {
    /*
- Основной источник состояния — собственные SSE lifecycle events.
     *
- body.htmx-request остаётся fallback для текущей версии htmx SSE
- extension и для initial transition до первого htmx:sseOpen.
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

    /*
   * CONNECTION LOST BANNER
   *
   * nginx-спиннер (proxy_intercept_errors) виден только при полной
   * навигации; HTMX-клики получают 503 без UI-фидбека. Этот баннер
   * закрывает разрыв для живой сессии.
   *
   * Показ: htmx:sendError / responseError (0, 502, 503, 504),
   * с debounce — hx-sync abort тоже fires sendError.
   * Скрытие: успешный afterRequest или sseOpen.
   */
  var CONNECTION_LOST_DELAY_MS = 1200;
  var connectionLostTimer = null;

  function showConnectionLost() {
    var banner = document.getElementById("connection-lost");
    if (banner) {
      banner.hidden = false;
    }
  }

  function hideConnectionLost() {
    var banner = document.getElementById("connection-lost");
    if (banner) {
      banner.hidden = true;
    }
  }

  function scheduleConnectionLost() {
    if (connectionLostTimer !== null) {
      return;
    }
    connectionLostTimer = window.setTimeout(function () {
      connectionLostTimer = null;
      showConnectionLost();
    }, CONNECTION_LOST_DELAY_MS);
  }

  function cancelConnectionLost() {
    if (connectionLostTimer !== null) {
      window.clearTimeout(connectionLostTimer);
      connectionLostTimer = null;
    }
    hideConnectionLost();
  }

  function isServerUnreachable(event) {
    var xhr = event.detail && event.detail.xhr;
    if (!xhr) {
      return true;
    }
    /* 0 — network error (в т.ч. Response.error() из Service Worker);
       502/503/504 — nginx без живого upstream (intercept_errors). */
    return (
      xhr.status === 0
      || xhr.status === 502
      || xhr.status === 503
      || xhr.status === 504
    );
  }

  function clearStuckRequestIndicator() {
    /* Защита от залипания skeleton при abort'е hx-sync запросов. */
    document.body.classList.remove("htmx-request");
  }

  function setupConnectionLostBanner() {
    document.body.addEventListener(
      "htmx:sendError",
      function () {
        clearStuckRequestIndicator();
        scheduleConnectionLost();
      }
    );

    document.body.addEventListener(
      "htmx:responseError",
      function (event) {
        if (isServerUnreachable(event)) {
          clearStuckRequestIndicator();
          scheduleConnectionLost();
        }
      }
    );

    document.body.addEventListener(
      "htmx:afterRequest",
      function (event) {
        if (!event.detail.failed) {
          cancelConnectionLost();
        }
      }
    );
  }
  
  function registerServiceWorker() {
    // Читаем метку surface из body, которую устанавливает бэкенд для Mini App
    var isTelegramSurface = document.body.dataset.surface === "telegram";

    // Регистрируем Service Worker только если это не Telegram и браузер его поддерживает
    if (!isTelegramSurface && "serviceWorker" in navigator) {
      window.addEventListener("load", function () {
        navigator.serviceWorker
          .register("/service-worker.js", { scope: "/" })
          .catch(function () {
            /*
- PWA enhancement не должен ломать application.
             */
          });
      });
    }
  }

  function cleanupTelegramServiceWorker() {
    // Одна из ранних версий Mini App успела зарегистрировать SW
    // в хранилище Telegram WebView. Убираем его, чтобы WebView не
    // проверял обновления и не получал закешированный shell.
    if (
      document.body.dataset.surface === "telegram"
      && "serviceWorker" in navigator
    ) {
      navigator.serviceWorker
        .getRegistrations()
        .then(function (registrations) {
          registrations.forEach(function (registration) {
            registration.unregister();
          });
        })
        .catch(function () {
          /* best-effort cleanup */
        });
    }
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
- htmx.ajax() является asynchronous.
     *
- Снимаем in-flight lock только после фактического request completion,
- а не через timeout. Это защищает PWA от concurrent SSE, foreground
- и polling revalidation requests.
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
- Во время текущего request мог прийти ещё один ScheduleChanged.
- После успешного swap запускаем один дополнительный refresh.
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
- htmx-ext-sse dispatches lifecycle events. Храним собственное состояние,
- не полагаясь только на CSS class htmx-request.
     */
    document.body.addEventListener(
      "htmx:sseOpen",
      function () {
        sseOpen = true;
        cancelConnectionLost();
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
        /*
         * SSE падает по трём причинам: сервер недоступен, сессия
         * отозвана (EventSource получает 401 на reconnect), краткий
         * рестарт деплоя. Баннер напрямую НЕ показываем — через 10 сек
         * revalidation разводит сценарии сама:
         * сервер недоступен -> sendError/503 -> баннер;
         * сессия отозвана  -> 401 -> HX-Redirect /auth.
         */
        window.setTimeout(function () {
          if (!sseOpen) {
            revalidateCurrentScreen();
          }
        }, 10000);
      }
    );
  }

  function setupLiveUpdates() {
    var monitor = document.getElementById("live-monitor");

    setupShellRevalidationLifecycle();
    setupSseLifecycle();

    /*
- SSE event:
     *
- schedule_changed
- → #live-monitor GET /api/v1/live/revalidate
- → successful response
- → мягкая revalidation current #app-shell.
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
- Контракт для будущих integrations:
     *
- document.dispatchEvent(new Event("schedule:revalidate"))
     */
    document.addEventListener(
      "schedule:revalidate",
      revalidateCurrentScreen
    );

    /*
- Polling нужен только standalone PWA:
- browser tab рассчитывает на normal SSE reconnect.
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
      - ЗАЩИТА ОТ "БЕЛОГО ЭКРАНА" В PWA (с Cooldown)
      - ОС может выгрузить DOM из памяти при нехватке ресурсов в спящем режиме.
      - Перезагружаем страницу, но не чаще чем раз в 10 секунд (защита от цикла).
      */
      if (isStandalone() && document.getElementById("app-shell") === null) {
        if (Date.now() - lastWhiteScreenReloadAt > 10000) {
          lastWhiteScreenReloadAt = Date.now();
          window.location.reload();
        }
        return;
      }
      /*
      - Если это обычная вкладка браузера (не PWA), то интернет никуда 
      - не пропадал, обновляем данные сразу без задержек.
      */
      if (!isStandalone() && pendingScheduleRevalidation) {
        revalidateCurrentScreen();
        return;
      }

      /*
      - ЗАДЕРЖКА НА ВОССТАНОВЛЕНИЕ СЕТИ ДЛЯ PWA
      - После "сна" смартфона модулю Wi-Fi/LTE нужно время на переподключение.
      */
      if (isStandalone()) {
        window.setTimeout(function () {
          revalidateCurrentScreen();
        }, 1000); 
      }
    }
  );

  /*
  - АВТО-ОБНОВЛЕНИЕ ПРИ ВОЗВРАТЕ ИНТЕРНЕТА
  */
  window.addEventListener(
    "online",
    function () {
      if (isStandalone() || pendingScheduleRevalidation) {
        window.setTimeout(revalidateCurrentScreen, 500);
      }
    }
  );

  window.addEventListener(
    "pageshow",
    function (event) {
      if (
        event.persisted
        && (
          pendingScheduleRevalidation
          || isStandalone()
        )
      ) {
        window.setTimeout(revalidateCurrentScreen, 300);
      }
    }
  );

  /*
- Logout: удалить shell caches.
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

  // --- Динамическая подмена бейджа для общих кук (iOS Safari + PWA) ---
  function applyPwaDeviceOverride() {
    if (!isStandalone()) {
      return;
    }

    var currentCard = document.querySelector('.device-card--current');
    if (!currentCard) return;

    var title = currentCard.querySelector('.device-card__title');
    var badge = currentCard.querySelector('.device-badge--browser');
    var tpl = document.getElementById('pwa-badge-template');
    
    if (badge && title && tpl) {
      title.textContent = 'Установленное PWA';
      badge.className = 'device-badge device-badge--pwa';
      badge.innerHTML = tpl.innerHTML;
    }
  }

  document.body.addEventListener("htmx:load", applyPwaDeviceOverride);

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", applyPwaDeviceOverride);
  } else {
    applyPwaDeviceOverride();
  }

  registerServiceWorker();
  cleanupTelegramServiceWorker();
  setupConnectionLostBanner();

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


    /* --- УВЕДОМЛЕНИЯ (TOASTS) --- */

  // 1. Мгновенное закрытие уведомления при тапе (клике) по нему
  document.addEventListener("click", function(event) {
    const toast = event.target.closest(".class-watch-toggle__error");
    if (toast) {
      toast.remove();
    }
  });

  // 2. Автоматическая очистка старых уведомлений при любой HTMX-навигации (перелистывание дней)
  document.body.addEventListener("htmx:beforeRequest", function() {
    document.querySelectorAll(".class-watch-toggle__error").forEach(function(toast) {
      toast.remove();
    });
  });

/* --- ДЕЛЕГИРОВАНИЕ КЛИКОВ (СЕМЬЯ) --- */
document.addEventListener("click", function(event) {
  // 1. Блокируем сворачивание аккордеона при клике на вложенную кнопку (например, "Отозвать")
  if (event.target.closest("summary") && event.target.closest("button")) {
    event.preventDefault();
  }

  // 2. Копирование длинной ссылки
  const linkBtn = event.target.closest(".js-copy-invite");
  if (linkBtn) {
    const link = linkBtn.dataset.link;
    if (!link || linkBtn.classList.contains("copied")) return;
    
    navigator.clipboard.writeText(link).then(() => {
      linkBtn.classList.add("copied");
      setTimeout(() => linkBtn.classList.remove("copied"), 2500);
    });
    return;
  }

  // 3. Копирование короткого кода
  const codeBtn = event.target.closest(".js-copy-code");
  if (codeBtn) {
    const code = codeBtn.dataset.code;
    if (!code || codeBtn.classList.contains("copied")) return;

    navigator.clipboard.writeText(code).then(() => {
      codeBtn.classList.add("copied");
      setTimeout(() => codeBtn.classList.remove("copied"), 2000);
    });
  }
});

})();