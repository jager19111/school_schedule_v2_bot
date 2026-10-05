/* web/static/js/schedule.js
 *
 * Общий UI runtime расписания.
 *
 * Файл загружается один раз из base.html и должен переживать HTMX-замену
 * #app-shell. Поэтому document-level listeners не привязаны к конкретному
 * #main, а каждый event работает с актуальным DOM в момент события.
 *
 * Возможности:
 * - autofit subject text;
 * - ResizeObserver для schedule containers;
 * - direct-manipulation swipe day navigation;
 * - inline details changed lessons;
 * - сохранение и плавное центрирование student-switch.
 */

(function () {
  "use strict";

  /*
   * Защита от повторной регистрации listeners.
   *
   * Сейчас schedule.js подключается глобально из base.html. Guard сохраняет
   * корректность и при случайном повторном включении файла в template.
   */
  if (window.schoolScheduleUiInstalled) {
    return;
  }

  window.schoolScheduleUiInstalled = true;

  var MIN_SIZE_PX = 12;
  var MAX_SIZE_PX = 21;
  var STEP_PX = 1;

  var resizeObserver = null;
  var observedContainers = new WeakSet();

  /* ------------------------------------------------------------------------
     Subject autofit
     ------------------------------------------------------------------------ */

  function fitSubject(element) {
    if (!(element instanceof HTMLElement)) {
      return;
    }

    /*
     * Текст всегда остаётся visible.
     *
     * Нельзя скрывать [data-autofit="subject"] до .is-fitted:
     * это вызывало заметное мигание при initial render и HTMX swap.
     */
    element.style.fontSize = "";

    var computed = window.getComputedStyle(element);
    var initialSize = parseFloat(computed.fontSize) || MAX_SIZE_PX;
    var fontSize = Math.min(MAX_SIZE_PX, initialSize);

    element.style.fontSize = fontSize + "px";

    while (
      fontSize > MIN_SIZE_PX
      && element.scrollWidth > element.clientWidth
    ) {
      fontSize -= STEP_PX;
      element.style.fontSize = fontSize + "px";
    }

    element.classList.add("is-fitted");
  }

  function fitSubjectsIn(container) {
    if (!(container instanceof Element)) {
      return;
    }

    if (container.matches('[data-autofit="subject"]')) {
      fitSubject(container);
    }

    container
      .querySelectorAll('[data-autofit="subject"]')
      .forEach(fitSubject);
  }

  function fitAllSubjects() {
    document
      .querySelectorAll('[data-autofit="subject"]')
      .forEach(fitSubject);
  }

  function getScheduleContainers(root) {
    if (!(root instanceof Element)) {
      return [];
    }

    var containers = [];

    if (
      root.matches(".schedule-showcase")
      || root.matches(".day-schedule")
    ) {
      containers.push(root);
    }

    root
      .querySelectorAll(".schedule-showcase, .day-schedule")
      .forEach(function (container) {
        containers.push(container);
      });

    return containers;
  }

  function observeScheduleContainer(container) {
    if (
      !resizeObserver
      || !(container instanceof Element)
      || observedContainers.has(container)
    ) {
      return;
    }

    observedContainers.add(container);
    resizeObserver.observe(container);
  }

  function unobserveScheduleContainers(root) {
    if (!resizeObserver || !(root instanceof Element)) {
      return;
    }

    getScheduleContainers(root).forEach(function (container) {
      resizeObserver.unobserve(container);
    });
  }

  function installResizeObserver() {
    if (!("ResizeObserver" in window)) {
      return;
    }

    resizeObserver = new ResizeObserver(function (entries) {
      entries.forEach(function (entry) {
        fitSubjectsIn(entry.target);
      });
    });

    getScheduleContainers(document.body).forEach(
      observeScheduleContainer
    );
  }


  /* ------------------------------------------------------------------------
     Inline changed-lesson details
     ------------------------------------------------------------------------ */

  function getToggle(wrapper) {
    return wrapper.querySelector("[data-inline-change-toggle]");
  }

  function getDetailsPanel(wrapper) {
    return wrapper.querySelector(".lesson-change-details");
  }

  function isDetailsOpen(wrapper) {
    return wrapper.classList.contains("lesson-card-wrapper--open");
  }

  function closeInlineDetails(wrapper, returnFocus) {
    if (!(wrapper instanceof Element)) {
      return;
    }

    var toggle = getToggle(wrapper);
    var details = getDetailsPanel(wrapper);

    wrapper.classList.remove("lesson-card-wrapper--open");

    if (toggle) {
      toggle.setAttribute("aria-expanded", "false");
    }

    if (details) {
      details.hidden = true;
    }

    if (returnFocus && toggle) {
      toggle.focus();
    }
  }

  function closeInlineDetailsIn(scope, exceptWrapper) {
    if (!(scope instanceof Element)) {
      return;
    }

    scope
      .querySelectorAll(".lesson-card-wrapper--open")
      .forEach(function (wrapper) {
        if (wrapper !== exceptWrapper) {
          closeInlineDetails(wrapper, false);
        }
      });
  }

  function openInlineDetails(wrapper) {
    if (!(wrapper instanceof Element)) {
      return;
    }

    var schedule = wrapper.closest(".day-schedule");
    var toggle = getToggle(wrapper);
    var details = getDetailsPanel(wrapper);

    if (!toggle || !details) {
      return;
    }

    if (schedule) {
      closeInlineDetailsIn(schedule, wrapper);
    }

    wrapper.classList.add("lesson-card-wrapper--open");
    toggle.setAttribute("aria-expanded", "true");
    details.hidden = false;
  }

  function toggleInlineDetails(wrapper) {
    if (isDetailsOpen(wrapper)) {
      closeInlineDetails(wrapper, false);
      return;
    }

    openInlineDetails(wrapper);
  }

  function installInlineChangeDetails() {
    document.addEventListener("click", function (event) {
      if (!(event.target instanceof Element)) {
        return;
      }

      var toggle = event.target.closest(
        "[data-inline-change-toggle]"
      );

      if (toggle) {
        var toggleWrapper = toggle.closest(
          ".lesson-card-wrapper"
        );

        if (toggleWrapper) {
          toggleInlineDetails(toggleWrapper);
        }

        return;
      }

      var closeButton = event.target.closest(
        "[data-inline-change-close]"
      );

      if (closeButton) {
        var closeWrapper = closeButton.closest(
          ".lesson-card-wrapper"
        );

        if (closeWrapper) {
          closeInlineDetails(closeWrapper, true);
        }

        return;
      }

      /*
       * Tap внутри card/details не является outside tap.
       * Это позволяет читать и выделять текст details.
       */
      if (event.target.closest(".lesson-card-wrapper")) {
        return;
      }

      /*
       * Закрываем details только при tap в свободное место текущего
       * day screen. Bottom nav, forms и прочие screens не затрагиваются.
       */
      var schedule = event.target.closest(".day-schedule");

      if (schedule) {
        closeInlineDetailsIn(schedule, null);
      }
    });

    document.addEventListener("keydown", function (event) {
      if (event.key !== "Escape") {
        return;
      }

      var activeElement = document.activeElement;

      if (!(activeElement instanceof Element)) {
        return;
      }

      var activeWrapper = activeElement.closest(
        ".lesson-card-wrapper--open"
      );

      if (activeWrapper) {
        closeInlineDetails(activeWrapper, true);
        return;
      }

      document
        .querySelectorAll(".lesson-card-wrapper--open")
        .forEach(function (wrapper) {
          closeInlineDetails(wrapper, false);
        });
    });
  }

  /* ------------------------------------------------------------------------
     HTMX lifecycle
     ------------------------------------------------------------------------ */

  function installHtmxLifecycle() {
    /*
     * Новый day DOM после:
     *
     * - #day-content outerHTML swap;
     * - future #app-shell outerHTML swap.
     *
     * Получает autofit и ResizeObserver без повторной регистрации
     * document-level event listeners.
     */
    document.body.addEventListener(
      "htmx:load",
      function (event) {
        if (!(event.detail.elt instanceof Element)) {
          return;
        }

        var loadedElement = event.detail.elt;

        fitSubjectsIn(loadedElement);

        getScheduleContainers(loadedElement).forEach(
          observeScheduleContainer
        );
      }
    );

    /*
     * При shell replacement старые schedule nodes удаляются из DOM.
     * ResizeObserver должен прекратить их наблюдать, иначе после большого
     * количества transitions возможны лишние references и callbacks.
     */
    document.body.addEventListener(
      "htmx:beforeCleanupElement",
      function (event) {
        var element = event.detail && event.detail.elt;

        if (element instanceof Element) {
          unobserveScheduleContainers(element);
        }
      }
    );
  }

  /* ------------------------------------------------------------------------
     Initialization
     ------------------------------------------------------------------------ */

function initialize() {
  fitAllSubjects();
  installResizeObserver();

  /*
   * Day и week swipe обслуживает отдельный общий module:
   * /static/js/schedule-swipe.js.
   *
   * Здесь intentionally остаются только schedule-specific UI concerns:
   * autofit, ResizeObserver, inline change details и HTMX cleanup.
   */
  installInlineChangeDetails();
  installHtmxLifecycle();
}

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      initialize,
      { once: true }
    );
  } else {
    initialize();
  }
})();

/* ==========================================================================
   SMART SCROLL & STATE PRESERVATION: .student-switch
   ========================================================================== */

(function () {
  "use strict";

  /*
   * Отдельный guard: этот runtime также должен переживать shell replacement
   * и не должен добавить повторные HTMX/document listeners.
   */
  if (window.schoolStudentSwitchUiInstalled) {
    return;
  }

  window.schoolStudentSwitchUiInstalled = true;

  var savedScroll = null;
  var animationId = null;
  var wheelBoundContainers = new WeakSet();

  function glideToCenter(container, activeChip) {
    if (!container || !activeChip) {
      return;
    }

    var containerRect = container.getBoundingClientRect();
    var chipRect = activeChip.getBoundingClientRect();

    var offsetToCenter = (
      (chipRect.left - containerRect.left)
      - (container.clientWidth / 2)
      + (chipRect.width / 2)
    );

    if (Math.abs(offsetToCenter) < 3) {
      return;
    }

    var duration = Math.min(
      Math.max(Math.abs(offsetToCenter) * 1.5, 300),
      600
    );

    var startLeft = container.scrollLeft;
    var startTime = null;

    if (animationId !== null) {
      window.cancelAnimationFrame(animationId);
    }

    function glideStep(currentTime) {
      if (startTime === null) {
        startTime = currentTime;
      }

      var elapsed = currentTime - startTime;
      var progress = Math.min(elapsed / duration, 1);

      /*
       * easeOutQuart:
       * быстрый старт, плавное торможение в финальной позиции.
       */
      var ease = 1 - Math.pow(1 - progress, 4);

      container.scrollLeft = (
        startLeft + (offsetToCenter * ease)
      );

      if (progress < 1) {
        animationId = window.requestAnimationFrame(glideStep);
      } else {
        animationId = null;
      }
    }

    animationId = window.requestAnimationFrame(glideStep);
  }

  function bindWheel(container) {
    if (
      !(container instanceof HTMLElement)
      || wheelBoundContainers.has(container)
    ) {
      return;
    }

    wheelBoundContainers.add(container);

    container.addEventListener(
      "wheel",
      function (event) {
        if (event.deltaY === 0) {
          return;
        }

        event.preventDefault();
        container.scrollLeft += event.deltaY;
      },
      { passive: false }
    );
  }

  function initializeStudentSwitches(root) {
    if (!(root instanceof Element)) {
      return;
    }

    var containers = [];

    if (root.matches(".student-switch")) {
      containers.push(root);
    }

    root.querySelectorAll(".student-switch").forEach(
      function (container) {
        containers.push(container);
      }
    );

    containers.forEach(function (container) {
      bindWheel(container);

      var activeChip = container.querySelector(
        ".student-chip.current"
      );

      glideToCenter(container, activeChip);
    });
  }

  function restoreSavedScroll() {
    if (savedScroll === null) {
      return;
    }

    document
      .querySelectorAll(".student-switch")
      .forEach(function (container) {
        container.scrollLeft = savedScroll;
      });
  }

  function glideCurrentStudentSwitches() {
    document
      .querySelectorAll(".student-switch")
      .forEach(function (container) {
        var activeChip = container.querySelector(
          ".student-chip.current"
        );

        glideToCenter(container, activeChip);
      });
  }

  function initialize() {
    initializeStudentSwitches(document.body);

    /*
     * Позиция фиксируется до request/skeleton swap.
     * Это убирает резкий возврат horizontal menu в scrollLeft=0.
     */
    document.body.addEventListener(
      "htmx:beforeRequest",
      function () {
        var container = document.querySelector(".student-switch");

        if (container) {
          savedScroll = container.scrollLeft;
        }
      }
    );

    /*
     * После вставки нового DOM сразу восстанавливаем старую позицию:
     * до htmx:afterSettle пользователь не должен увидеть jump влево.
     */
    document.body.addEventListener(
      "htmx:afterSwap",
      function () {
        restoreSavedScroll();
      }
    );

    /*
     * После settle плавно доводим active chip до центра.
     */
    document.body.addEventListener(
      "htmx:afterSettle",
      function () {
        glideCurrentStudentSwitches();
      }
    );

    /*
     * Новый shell/day content может содержать свежий student-switch.
     * Wheel listener и initial centering добавляются только новому node.
     */
    document.body.addEventListener(
      "htmx:load",
      function (event) {
        if (event.detail.elt instanceof Element) {
          initializeStudentSwitches(event.detail.elt);
        }
      }
    );
  }

  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      initialize,
      { once: true }
    );
  } else {
    initialize();
  }
})();