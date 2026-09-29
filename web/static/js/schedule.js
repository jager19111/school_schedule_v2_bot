  /*web/static/js/schedule.js    */
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
     Interactive day swipe
     ------------------------------------------------------------------------ */

  /*
   * Direct manipulation day navigation.
   *
   * Этот controller:
   * - не вычисляет даты;
   * - не строит URL;
   * - не меняет history;
   * - не создаёт новый HTMX flow.
   *
   * Он читает existing navigation buttons:
   *
   * [data-day-direction="previous"]
   * [data-day-direction="next"]
   *
   * и после visual commit вызывает button.click().
   */

  var SWIPE_AXIS_RATIO = 1.5;
  var SWIPE_AXIS_LOCK_DISTANCE_PX = 10;
  var SWIPE_DRAG_ACTIVATION_PX = 12;
  var SWIPE_COMMIT_VIEWPORT_RATIO = 0.45;

  var SWIPE_LEFT_EDGE_PX = 24;
  var SWIPE_RIGHT_EDGE_PX = 16;

  var swipeNavigationLocked = false;
  var activeSwipe = null;
  var activeNavigationTrigger = null;
  var activeNavigationXhr = null;
  var activeNavigationSwapHandled = false;
  var slowLoadingTimer = null;
  var swipeAnimationFrame = null;

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


  function prefersReducedMotion() {
    return window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
  }


  function resetSwipeState() {
    activeSwipe = null;
  }

  function clearSlowLoadingState(stage) {
  if (slowLoadingTimer !== null) {
    window.clearTimeout(slowLoadingTimer);
    slowLoadingTimer = null;
  }

  if (stage instanceof Element) {
    stage.classList.remove(
      "is-day-swipe-slow-loading"
    );
  }
}


  function scheduleSlowLoadingState(stage) {
    clearSlowLoadingState(stage);

    /*
    * Это UI delay, а не navigation unlock.
    *
    * Lock и HTMX lifecycle по-прежнему определяются только реальными
    * htmx events. Timer отвечает исключительно за visible skeleton.
    */
    slowLoadingTimer = window.setTimeout(function () {
      slowLoadingTimer = null;

      if (
        swipeNavigationLocked
        && stage instanceof Element
      ) {
        stage.classList.add(
          "is-day-swipe-slow-loading"
        );
      }
    }, 400);
  }

  function getActiveDaySchedule(stage) {
    if (!(stage instanceof Element)) {
      return null;
    }

    var schedule = stage.querySelector(
      ":scope > .day-schedule"
    );

    return schedule instanceof Element
      ? schedule
      : null;
  }


  function getDaySwipeStage(main) {
    if (!(main instanceof Element)) {
      return null;
    }

    var stage = main.querySelector(
      "[data-day-swipe-stage]"
    );

    return stage instanceof Element
      ? stage
      : null;
  }


  function getDaySwipeNeighbor(stage) {
    if (!(stage instanceof Element)) {
      return null;
    }

    var neighbor = stage.querySelector(
      "[data-day-swipe-neighbor]"
    );

    return neighbor instanceof Element
      ? neighbor
      : null;
  }


  function getNeighborLabelElement(neighbor) {
    if (!(neighbor instanceof Element)) {
      return null;
    }

    var label = neighbor.querySelector(
      "[data-day-swipe-neighbor-label]"
    );

    return label instanceof Element
      ? label
      : null;
  }

  function getNeighborStudentsElement(neighbor) {
    if (!(neighbor instanceof Element)) {
      return null;
    }

    var students = neighbor.querySelector(
      "[data-day-swipe-neighbor-students]"
    );

    return students instanceof HTMLElement
      ? students
      : null;
  }


  function prepareNeighborChrome(
    neighbor,
    schedule,
    label
  ) {
    if (
      !(neighbor instanceof Element)
      || !(schedule instanceof Element)
    ) {
      return;
    }

    setNeighborLabel(neighbor, label);

    var target = getNeighborStudentsElement(neighbor);

    if (!target) {
      return;
    }

    target.replaceChildren();

    /*
    * Клонируем только visual child selector.
    *
    * Clone не является application state и не содержит active behavior:
    * .day-swipe-neighbor has pointer-events: none.
    */
    var source = schedule.querySelector(
      ":scope > .student-switch"
    );

    if (!source) {
      return;
    }

    var visualCopy = source.cloneNode(true);

    if (visualCopy instanceof HTMLElement) {
      visualCopy.setAttribute("aria-hidden", "true");

      visualCopy.querySelectorAll("[id]").forEach(
        function (element) {
          element.removeAttribute("id");
        }
      );

      target.appendChild(visualCopy);
    }
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


  function isInsideProtectedEdge(clientX) {
    if (clientX <= SWIPE_LEFT_EDGE_PX) {
      return true;
    }

    return (
      clientX >= window.innerWidth - SWIPE_RIGHT_EDGE_PX
    );
  }


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


  function isSwipeStartExcluded(target, main) {
    if (!(target instanceof Element)) {
      return true;
    }

    if (target.closest(SWIPE_INTERACTIVE_SELECTOR)) {
      return true;
    }

    return isInsideHorizontalScroller(target, main);
  }


  function determineSwipeAxis(deltaX, deltaY) {
    var absX = Math.abs(deltaX);
    var absY = Math.abs(deltaY);

    if (
      absX < SWIPE_AXIS_LOCK_DISTANCE_PX
      && absY < SWIPE_AXIS_LOCK_DISTANCE_PX
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


  function getStageWidth(stage) {
    if (!(stage instanceof Element)) {
      return 0;
    }

    return stage.getBoundingClientRect().width;
  }


  function getSwipeDirection(deltaX) {
    return deltaX < 0
      ? "next"
      : "previous";
  }


  function getNeighborStartOffset(
    stageWidth,
    direction
  ) {
    return direction === "next"
      ? stageWidth
      : -stageWidth;
  }


  function setPanelTransform(panel, offsetX) {
    if (!(panel instanceof HTMLElement)) {
      return;
    }

    panel.style.transform = (
      "translate3d(" + offsetX + "px, 0, 0)"
    );
  }


  function queueDragRender(swipe, offsetX) {
    swipe.pendingOffsetX = offsetX;

    if (swipeAnimationFrame !== null) {
      return;
    }

    swipeAnimationFrame = window.requestAnimationFrame(
      function () {
        swipeAnimationFrame = null;

        if (!activeSwipe || activeSwipe !== swipe) {
          return;
        }

        var direction = swipe.direction;
        var width = swipe.stageWidth;
        var neighborOffset = (
          getNeighborStartOffset(width, direction)
          + swipe.pendingOffsetX
        );

        setPanelTransform(
          swipe.schedule,
          swipe.pendingOffsetX
        );

        setPanelTransform(
          swipe.neighbor,
          neighborOffset
        );
      }
    );
  }


  function setNeighborLabel(neighbor, label) {
    var labelElement = getNeighborLabelElement(neighbor);

    if (!labelElement) {
      return;
    }

    labelElement.textContent = label || "";
  }


  function beginInteractiveDrag(swipe, direction) {
    if (swipe.dragActive) {
      return;
    }

    var button = getDayNavigationButton(
      swipe.schedule,
      direction
    );

    if (!button) {
      return;
    }

    swipe.dragActive = true;
    swipe.direction = direction;
    swipe.navigationButton = button;

    prepareNeighborChrome(
      swipe.neighbor,
      swipe.schedule,
      button.dataset.dayLabel || ""
    );

    swipe.stage.dataset.daySwipeDirection = direction;
    swipe.stage.classList.add(
      "is-day-swipe-active",
      "is-day-swipe-dragging"
    );

    setPanelTransform(
      swipe.neighbor,
      getNeighborStartOffset(
        swipe.stageWidth,
        direction
      )
    );
  }


  function clearPanelTransforms(stage) {
    var schedule = getActiveDaySchedule(stage);
    var neighbor = getDaySwipeNeighbor(stage);

    if (schedule) {
      schedule.style.transform = "";
    }

    if (neighbor) {
      neighbor.style.transform = "";
    }
  }


  function resetInteractiveStage(stage) {
    if (!(stage instanceof Element)) {
      return;
    }

    stage.classList.remove(
      "is-day-swipe-active",
      "is-day-swipe-dragging",
      "is-day-swipe-settling"
    );

    delete stage.dataset.daySwipeDirection;

    clearPanelTransforms(stage);
    clearSlowLoadingState(stage);
  }

    function resetInteractiveStageAfterSwap(stage) {
    if (!(stage instanceof Element)) {
      return;
    }

    var schedule = getActiveDaySchedule(stage);
    var neighbor = getDaySwipeNeighbor(stage);

    /*
    * В момент htmx:afterSwap stage может всё ещё иметь class
    * is-day-swipe-settling.
    *
    * Safari применяет transition к newly inserted canonical
    * .day-schedule, если просто очистить transforms. Поэтому
    * временно отключаем transition только у текущего stage.
    */
    if (schedule instanceof HTMLElement) {
      schedule.style.transition = "none";
    }

    if (neighbor instanceof HTMLElement) {
      neighbor.style.transition = "none";
    }

    stage.classList.remove(
      "is-day-swipe-active",
      "is-day-swipe-dragging",
      "is-day-swipe-settling"
    );

    delete stage.dataset.daySwipeDirection;

    clearPanelTransforms(stage);

    /*
    * Synchronize style cleanup before restoring CSS ownership.
    * Это forced layout, а не timer и не новая animation.
    */
    void stage.offsetWidth;

    if (schedule instanceof HTMLElement) {
      schedule.style.transition = "";
    }

    if (neighbor instanceof HTMLElement) {
      neighbor.style.transition = "";
    }
  }


  function releaseSwipeNavigationLock() {
    swipeNavigationLocked = false;
    activeNavigationTrigger = null;
    activeNavigationXhr = null;
  }


  function finishCancelledSwipe(swipe) {
    clearSlowLoadingState(swipe.stage);
    resetInteractiveStage(swipe.stage);
  }


  function activateExistingNavigation(swipe) {
    if (
      swipeNavigationLocked
      || !(swipe.navigationButton instanceof HTMLElement)
    ) {
      return;
    }

    swipeNavigationLocked = true;
    activeNavigationTrigger = swipe.navigationButton;

    swipe.navigationButton.click();
  }


  function finishCommittedSwipe(swipe) {
    activateExistingNavigation(swipe);
  }


  function settleSwipe(swipe, shouldCommit) {
    var schedule = swipe.schedule;
    var neighbor = swipe.neighbor;
    var stage = swipe.stage;

    if (
      !(schedule instanceof HTMLElement)
      || !(neighbor instanceof HTMLElement)
      || !(stage instanceof Element)
    ) {
      return;
    }

    var width = swipe.stageWidth;
    var direction = swipe.direction;
    var currentTargetOffset = shouldCommit
      ? getNeighborStartOffset(width, direction)
      : 0;

    var neighborTargetOffset = shouldCommit
      ? 0
      : getNeighborStartOffset(width, direction);

    stage.classList.remove("is-day-swipe-dragging");
    stage.classList.add("is-day-swipe-settling");

    setPanelTransform(schedule, currentTargetOffset);
    setPanelTransform(neighbor, neighborTargetOffset);

    /*
    * Commit navigation запускаем сразу.
    *
    * Visual animation продолжает идти независимо, но HTMX request уже
    * стартует через exact existing navigation arrow. Это устраняет
    * Safari hang, когда transitionend не приходит.
    */
    if (shouldCommit) {
      finishCommittedSwipe(swipe);
    }

    /*
    * Reduced motion:
    * commit уже стартовал выше;
    * cancel нужно завершить сразу.
    */
    if (prefersReducedMotion()) {
      if (!shouldCommit) {
        finishCancelledSwipe(swipe);
      }

      return;
    }

    /*
    * Для successful commit не ждём transitionend.
    *
    * transitionend нужен только cancel flow, потому что после cancel
    * canonical navigation не запускается и state нужно вернуть в idle
    * только после snap-back.
    */
    if (shouldCommit) {
      return;
    }

    var completed = false;

    function onTransitionEnd(event) {
      if (
        completed
        || event.target !== schedule
        || event.propertyName !== "transform"
      ) {
        return;
      }

      completed = true;
      finishCancelledSwipe(swipe);
    }

    schedule.addEventListener(
      "transitionend",
      onTransitionEnd,
      { once: true }
    );
  }


  function isActiveDayNavigationRequest(event) {
    if (!swipeNavigationLocked) {
      return false;
    }

    var xhr = event.detail && event.detail.xhr;

    if (activeNavigationXhr === null) {
      return true;
    }

    return xhr === activeNavigationXhr;
  }


  function installSwipeNavigation() {
    var main = document.getElementById("main");

    if (!(main instanceof Element)) {
      return;
    }

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

      if (event.pointerType === "mouse") {
        return;
      }

      var target = event.target;

      if (!(target instanceof Element)) {
        return;
      }

      var stage = getDaySwipeStage(main);
      var schedule = getActiveDaySchedule(stage);
      var neighbor = getDaySwipeNeighbor(stage);

      if (
        !stage
        || !schedule
        || !neighbor
        || !main.contains(target)
      ) {
        return;
      }

      if (isInsideProtectedEdge(event.clientX)) {
        return;
      }

      if (isSwipeStartExcluded(target, main)) {
        return;
      }

      var stageWidth = getStageWidth(stage);

      if (stageWidth <= 0) {
        return;
      }

      activeSwipe = {
        pointerId: event.pointerId,
        stage: stage,
        schedule: schedule,
        neighbor: neighbor,
        stageWidth: stageWidth,
        startX: event.clientX,
        startY: event.clientY,
        axis: null,
        direction: null,
        dragActive: false,
        navigationButton: null,
        pendingOffsetX: 0,
      };

      try {
        main.setPointerCapture(event.pointerId);
      } catch (error) {
        /*
         * Pointer capture — дополнительная защита. Если браузер
         * не поддержал capture, базовый pointer flow всё равно работает.
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

      var swipe = activeSwipe;
      var deltaX = event.clientX - swipe.startX;
      var deltaY = event.clientY - swipe.startY;

      if (!swipe.axis) {
        swipe.axis = determineSwipeAxis(deltaX, deltaY);
      }

      if (swipe.axis !== "horizontal") {
        return;
      }

      if (
        !swipe.dragActive
        && Math.abs(deltaX) >= SWIPE_DRAG_ACTIVATION_PX
      ) {
        beginInteractiveDrag(
          swipe,
          getSwipeDirection(deltaX)
        );
      }

      if (!swipe.dragActive) {
        return;
      }

      /*
       * Direction lock:
       * после activation нельзя «развернуть» gesture в обратную сторону.
       */
      var isDirectionConsistent = (
        (swipe.direction === "next" && deltaX <= 0)
        || (
          swipe.direction === "previous"
          && deltaX >= 0
        )
      );

      if (!isDirectionConsistent) {
        return;
      }

      queueDragRender(swipe, deltaX);

      /*
       * preventDefault() не вызывается.
       * Vertical scroll сохраняет browser-native поведение.
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
         * Browser может уже снять pointer capture.
         */
      }

      if (!swipe.dragActive) {
        return;
      }

      var deltaX = event.clientX - swipe.startX;
      var commitThreshold = (
        swipe.stageWidth * SWIPE_COMMIT_VIEWPORT_RATIO
      );

      var isDirectionConsistent = (
        (swipe.direction === "next" && deltaX <= 0)
        || (
          swipe.direction === "previous"
          && deltaX >= 0
        )
      );

      var shouldCommit = (
        isDirectionConsistent
        && Math.abs(deltaX) >= commitThreshold
      );

      settleSwipe(swipe, shouldCommit);
    });


    main.addEventListener("pointercancel", function (event) {
      if (
        !activeSwipe
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
         * Browser может снять capture автоматически.
         */
      }

      if (swipe.dragActive) {
        settleSwipe(swipe, false);
      }
    });


    /*
     * Manual arrow click также блокирует новый drag до завершения
     * существующего HTMX navigation lifecycle.
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
        activeNavigationSwapHandled = false;
        var currentStage = getDaySwipeStage(main);

        scheduleSlowLoadingState(currentStage);
      }
    );

    /*
     * afterSwap означает:
     * - HTMX response уже accepted;
     * - canonical #day-content уже заменён;
     * - новый day DOM существует;
     * - URL/history уже принадлежат existing HTMX navigation.
     *
     * Здесь только visual cleanup. Unlock делаем позже, на afterSettle.
     */
    document.body.addEventListener(
      "htmx:afterSwap",
      function (event) {
        if (!isActiveDayNavigationRequest(event)) {
          return;
        }

        if (activeNavigationSwapHandled) {
          return;
        }

        activeNavigationSwapHandled = true;
        

        var currentStage = getDaySwipeStage(main);
        clearSlowLoadingState(currentStage);

        var schedule = getActiveDaySchedule(currentStage);

        if (schedule) {
          fitSubjectsIn(schedule);
          observeScheduleContainer(schedule);
        }

        resetInteractiveStageAfterSwap(currentStage);
      }
    );

    /*
     * После HTMX swap new #day-content уже существует.
     * Сбрасываем temporary transforms и neighbour skeleton.
     */
    document.body.addEventListener(
      "htmx:afterSettle",
      function (event) {
        if (!isActiveDayNavigationRequest(event)) {
          return;
        }

        /*
        * Defensive fallback:
        * если afterSwap по какой-либо причине не был получен,
        * canonical DOM всё равно должен быть visual-clean.
        */
        if (!activeNavigationSwapHandled) {
          var currentStage = getDaySwipeStage(main);
          var schedule = getActiveDaySchedule(currentStage);

          if (schedule) {
            fitSubjectsIn(schedule);
            observeScheduleContainer(schedule);
          }

          resetInteractiveStageAfterSwap(currentStage);
        }
        clearSlowLoadingState(
          getDaySwipeStage(main)
        );

        releaseSwipeNavigationLock();
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
          if (!isActiveDayNavigationRequest(event)) {
            return;
          }

          var currentStage = getDaySwipeStage(main);
          

          activeNavigationSwapHandled = false;
          clearSlowLoadingState(currentStage);

          resetInteractiveStage(currentStage);
          releaseSwipeNavigationLock();
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