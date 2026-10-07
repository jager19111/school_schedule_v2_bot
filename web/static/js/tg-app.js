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

    // ---> ИЗМЕНЕНИЯ ЗДЕСЬ: добавили platform: tg.platform в JSON.stringify <---
    fetch("/tg/bootstrap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ 
        initData: tg.initData, 
        init_data: tg.initData,
        platform: tg.platform 
      })
    })
    .then(function (response) {
      if (!response.ok) {
        return response.text().then(function(text) {
          throw new Error("HTTP " + response.status + ": " + text.substring(0, 50));
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
    .catch(function (error) {
      if (titleEl) titleEl.textContent = "Ошибка сервера";
      if (descEl) descEl.textContent = error.message;
    });

  } catch (e) {
    if (titleEl) titleEl.textContent = "Критическая ошибка";
    if (descEl) descEl.textContent = e.message;
  }
})();