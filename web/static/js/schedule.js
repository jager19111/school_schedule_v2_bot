(function () {
  "use strict";

  var MIN_SIZE_PX = 12;
  var MAX_SIZE_PX = 21;
  var STEP_PX = 1;

  var resizeObserver = null;
  var observedContainers = new WeakSet();


  function fitSubject(element) {
    element.style.fontSize = "";

    var computed = window.getComputedStyle(element);
    var initialSize = parseFloat(computed.fontSize) || MAX_SIZE_PX;
    var fontSize = Math.min(MAX_SIZE_PX, initialSize);

    element.style.fontSize = fontSize + "px";

    while (
      fontSize > MIN_SIZE_PX &&
      element.scrollWidth > element.clientWidth
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
    if (!resizeObserver || observedContainers.has(container)) {
      return;
    }

    observedContainers.add(container);
    resizeObserver.observe(container);
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
     Swipe-навигация по дням
     ------------------------------------------------------------------------ */

  /*
   * Контроллер не содержит логики дат, URL или HTMX.
   *
   * Успешный свайп программно активирует одну из уже существующих
   * стрелок:
   *
   * [data-day-direction="previous"]
   * [data-day-direction="next"]
   *
   * Gesture area — стабильный <main id="main">. Это позволяет
   * свайпать на карточках, между карточками и в свободной нижней
   * части main при коротком расписании.
   */

  var SWIPE_MIN_DISTANCE_PX = 56;
  var SWIPE_AXIS_RATIO = 1.5;
  var SWIPE_DIRECTION_LOCK_DISTANCE_PX = 8;

  var SWIPE_LEFT_EDGE_PX = 24;
  var SWIPE_RIGHT_EDGE_PX = 16;

  var swipeNavigationLocked = false;
  var activeSwipe = null;
  var activeNavigationTrigger = null;
  var activeNavigationXhr = null;

  var SWIPE_INTERACTIVE_SELECTOR = [
    "button",
    "a",
    "input",
    "select",
    "textarea",
    "summary",
    '[role="button"]',
    "[contenteditable]",
  ].join(", ");


  function resetSwipeState() {
    activeSwipe = null;
  }


  function getActiveDaySchedule(main) {
    if (!(main instanceof Element)) {
      return null;
    }

    var schedule = main.querySelector(".day-schedule");

    return schedule instanceof Element
      ? schedule
      : null;
  }


  function isSwipeStartExcluded(target, main) {
    if (!(target instanceof Element)) {
      return true;
    }

    if (target.closest(SWIPE_INTERACTIVE_SELECTOR)) {
      return true;
    }

    return isInsideHorizontalScroller(target, main);
  }


  /*
   * Горизонтальный scroller получает собственное native interaction.
   * Swipe смены дня в нём не запускается.
   */
  function isInsideHorizontalScroller(target, main) {
    var current = target;

    while (
      current instanceof Element
      && current !== main
    ) {
      var style = window.getComputedStyle(current);
      var overflowX = style.overflowX;

      var canScrollHorizontally = (
        (overflowX === "auto" || overflowX === "scroll")
        && current.scrollWidth > current.clientWidth
      );

      if (canScrollHorizontally) {
        return true;
      }

      current = current.parentElement;
    }

    return false;
  }


  function isInsideProtectedEdge(clientX) {
    if (clientX <= SWIPE_LEFT_EDGE_PX) {
      return true;
    }

    return (
      clientX >= window.innerWidth - SWIPE_RIGHT_EDGE_PX
    );
  }


  function determineSwipeAxis(deltaX, deltaY) {
    var absX = Math.abs(deltaX);
    var absY = Math.abs(deltaY);

    if (
      absX < SWIPE_DIRECTION_LOCK_DISTANCE_PX
      && absY < SWIPE_DIRECTION_LOCK_DISTANCE_PX
    ) {
      return null;
    }

    if (absX >= absY * SWIPE_AXIS_RATIO) {
      return "horizontal";
    }

    if (absY >= absX * SWIPE_AXIS_RATIO) {
      return "vertical";
    }

    return null;
  }


  function getDayNavigationButton(schedule, direction) {
    if (!(schedule instanceof Element)) {
      return null;
    }

    var button = schedule.querySelector(
      '[data-day-direction="' + direction + '"]'
    );

    return button instanceof HTMLElement
      ? button
      : null;
  }


  function isDayNavigationTrigger(element) {
    return (
      element instanceof Element
      && element.matches("[data-day-direction]")
    );
  }


  function releaseSwipeNavigationLock() {
    swipeNavigationLocked = false;
    activeNavigationTrigger = null;
    activeNavigationXhr = null;
  }


  function activateDayNavigation(schedule, direction) {
    if (swipeNavigationLocked) {
      return;
    }

    var button = getDayNavigationButton(
      schedule,
      direction
    );

    if (!button) {
      return;
    }

    /*
     * Lock ставится до click(), чтобы два быстрых swipe не вызвали
     * два перехода подряд.
     *
     * Unlock происходит только в реальных HTMX lifecycle events.
     */
    swipeNavigationLocked = true;
    activeNavigationTrigger = button;

    button.click();
  }


  function installSwipeNavigation() {
    var main = document.getElementById("main");

    if (!(main instanceof Element)) {
      return;
    }

    /*
     * Инициализация происходит только один раз. main стабилен:
     * HTMX заменяет #day-content, но не <main id="main">.
     */
    if (main.dataset.swipeNavigationInstalled === "true") {
      return;
    }

    main.dataset.swipeNavigationInstalled = "true";


    main.addEventListener("pointerdown", function (event) {
      if (
        !event.isPrimary
        || activeSwipe
        || swipeNavigationLocked
      ) {
        return;
      }

      /*
       * Swipe предназначен для touch/pen.
       * Drag мышью не должен листать дни и мешать выделению текста.
       */
      if (event.pointerType === "mouse") {
        return;
      }

      var target = event.target;

      if (!(target instanceof Element)) {
        return;
      }

      var schedule = getActiveDaySchedule(main);

      /*
       * Swipe включён только на day screen.
       */
      if (!schedule) {
        return;
      }

      /*
       * main может содержать другие элементы на не-daily screen.
       * Начало жеста должно находиться в пределах main,
       * но не обязано находиться в lesson card.
       */
      if (!main.contains(target)) {
        return;
      }

      if (isInsideProtectedEdge(event.clientX)) {
        return;
      }

      if (isSwipeStartExcluded(target, main)) {
        return;
      }

      activeSwipe = {
        pointerId: event.pointerId,
        schedule: schedule,
        startX: event.clientX,
        startY: event.clientY,
        axis: null,
      };

      /*
       * Pointer capture гарантирует pointerup/pointercancel, даже если
       * палец заканчивает движение над нижним меню или за краем main.
       */
      try {
        main.setPointerCapture(event.pointerId);
      } catch (error) {
        /*
         * Pointer capture — защита, а не обязательное условие.
         * Если браузер не поддержал вызов, жест по-прежнему работает.
         */
      }
    });


    main.addEventListener("pointermove", function (event) {
      if (
        !activeSwipe
        || !event.isPrimary
        || event.pointerId !== activeSwipe.pointerId
      ) {
        return;
      }

      /*
       * Direction lock:
       * после определения dominant axis решение не меняется
       * до pointerup или pointercancel.
       */
      if (activeSwipe.axis) {
        return;
      }

      var deltaX = event.clientX - activeSwipe.startX;
      var deltaY = event.clientY - activeSwipe.startY;

      activeSwipe.axis = determineSwipeAxis(
        deltaX,
        deltaY
      );

      /*
       * preventDefault() намеренно не вызывается.
       * Vertical scroll всегда остаётся browser-native.
       */
    });


    main.addEventListener("pointerup", function (event) {
      if (
        !activeSwipe
        || !event.isPrimary
        || event.pointerId !== activeSwipe.pointerId
      ) {
        return;
      }

      var swipe = activeSwipe;
      resetSwipeState();

      try {
        main.releasePointerCapture(event.pointerId);
      } catch (error) {
        /*
         * Pointer capture мог быть снят браузером при native scroll
         * или pointercancel. Это не является ошибкой навигации.
         */
      }

      if (swipeNavigationLocked) {
        return;
      }

      var deltaX = event.clientX - swipe.startX;
      var deltaY = event.clientY - swipe.startY;

      /*
       * Если быстрое движение не успело попасть в pointermove,
       * определяем axis финально на pointerup.
       */
      var axis = swipe.axis || determineSwipeAxis(
        deltaX,
        deltaY
      );

      if (axis !== "horizontal") {
        return;
      }

      var absX = Math.abs(deltaX);
      var absY = Math.abs(deltaY);

      if (
        absX < SWIPE_MIN_DISTANCE_PX
        || absX < absY * SWIPE_AXIS_RATIO
      ) {
        return;
      }

      /*
       * Swipe left  → next.
       * Swipe right → previous.
       */
      activateDayNavigation(
        swipe.schedule,
        deltaX < 0 ? "next" : "previous"
      );
    });


    main.addEventListener("pointercancel", function (event) {
      if (
        activeSwipe
        && event.pointerId === activeSwipe.pointerId
      ) {
        resetSwipeState();
      }

      try {
        main.releasePointerCapture(event.pointerId);
      } catch (error) {
        /*
         * Для pointercancel отсутствие capture является допустимым.
         */
      }
    });

        /*
     * HTMX lifecycle слушаем на document.body, а не на main.
     *
     * #day-content заменяется через hx-swap="outerHTML". После замены
     * afterSettle может быть dispatch-нут уже от нового элемента либо
     * от target, который не является дочерним узлом исходного main
     * для bubbling chain.
     *
     * document.body остаётся стабильным во всех вариантах swap.
     */
    document.body.addEventListener(
      "htmx:beforeRequest",
      function (event) {
        var trigger = event.detail && event.detail.elt;

        if (!isDayNavigationTrigger(trigger)) {
          return;
        }

        swipeNavigationLocked = true;
        activeNavigationTrigger = trigger;
        activeNavigationXhr = event.detail.xhr || null;
      }
    );


    /*
     * Проверяем конкретный XHR текущей day-navigation.
     *
     * Это надёжнее сравнения DOM-элементов, потому что стрелка является
     * потомком #day-content и исчезает после hx-swap="outerHTML".
     */
    function isActiveDayNavigationRequest(event) {
      if (!swipeNavigationLocked) {
        return false;
      }

      var xhr = event.detail && event.detail.xhr;

      /*
       * В normal HTMX lifecycle xhr доступен всегда.
       *
       * Null fallback оставлен для совместимости с нестандартными
       * HTMX event detail в браузерах/версиях HTMX.
       */
      if (activeNavigationXhr === null) {
        return true;
      }

      return xhr === activeNavigationXhr;
    }


    /*
     * Успешный flow:
     *
     * beforeRequest
     * → request
     * → swap
     * → settle
     * → unlock
     */
    document.body.addEventListener(
      "htmx:afterSettle",
      function (event) {
        if (isActiveDayNavigationRequest(event)) {
          releaseSwipeNavigationLock();
        }
      }
    );


    /*
     * Если сервер или сеть вернули ошибку, settle может не наступить.
     * Lock снимается только в real HTMX lifecycle event — без timeout.
     */
    [
      "htmx:responseError",
      "htmx:sendError",
      "htmx:timeout",
    ].forEach(function (eventName) {
      document.body.addEventListener(
        eventName,
        function (event) {
          if (isActiveDayNavigationRequest(event)) {
            releaseSwipeNavigationLock();
          }
        }
      );
    });


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
       * Tap inside card or inside opened details is not an outside tap.
       * This allows reading and selecting details text without closing it.
       */
      if (event.target.closest(".lesson-card-wrapper")) {
        return;
      }

      /*
       * Close only when the user taps free space within the current
       * day-schedule screen. We do not attach global "click outside"
       * behaviour to navigation, forms, bottom nav, or other pages.
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
     Lifecycle
     ------------------------------------------------------------------------ */

  function initialize() {
    fitAllSubjects();
    installResizeObserver();
    installInlineChangeDetails();
    installSwipeNavigation();
  }


  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      initialize
    );
  } else {
    initialize();
  }


  /*
   * HTMX replaces #day-content with a fresh .day-schedule element.
   *
   * Event delegation above needs no reinstallation. Here we only:
   * - apply subject font fitting to the new content;
   * - attach ResizeObserver to the new schedule container.
   */
  document.body.addEventListener("htmx:load", function (event) {
    if (!(event.detail.elt instanceof Element)) {
      return;
    }

    var loadedElement = event.detail.elt;

    fitSubjectsIn(loadedElement);

    getScheduleContainers(loadedElement).forEach(
      observeScheduleContainer
    );
  });
})();