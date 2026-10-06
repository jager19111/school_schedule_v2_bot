# web/htmx.py
"""
Общие HTTP/HTMX-предикаты для web-слоя.

В приложении существуют три легитимных режима HTML-ответа:

1. Обычная навигация браузера:
   server возвращает полную HTML-страницу.

2. Локальный HTMX fragment:
   например, #day-content, #settings-content или #extra-content.
   Server возвращает только нужный fragment.

3. Верхнеуровневая app-shell navigation:
   HTMX запрашивает страницу, но target равен #app-shell.
   Server намеренно возвращает полную страницу, а клиент выбирает из
   response только #app-shell через hx-select="#app-shell".

Важно: app-shell navigation нельзя определять только по HX-Request.
Все локальные HTMX-взаимодействия также содержат HX-Request: true.
"""

from __future__ import annotations

from fastapi import Request


APP_SHELL_TARGET = "app-shell"


def is_htmx_request(request: Request) -> bool:
    """Возвращает True для любого HTMX HTTP-запроса."""
    return request.headers.get("HX-Request") == "true"


def is_app_shell_request(request: Request) -> bool:
    """
    Возвращает True только для верхнеуровневой HTMX-навигации.

    Будущие ссылки нижней навигации будут использовать:

        hx-target="#app-shell"
        hx-select="#app-shell"
        hx-swap="outerHTML"

    HTMX отправляет имя target без символа '#', поэтому сервер получает:

        HX-Target: app-shell
    """
    return (
        is_htmx_request(request)
        and request.headers.get("HX-Target") == APP_SHELL_TARGET
    )

def is_history_restore_request(request: Request) -> bool:
    """
    Возвращает True, когда HTMX восстанавливает history entry,
    отсутствующий в client-side history cache.

    HTMX отправляет такой request с:

        HX-Request: true
        HX-History-Restore-Request: true

    В этом режиме server обязан вернуть full page template, а не local
    fragment. Иначе history restore может заменить часть document fragment
    response-ом и визуально потерять header/shell после серии Back.
    """
    return (
        is_htmx_request(request)
        and request.headers.get(
            "HX-History-Restore-Request"
        ) == "true"
    )

def select_page_or_fragment_template(
    request: Request,
    *,
    page_template: str,
    fragment_template: str,
) -> str:
    """
    Выбирает template для стандартного page/fragment route.

    Приоритет намеренный:

    1. App-shell HTMX navigation получает full page template.
       Клиент выберет #app-shell с помощью hx-select.

    2. Обычный HTMX request получает local fragment template.

    3. Обычная browser navigation получает full page template.

    Это сохраняет progressive enhancement: каждый href остаётся рабочим
    без JavaScript и без HTMX.
    """
    if (
        is_app_shell_request(request)
        or is_history_restore_request(request)
    ):
        return page_template

    if is_htmx_request(request):
        return fragment_template

    return page_template