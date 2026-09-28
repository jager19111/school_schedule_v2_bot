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