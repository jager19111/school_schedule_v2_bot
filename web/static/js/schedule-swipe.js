/* web/static/js/schedule-swipe.js
 *
 * Общий direct-manipulation swipe controller для дня и недели.
 *
 * JavaScript не вычисляет даты и не строит URL. После visual commit он
 * вызывает click() существующей HTMX navigation link.
 *
 * Server остаётся владельцем:
 * - календарной арифметики;
 * - URL;
 * - history;
 * - fragment response.
 */

(function () {
  "use strict";

  if (window.schoolScheduleSwipeInstalled) {
    return;
  }

  window.schoolScheduleSwipeInstalled = true;

  var AXIS_RATIO = 1.5;
  var AXIS_LOCK_DISTANCE = 10;
  var DRAG_ACTIVATION_DISTANCE = 12;
  var COMMIT_VIEWPORT_RATIO = 0.45;
  var LEFT_EDGE_PX = 24;
  var RIGHT_EDGE_PX = 16;

  var activeSwipe = null;
  var activeRequest = null;
  var slowLoadingTimer = null;
  var animationFrame = null;

  var INTERACTIVE_SELECTOR = [
    "button",
    "a",
    "input",
    "select",
    "textarea",
    "summary",
    '[role="button"]',
    "[contenteditable]",
  ].join(", ");

  var DAY = {
    stage: "[data-day-swipe-stage]",
    panel: ".day-schedule",
    neighbor: "[data-day-swipe-neighbor]",
    direction: "[data-day-direction]",
    navigation: "[data-day-navigation]",
    label: "[data-day-swipe-neighbor-label]",
    students: "[data-day-swipe-neighbor-students]",
    activeClass: "is-day-swipe-active",
    draggingClass: "is-day-swipe-dragging",
    settlingClass: "is-day-swipe-settling",
    slowClass: "is-day-swipe-slow-loading",
    directionData: "daySwipeDirection",
    labelData: "dayLabel",
  };

  var WEEK = {
    stage: "[data-week-swipe-stage]",
    panel: ".week-schedule",
    neighbor: "[data-week-swipe-neighbor]",
    direction: "[data-week-direction]",
    navigation: "[data-week-navigation]",
    label: "[data-week-swipe-neighbor-label]",
    students: "[data-week-swipe-neighbor-students]",
    activeClass: "is-week-swipe-active",
    draggingClass: "is-week-swipe-dragging",
    settlingClass: "is-week-swipe-settling",
    slowClass: "is-week-swipe-slow-loading",
    directionData: "weekSwipeDirection",
    labelData: "weekLabel",
  };

  var CONFIGS = [DAY, WEEK];

  function prefersReducedMotion() {
    return window.matchMedia(
      "(prefers-reduced-motion: reduce)"
    ).matches;
  }

  function findConfigForElement(element) {
    if (!(element instanceof Element)) {
      return null;
    }

    return CONFIGS.find(function (config) {
      return element.closest(config.stage) !== null;
    }) || null;
  }

  function stageFor(config) {
    var stage = document.querySelector(config.stage);

    return stage instanceof Element ? stage : null;
  }

  function panelFor(config, stage) {
    if (!(stage instanceof Element)) {
      return null;
    }

    var panel = stage.querySelector(
      ":scope > " + config.panel
    );

    return panel instanceof HTMLElement ? panel : null;
  }

  function neighborFor(config, stage) {
    if (!(stage instanceof Element)) {
      return null;
    }

    var neighbor = stage.querySelector(config.neighbor);

    return neighbor instanceof HTMLElement ? neighbor : null;
  }

  function clearSlowLoading(stage, config) {
    if (slowLoadingTimer !== null) {
      window.clearTimeout(slowLoadingTimer);
      slowLoadingTimer = null;
    }

    if (stage instanceof Element) {
      stage.classList.remove(config.slowClass);
    }
  }

  function scheduleSlowLoading(stage, config) {
    clearSlowLoading(stage, config);

    slowLoadingTimer = window.setTimeout(function () {
      slowLoadingTimer = null;

      if (
        activeRequest
        && stage instanceof Element
      ) {
        stage.classList.add(config.slowClass);
      }
    }, 400);
  }

  function clearTransforms(config, stage) {
    var panel = panelFor(config, stage);
    var neighbor = neighborFor(config, stage);

    if (panel) {
      panel.style.transform = "";
    }

    if (neighbor) {
      neighbor.style.transform = "";
    }
  }

  function resetStage(config, stage) {
    if (!(stage instanceof Element)) {
      return;
    }

    stage.classList.remove(
      config.activeClass,
      config.draggingClass,
      config.settlingClass
    );

    delete stage.dataset[config.directionData];

    clearTransforms(config, stage);
    clearSlowLoading(stage, config);
  }

  function resetStageAfterSwap(config, stage) {
    if (!(stage instanceof Element)) {
      return;
    }

    var panel = panelFor(config, stage);
    var neighbor = neighborFor(config, stage);

    if (panel) {
      panel.style.transition = "none";
    }

    if (neighbor) {
      neighbor.style.transition = "none";
    }

    resetStage(config, stage);

    void stage.offsetWidth;

    if (panel) {
      panel.style.transition = "";
    }

    if (neighbor) {
      neighbor.style.transition = "";
    }
  }

  function prepareNeighbor(config, swipe, button) {
    var labelElement = swipe.neighbor.querySelector(config.label);
    var studentsTarget = swipe.neighbor.querySelector(config.students);

    if (labelElement) {
      labelElement.textContent = (
        button.dataset[config.labelData]
        || "Загрузка"
      );
    }

    if (!studentsTarget) {
      return;
    }

    studentsTarget.replaceChildren();

    var source = swipe.panel.querySelector(
      ":scope > .student-switch"
    );

    if (!source) {
      return;
    }

    var copy = source.cloneNode(true);

    if (!(copy instanceof HTMLElement)) {
      return;
    }

    copy.setAttribute("aria-hidden", "true");

    copy.querySelectorAll("[id]").forEach(function (element) {
      element.removeAttribute("id");
    });

    studentsTarget.appendChild(copy);
  }

  function setTransform(element, offsetX) {
    element.style.transform = (
      "translate3d(" + offsetX + "px, 0, 0)"
    );
  }

  function startOffset(width, direction) {
    return direction === "next" ? width : -width;
  }

  function renderDrag(swipe) {
    if (animationFrame !== null) {
      return;
    }

    animationFrame = window.requestAnimationFrame(function () {
      animationFrame = null;

      if (!activeSwipe || activeSwipe !== swipe) {
        return;
      }

      setTransform(swipe.panel, swipe.offsetX);

      setTransform(
        swipe.neighbor,
        startOffset(swipe.width, swipe.direction) + swipe.offsetX
      );
    });
  }

  function selectorForDirection(config, direction) {
  /*
   * config.direction уже содержит attribute selector:
   *
   * [data-day-direction]
   * [data-week-direction]
   *
   * Превращаем его в:
   *
   * [data-day-direction="next"]
   * [data-week-direction="previous"]
   */
  return config.direction.replace(
    "]",
    '="' + direction + '"]'
  );
}

  function isExcludedStart(target, stage) {
    if (target.closest(INTERACTIVE_SELECTOR)) {
      return true;
    }

    var current = target;

    while (
      current instanceof Element
      && current !== stage
    ) {
      var style = window.getComputedStyle(current);

      if (
        (style.overflowX === "auto" || style.overflowX === "scroll")
        && current.scrollWidth > current.clientWidth
      ) {
        return true;
      }

      current = current.parentElement;
    }

    return false;
  }

  function activateSwipe(swipe, direction) {
    var button = swipe.panel.querySelector(
    selectorForDirection(
        swipe.config,
        direction
    )
    );

    if (!(button instanceof HTMLElement)) {
      return;
    }

    swipe.dragActive = true;
    swipe.direction = direction;
    swipe.button = button;

    prepareNeighbor(swipe.config, swipe, button);

    swipe.stage.dataset[swipe.config.directionData] = direction;

    swipe.stage.classList.add(
      swipe.config.activeClass,
      swipe.config.draggingClass
    );

    setTransform(
      swipe.neighbor,
      startOffset(swipe.width, direction)
    );
  }

  function finishSwipe(swipe, commit) {
    swipe.stage.classList.remove(swipe.config.draggingClass);
    swipe.stage.classList.add(swipe.config.settlingClass);

    setTransform(
      swipe.panel,
      commit ? startOffset(swipe.width, swipe.direction) : 0
    );

    setTransform(
      swipe.neighbor,
      commit ? 0 : startOffset(swipe.width, swipe.direction)
    );

    if (commit) {
      swipe.button.click();
      return;
    }

    if (prefersReducedMotion()) {
      resetStage(swipe.config, swipe.stage);
      return;
    }

    swipe.panel.addEventListener(
      "transitionend",
      function (event) {
        if (
          event.target === swipe.panel
          && event.propertyName === "transform"
        ) {
          resetStage(swipe.config, swipe.stage);
        }
      },
      { once: true }
    );
  }

  document.addEventListener("pointerdown", function (event) {
    if (
      !event.isPrimary
      || activeSwipe
      || activeRequest
      || event.pointerType === "mouse"
    ) {
      return;
    }

    if (!(event.target instanceof Element)) {
      return;
    }

    if (
      event.clientX <= LEFT_EDGE_PX
      || event.clientX >= window.innerWidth - RIGHT_EDGE_PX
    ) {
      return;
    }

    var config = findConfigForElement(event.target);

    if (!config) {
      return;
    }

    var stage = event.target.closest(config.stage);
    var panel = panelFor(config, stage);
    var neighbor = neighborFor(config, stage);

    if (
      !stage
      || !panel
      || !neighbor
      || isExcludedStart(event.target, stage)
    ) {
      return;
    }

    var width = stage.getBoundingClientRect().width;

    if (width <= 0) {
      return;
    }

    activeSwipe = {
      config: config,
      stage: stage,
      panel: panel,
      neighbor: neighbor,
      pointerId: event.pointerId,
      width: width,
      startX: event.clientX,
      startY: event.clientY,
      axis: null,
      direction: null,
      dragActive: false,
      button: null,
      offsetX: 0,
    };

    try {
      stage.setPointerCapture(event.pointerId);
    } catch (error) {
      /* Pointer capture is optional. */
    }
  });

  document.addEventListener("pointermove", function (event) {
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
      if (
        Math.abs(deltaX) < AXIS_LOCK_DISTANCE
        && Math.abs(deltaY) < AXIS_LOCK_DISTANCE
      ) {
        return;
      }

      if (Math.abs(deltaX) >= Math.abs(deltaY) * AXIS_RATIO) {
        swipe.axis = "horizontal";
      } else if (
        Math.abs(deltaY) >= Math.abs(deltaX) * AXIS_RATIO
      ) {
        swipe.axis = "vertical";
      } else {
        return;
      }
    }

    if (swipe.axis !== "horizontal") {
      return;
    }

    if (
      !swipe.dragActive
      && Math.abs(deltaX) >= DRAG_ACTIVATION_DISTANCE
    ) {
      activateSwipe(
        swipe,
        deltaX < 0 ? "next" : "previous"
      );
    }

    if (!swipe.dragActive) {
      return;
    }

    if (
      (swipe.direction === "next" && deltaX > 0)
      || (swipe.direction === "previous" && deltaX < 0)
    ) {
      return;
    }

    swipe.offsetX = deltaX;
    renderDrag(swipe);
  });

  function releasePointer(event, cancelled) {
    if (
      !activeSwipe
      || event.pointerId !== activeSwipe.pointerId
    ) {
      return;
    }

    var swipe = activeSwipe;
    activeSwipe = null;

    try {
      swipe.stage.releasePointerCapture(event.pointerId);
    } catch (error) {
      /* Browser may release capture automatically. */
    }

    if (!swipe.dragActive) {
      return;
    }

    var deltaX = event.clientX - swipe.startX;
    var commit = (
      !cancelled
      && Math.abs(deltaX) >= swipe.width * COMMIT_VIEWPORT_RATIO
      && (
        (swipe.direction === "next" && deltaX <= 0)
        || (swipe.direction === "previous" && deltaX >= 0)
      )
    );

    finishSwipe(swipe, commit);
  }

  document.addEventListener("pointerup", function (event) {
    releasePointer(event, false);
  });

  document.addEventListener("pointercancel", function (event) {
    releasePointer(event, true);
  });

  function configForNavigationTrigger(trigger) {
    if (!(trigger instanceof Element)) {
      return null;
    }

    return CONFIGS.find(function (config) {
      return trigger.matches(
        config.direction + ", " + config.navigation
      );
    }) || null;
  }

  function isActiveRequest(event) {
    if (!activeRequest) {
      return false;
    }

    var xhr = event.detail && event.detail.xhr;

    return (
      activeRequest.xhr === null
      || activeRequest.xhr === xhr
    );
  }

  document.body.addEventListener(
    "htmx:beforeRequest",
    function (event) {
      var trigger = event.detail && event.detail.elt;
      var config = configForNavigationTrigger(trigger);

      if (!config) {
        return;
      }

      var stage = stageFor(config);

      activeRequest = {
        config: config,
        xhr: event.detail.xhr || null,
        swapped: false,
      };

      scheduleSlowLoading(stage, config);
    }
  );

  document.body.addEventListener(
    "htmx:afterSwap",
    function (event) {
      if (!isActiveRequest(event) || activeRequest.swapped) {
        return;
      }

      activeRequest.swapped = true;

      var config = activeRequest.config;
      var stage = stageFor(config);

      clearSlowLoading(stage, config);
      resetStageAfterSwap(config, stage);
    }
  );

  document.body.addEventListener(
    "htmx:afterSettle",
    function (event) {
      if (!isActiveRequest(event)) {
        return;
      }

      var config = activeRequest.config;
      var stage = stageFor(config);

      if (!activeRequest.swapped) {
        resetStageAfterSwap(config, stage);
      }

      clearSlowLoading(stage, config);
      activeRequest = null;
    }
  );

  [
    "htmx:responseError",
    "htmx:sendError",
    "htmx:timeout",
  ].forEach(function (eventName) {
    document.body.addEventListener(eventName, function (event) {
      if (!isActiveRequest(event)) {
        return;
      }

      var config = activeRequest.config;

      resetStage(config, stageFor(config));
      activeRequest = null;
    });
  });
})();