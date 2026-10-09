/* web/static/js/tg-app.js */

(function () {
  var titleEl = document.getElementById("tg-title");
  var descEl = document.getElementById("tg-desc");

  try {
    var tg = window.Telegram && window.Telegram.WebApp;

    if (!tg) {
      if (titleEl) titleEl.textContent = "Ошибка загрузки";
      if (descEl) descEl.textContent = "Не удалось загрузить Telegram SDK. Проверьте интернет.";
      return;
    }

    tg.ready();
    tg.expand();

    if (!tg.initData) {
      if (titleEl) titleEl.textContent = "Доступ запрещён";
      if (descEl) descEl.textContent = "Пожалуйста, откройте это окно по кнопке внутри Telegram-бота.";
      return;
    }

    if (titleEl) titleEl.textContent = "Авторизация...";
    if (descEl) descEl.textContent = "Связываемся с сервером...";

    fetch("/tg/bootstrap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        initData: tg.initData, 
        init_data: tg.initData,
        platform: tg.platform 
      })
    })
    // ---> ИЗМЕНЕНИЯ ЗДЕСЬ: Обработка JSON-ошибок от FastAPI <---
    .then(function (response) {
      if (!response.ok) {
        return response
          .json()
          .catch(function () { return null; })
          .then(function (errorPayload) {
            var detail = errorPayload && errorPayload.detail;
            throw new Error(detail || "auth_failed");
          });
      }
      return response.json();
    })
    .then(function (data) {
      if (data.ok || data.redirect) {
        if (titleEl) titleEl.textContent = "Успешно!";
        if (descEl) descEl.textContent = "Загружаем расписание...";
        window.location.replace(data.redirect || "/");
      } else {
        throw new Error("Сервер не подтвердил вход");
      }
    })
    // ---> ИЗМЕНЕНИЯ ЗДЕСЬ: Финальный вывод причины ошибки <---
    .catch(function (error) {
      var message = (
        error
        && error.message
        && error.message !== "auth_failed"
      )
        ? error.message
        : "Не удалось подтвердить вход. Вернитесь в бота и откройте расписание заново.";

      if (titleEl) titleEl.textContent = "Ошибка";
      if (descEl) descEl.textContent = message;
    });

  } catch (e) {
    if (titleEl) titleEl.textContent = "Критическая ошибка";
    if (descEl) descEl.textContent = e.message;
  }
})();