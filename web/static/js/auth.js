// web/static/js/auth.js
//
// Обработка magic-link входа (ТЗ 11-12):
// 1. Токен читается из URL fragment (#token=...), который НЕ уходит
//    на сервер и не попадает в логи/referrer.
// 2. Токен отправляется на POST /api/v1/auth/exchange.
// 3. После успешного обмена fragment стирается переходом на "/".
// 4. Никакой бизнес-логики: только вход и переход.

(function () {
    "use strict";

    var statusEl = document.getElementById("status");

    function setStatus(text) {
        if (statusEl) {
            statusEl.textContent = text;
        }
    }

    function readTokenFromFragment() {
        var hash = window.location.hash || "";
        if (hash.indexOf("#token=") !== 0) {
            return null;
        }
        return hash.substring("#token=".length) || null;
    }

    function clearFragment() {
        // history.replaceState не триггерит перезагрузку и убирает
        // токен из адресной строки.
        window.history.replaceState(null, "", window.location.pathname);
    }

    function exchange(token) {
        fetch("/api/v1/auth/exchange", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ token: token }),
            credentials: "same-origin",
            cache: "no-store"
        })
            .then(function (response) {
                if (response.status === 401) {
                    // Обобщённое сообщение: причина не раскрывается.
                    setStatus(
                        "Ссылка недействительна или истекла. " +
                        "Запросите новую в Telegram-боте."
                    );
                    clearFragment();
                    return null;
                }
                if (!response.ok) {
                    setStatus("Временная ошибка. Попробуйте позже.");
                    return null;
                }
                return response.json();
            })
            .then(function (data) {
                if (!data) {
                    return;
                }
                clearFragment();
                // Полный переход на dashboard затирает URL с токеном
                // из истории навигации.
                window.location.replace(data.redirect || "/");
            })
            .catch(function () {
                setStatus("Нет соединения с сервером.");
            });
    }

    var token = readTokenFromFragment();
    if (token) {
        exchange(token);
    } else {
        // Без токена: пользователь, возможно, уже авторизован —
        // пробуем dashboard, иначе его отправит на вход.
        window.location.replace("/");
    }
})();
