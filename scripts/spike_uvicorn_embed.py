"""Spike: uvicorn.Server.serve() внутри существующего asyncio event loop.

Цель (Phase 0, раздел 5 отчёта): эмпирически проверить координацию
SIGINT/SIGTERM между uvicorn и приложением-владельцем loop'а
(бот + APScheduler + shared SQLite).

Проверяемая цепочка (uvicorn >= 0.30):
  1. Приложение регистрирует loop.add_signal_handler(SIGINT/SIGTERM).
  2. server.serve() через capture_signals() временно ставит СВОИ
     signal-хендлеры (замещая хендлеры приложения).
  3. Сигнал №1 -> uvicorn.handle_exit -> should_exit=True -> serve()
     завершается, хендлеры приложения восстанавливаются, пойманный
     сигнал re-raise'ится.
  4. Хендлер приложения запускает его собственный graceful shutdown.

Запуск: python scripts/spike_uvicorn_embed.py
Тест: curl http://127.0.0.1:8300/health/live, затем kill -TERM <pid>.
Ожидаемый лог: serve stopped -> app handlers restored -> app shutdown
в порядке: web -> worker -> done. Второй сигнал не ломает процесс.
"""

from __future__ import annotations

import asyncio
import signal
import time

import uvicorn
from fastapi import FastAPI
from fastapi.responses import StreamingResponse

app = FastAPI(title="spike")

SHUTDOWN_ORDER: list[str] = []


@app.get("/health/live")
async def live() -> dict:
    return {"status": "live"}


@app.get("/stream")
async def stream() -> StreamingResponse:
    """Имитация SSE: долгоживущее соединение, мешающее graceful shutdown."""

    async def gen():
        while True:
            yield ": heartbeat\n\n"
            await asyncio.sleep(1)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


async def main() -> None:
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=8300,
        workers=1,
        loop="asyncio",
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        # Не ждать закрытия долгоживущих соединений бесконечно:
        timeout_graceful_shutdown=5,
        log_level="info",
    )
    server = uvicorn.Server(config)

    loop = asyncio.get_running_loop()
    shutdown_started = asyncio.Event()
    t0 = time.monotonic()

    def log(msg: str) -> None:
        print(f"[spike +{time.monotonic() - t0:6.1f}s] {msg}", flush=True)

    # 1. Хендлеры ПРИЛОЖЕНИЯ (в проде: остановка scheduler/bot/DB).
    def handle_signal(signame: str) -> None:
        log(f"APP handler fired: {signame}")
        if shutdown_started.is_set():
            log("second signal ignored")
            return
        shutdown_started.set()
        server.should_exit = True  # останавливаем uvicorn первым

    for signame in ("SIGINT", "SIGTERM"):
        loop.add_signal_handler(
            getattr(signal, signame), handle_signal, signame
        )

    # 2. Имитация подсистем приложения (bot polling / scheduler).
    async def worker(name: str) -> None:
        try:
            while True:
                await asyncio.sleep(1)
        except asyncio.CancelledError:
            log(f"worker {name}: cancelled")
            raise

    workers = [
        asyncio.create_task(worker("bot-polling"), name="bot-polling"),
        asyncio.create_task(worker("scheduler"), name="scheduler"),
    ]

    # 3. Embedded запуск uvicorn.
    web_task = asyncio.create_task(server.serve(), name="web-server")
    log("web server started on http://127.0.0.1:8300")

    await web_task
    SHUTDOWN_ORDER.append("web-server")
    log("web_task finished (serve() returned)")

    # 4. Shutdown остальных подсистем ПОСЛЕ web (порядок ТЗ 7.4).
    for w in workers:
        w.cancel()
    await asyncio.gather(*workers, return_exceptions=True)
    SHUTDOWN_ORDER.append("workers")
    log(f"app shutdown done, order={SHUTDOWN_ORDER}")


if __name__ == "__main__":
    asyncio.run(main())
