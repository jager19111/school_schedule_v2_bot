// web/static/js/auth.js
//
// Обработка magic-link входа:
//
// 1. Token читается из URL fragment (#token=...), который не уходит
//    на сервер при GET /auth и не попадает в referrer.
// 2. Token отправляется только POST request-ом на auth exchange endpoint.
// 3. После успешного exchange browser получает web session и переходит
//    на dashboard.
// 4. Без token страница остаётся friendly public auth gate, а не
//    перенаправляет посетителя на закрытый dashboard.
// 5. Детали invalid token не раскрываются пользователю.


(function () {
    "use strict";

    var statusEl = document.getElementById("status");
    var helpEl = document.getElementById("auth-help");

    function setStatus(text) {
        if (statusEl) {
            statusEl.textContent = text;
        }
    }

    function showHelp() {
        if (helpEl) {
            helpEl.hidden = false;
        }
    }

    function hideHelp() {
        if (helpEl) {
            helpEl.hidden = true;
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
        /*
         * history.replaceState не вызывает page reload и удаляет token
         * из address bar / current browser history entry.
         *
         * /auth не использует query parameters, поэтому pathname здесь
         * достаточно.
         */
        window.history.replaceState(
            null,
            "",
            window.location.pathname
        );
    }

    function showAccessHelp() {
        setStatus(
            "Вход доступен по одноразовой ссылке из Telegram-бота."
        );
        showHelp();
    }

    function showInvalidLink() {
        setStatus(
            "Не удалось войти. Эта защищённая ссылка уже использована, "
            + "истекла или недействительна. Вернитесь в Telegram-бота "
            + "и запросите новую ссылку."
        );
        showHelp();
    }

    // Проверка на запуск в режиме PWA (с экрана "Домой")
    function isStandalone() {
        return (
            window.matchMedia("(display-mode: standalone)").matches
            || window.navigator.standalone === true
        );
    }

    function exchange(token) {
        setStatus("Проверяем защищённую ссылку…");
        hideHelp();

        fetch("/api/v1/auth/exchange", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                token: token,
                is_standalone: isStandalone() // <--- Добавили флаг PWA
            }),
            credentials: "same-origin",
            cache: "no-store"
        })
            .then(function (response) {
                if (response.status === 401) {
                    /*
                     * Backend намеренно не раскрывает, что именно произошло:
                     * token истёк, использован, неизвестен или принадлежит
                     * другому security context.
                     */
                    clearFragment();
                    showInvalidLink();
                    return null;
                }

                if (!response.ok) {
                    setStatus(
                        "Временная ошибка входа. Попробуйте открыть "
                        + "ссылку ещё раз немного позже."
                    );
                    return null;
                }

                return response.json();
            })
            .then(function (data) {
                if (!data) {
                    return;
                }

                clearFragment();
                setStatus("Вход выполнен. Открываем расписание…");

                /*
                 * replace(), а не href:
                 * auth URL с fragment token не остаётся полезной записью
                 * в browser history.
                 */
                window.location.replace(
                    data.redirect || "/"
                );
            })
            .catch(function () {
                /*
                 * Fragment намеренно не очищаем:
                 * при failure до получения HTTP response пользователь может
                 * повторить request, не запрашивая новую link.
                 */
                setStatus(
                    "Нет соединения с сервером. Проверьте интернет "
                    + "и попробуйте открыть ссылку ещё раз."
                );
            });
    }

    var token = readTokenFromFragment();

    if (token) {
        exchange(token);
    } else {
        /*
         * Раньше здесь был redirect на "/".
         *
         * Его удаляем: public /auth становится спокойной информационной
         * страницей, не раскрывает dashboard и не создаёт reload loop
         * для случайного посетителя.
         */
        showAccessHelp();
    }
})();