/* Telegram Mini App surface adapter.
 *
 * Подключается ТОЛЬКО при surface_mode == "telegram" (см. base.html).
 * Обязанности: ready/theme + кнопка «Открыть в браузере».
 * Никакой логики расписания и HTMX здесь быть не должно.
 */
(function () {
  "use strict";

  var tg = window.Telegram && window.Telegram.WebApp;
  if (!tg) {
    return;
  }

  tg.ready();

  function csrfToken() {
    var raw = document.body.getAttribute("hx-headers");
    if (!raw) {
      return "";
    }
    try {
      return JSON.parse(raw)["X-CSRF-Token"] || "";
    } catch (error) {
      return "";
    }
  }

  document.addEventListener("click", function (event) {
    var button = event.target.closest("#tg-open-browser");
    if (!button) {
      return;
    }
    event.preventDefault();

    fetch("/tg/browser-handoff", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "X-CSRF-Token": csrfToken(),
      },
    })
      .then(function (response) {
        if (!response.ok) {
          throw new Error("handoff_failed");
        }
        return response.json();
      })
      .then(function (data) {
        if (data && data.external_url) {
          tg.openLink(data.external_url);
        }
      })
      .catch(function () {
        if (
          tg.HapticFeedback
          && tg.HapticFeedback.notificationOccurred
        ) {
          tg.HapticFeedback.notificationOccurred("error");
        }
        button.setAttribute("aria-disabled", "true");
        setTimeout(function () {
          button.removeAttribute("aria-disabled");
        }, 2000);
      });
  });
})();