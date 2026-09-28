(function () {
  "use strict";

  var MIN_SIZE_PX = 12;
  var MAX_SIZE_PX = 21;
  var STEP_PX = 1;

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
// НОВАЯ СТРОКА: Добавляем класс, чтобы проявить текст после расчета
    element.classList.add("is-fitted");
  }

  function fitAllSubjects() {
    document
      .querySelectorAll('[data-autofit="subject"]')
      .forEach(fitSubject);
  }

  function installResizeObserver() {
    if (!("ResizeObserver" in window)) {
      return;
    }

    var observer = new ResizeObserver(function (entries) {
      entries.forEach(function (entry) {
        var subjects = entry.target.querySelectorAll(
          '[data-autofit="subject"]'
        );

        subjects.forEach(fitSubject);
      });
    });

    document
      .querySelectorAll(".schedule-showcase")
      .forEach(function (showcase) {
        observer.observe(showcase);
      });
  }

  function initialize() {
    fitAllSubjects();
    installResizeObserver();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
})();