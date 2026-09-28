/* web/static/js/extra.js */
(function () {
  "use strict";

  var MIN_SUBJECT_SIZE_PX = 12;
  var MAX_SUBJECT_SIZE_PX = 21;
  var SUBJECT_SIZE_STEP_PX = 1;
  var REMINDER_MIN = 0;
  var REMINDER_MAX = 180;
  var REMINDER_DEFAULT = 30;


  function getField(form, name) {
    if (!form || !form.elements) {
      return null;
    }

    return form.elements.namedItem(name);
  }

function clampReminder(value) {
  var numeric = Number.parseInt(value, 10);

  if (Number.isNaN(numeric)) {
    return REMINDER_DEFAULT;
  }

  return Math.min(
    REMINDER_MAX,
    Math.max(REMINDER_MIN, numeric)
  );
}


function getReminderInput(stepper) {
  if (!(stepper instanceof Element)) {
    return null;
  }

  var input = stepper.querySelector(
    'input[name="reminder_minutes"]'
  );

  return input instanceof HTMLInputElement
    ? input
    : null;
}


function adjustReminder(stepper, delta) {
  var input = getReminderInput(stepper);

  if (!input) {
    return;
  }

  var currentValue = clampReminder(input.value);
  var nextValue = clampReminder(currentValue + delta);

  input.value = String(nextValue);

  input.dispatchEvent(
    new Event("input", {
      bubbles: true,
    })
  );
}


function normalizeReminder(stepper) {
  var input = getReminderInput(stepper);

  if (!input) {
    return;
  }

  input.value = String(
    clampReminder(input.value)
  );
}

  function getFieldValue(form, name) {
    var field = getField(form, name);

    if (!field || typeof field.value !== "string") {
      return "";
    }

    return field.value.trim();
  }


  function fitSubject(subject) {
    if (!subject) {
      return;
    }

    subject.style.fontSize = "";

    var computed = window.getComputedStyle(subject);
    var initialSize = parseFloat(computed.fontSize)
      || MAX_SUBJECT_SIZE_PX;

    var fontSize = Math.min(
      MAX_SUBJECT_SIZE_PX,
      initialSize
    );

    subject.style.fontSize = fontSize + "px";

    while (
      fontSize > MIN_SUBJECT_SIZE_PX
      && subject.scrollWidth > subject.clientWidth
    ) {
      fontSize -= SUBJECT_SIZE_STEP_PX;
      subject.style.fontSize = fontSize + "px";
    }

    subject.classList.add("is-fitted");
  }


  function ensureLocationElement(entriesContainer) {
    var location = entriesContainer.querySelector(
      ".lesson-entry__meta--location"
    );

    if (location) {
      return location;
    }

    location = document.createElement("div");
    location.className = (
      "lesson-entry__meta lesson-entry__meta--location"
    );

    entriesContainer.appendChild(location);

    return location;
  }


  function updateCardAriaLabel(
    card,
    title,
    timeStart,
    timeEnd,
    location,
  ) {
    if (!card) {
      return;
    }

    var parts = [
      "Дополнительное занятие",
      title,
      timeStart + "–" + timeEnd,
    ];

    if (location) {
      parts.push("Место: " + location);
    }

    card.setAttribute(
      "aria-label",
      parts.join(". ")
    );
  }


  function refreshPreview(form) {
    if (!(form instanceof HTMLFormElement)) {
      return;
    }

    var preview = form.querySelector("[data-extra-preview]");

    if (!preview) {
      return;
    }

    var card = preview.querySelector(".lesson-card");
    var titleElement = preview.querySelector(
      ".lesson-card__subject"
    );
    var startElement = preview.querySelector(
      ".lesson-card__start"
    );
    var endElement = preview.querySelector(
      ".lesson-card__end"
    );
    var entriesContainer = preview.querySelector(
      ".lesson-card__entries"
    );

    if (
      !card
      || !titleElement
      || !startElement
      || !endElement
      || !entriesContainer
    ) {
      return;
    }

    var title = getFieldValue(form, "title") || "Без названия";
    var timeStart = getFieldValue(form, "time_start") || "—";
    var timeEnd = getFieldValue(form, "time_end") || "—";
    var location = getFieldValue(form, "location");

    titleElement.textContent = title;
    titleElement.setAttribute("title", title);

    startElement.textContent = timeStart;
    endElement.textContent = timeEnd;

    var locationElement = ensureLocationElement(
      entriesContainer
    );

    locationElement.textContent = location;
    locationElement.hidden = !location;

    updateCardAriaLabel(
      card,
      title,
      timeStart,
      timeEnd,
      location,
    );

    fitSubject(titleElement);
  }


  function refreshPreviewFromElement(element) {
    if (!(element instanceof Element)) {
      return;
    }

    var form = element.closest("[data-extra-preview-form]");

    if (form instanceof HTMLFormElement) {
      refreshPreview(form);
    }
  }


  function refreshAllPreviews(root) {
    if (!(root instanceof Element)) {
      return;
    }

    if (root.matches("[data-extra-preview-form]")) {
      refreshPreview(root);
    }

    root
      .querySelectorAll("[data-extra-preview-form]")
      .forEach(function (form) {
        if (form instanceof HTMLFormElement) {
          refreshPreview(form);
        }
      });
  }


function installLivePreview() {
  document.addEventListener("click", function (event) {
    if (!(event.target instanceof Element)) {
      return;
    }

    var button = event.target.closest(
      "[data-reminder-adjust]"
    );

    if (!button) {
      return;
    }

    var stepper = button.closest(
      "[data-reminder-stepper]"
    );

    if (!stepper) {
      return;
    }

    var delta = Number.parseInt(
      button.dataset.reminderAdjust || "0",
      10
    );

    if (Number.isNaN(delta)) {
      return;
    }

    adjustReminder(stepper, delta);
  });

  document.addEventListener("input", function (event) {
    refreshPreviewFromElement(event.target);
  });

  document.addEventListener("change", function (event) {
    if (
      event.target instanceof Element
      && event.target.matches(
        'input[name="reminder_minutes"]'
      )
    ) {
      var stepper = event.target.closest(
        "[data-reminder-stepper]"
      );

      normalizeReminder(stepper);
    }

    refreshPreviewFromElement(event.target);
  });
}


  function initialize() {
    refreshAllPreviews(document.body);
    installLivePreview();
  }


  if (document.readyState === "loading") {
    document.addEventListener(
      "DOMContentLoaded",
      initialize,
    );
  } else {
    initialize();
  }


  document.body.addEventListener("htmx:load", function (event) {
    if (event.detail && event.detail.elt) {
      refreshAllPreviews(event.detail.elt);
    }
  });
})();