#!/usr/bin/env python3
"""
Advance Quiz Bot — Open Source Project
Render Web Service compatible launcher.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys

from quizbot.database import init_db, close_db
from quizbot.shared import config
from quizbot.shared.utils.http import close_session

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
)

logger = logging.getLogger("launcher")

# Silence noisy third-party debug logs.
for noisy in ("httpx", "httpcore", "apscheduler", "pymongo"):
    logging.getLogger(noisy).setLevel(logging.WARNING)


async def _run_creator_bot() -> None:
    from quizbot.creator_bot.bot import run_creator_bot

    logger.info("Starting Creator Bot (Pyrogram)...")
    await run_creator_bot()


async def _run_runner_bot() -> None:
    from quizbot.runner_bot.bot import run_runner_bot

    logger.info("Starting Runner Bot (python-telegram-bot)...")
    await run_runner_bot()


async def _run_mini_app() -> None:
    from quizbot.mini_app.server import run_mini_app_server

    logger.info("Starting Mini App server (FastAPI)...")
    await run_mini_app_server()


async def _run_render_health_server() -> None:
    """
    Small HTTP server for Render Web Service.
    Keeps the Render service alive and provides a health endpoint.
    """

    port = int(os.environ.get("PORT", "10000"))

    async def handle_client(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            await reader.read(4096)

            body = b'{"status":"ok","service":"quizbotty"}'

            response = (
                b"HTTP/1.1 200 OK\r\n"
                b"Content-Type: application/json\r\n"
                b"Content-Length: "
                + str(len(body)).encode()
                + b"\r\n"
                b"Connection: close\r\n"
                b"\r\n"
                + body
            )

            writer.write(response)
            await writer.drain()

        except Exception:
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:
                pass

    server = await asyncio.start_server(
        handle_client,
        host="0.0.0.0",
        port=port,
    )

    addresses = ", ".join(str(sock.getsockname()) for sock in server.sockets or [])

    logger.info("Render health server listening on %s", addresses)

    async with server:
        await server.serve_forever()


async def main(only: str | None) -> None:
    problems = config.validate(bot=only or "both")

    if problems:
        for p in problems:
            logger.error("Config problem: %s", p)

        logger.error(
            "Fix the above in your .env file (see .env.example) before starting."
        )
        sys.exit(1)

    logger.info(
        "Connecting to MongoDB (db=%s) ...",
        config.MONGODB_DB_NAME,
    )

    await init_db(
        config.MONGODB_URI,
        config.MONGODB_DB_NAME,
    )

    logger.info("Database ready.")

    tasks: list[asyncio.Task] = []

    # Creator Bot
    if only in (None, "creator"):
        tasks.append(
            asyncio.create_task(
                _run_creator_bot(),
                name="creator_bot",
            )
        )

    # Runner Bot
    if only in (None, "runner"):
        tasks.append(
            asyncio.create_task(
                _run_runner_bot(),
                name="runner_bot",
            )
        )

    # Mini App
    mini_app_enabled = False

    if only == "miniapp":
        mini_app_enabled = True
        tasks.append(
            asyncio.create_task(
                _run_mini_app(),
                name="mini_app",
            )
        )

    elif only is None and config.MINI_APP_DOMAIN:
        mini_app_enabled = True
        tasks.append(
            asyncio.create_task(
                _run_mini_app(),
                name="mini_app",
            )
        )

    # ---------------------------------------------------------
    # Render Web Service PORT
    # ---------------------------------------------------------
    #
    # If Mini App is not running, start a tiny HTTP server
    # so Render detects an open port.
    #
    if not mini_app_enabled:
        tasks.append(
            asyncio.create_task(
                _run_render_health_server(),
                name="render_health_server",
            )
        )

    stop_event = asyncio.Event()

    def _handle_signal(*_args):
        logger.info("Shutdown signal received, stopping bots...")
        stop_event.set()

    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(
                sig,
                _handle_signal,
            )
        except NotImplementedError:
            pass

    try:
        stop_task = asyncio.create_task(
            stop_event.wait(),
            name="stop_event",
        )

        all_tasks = [*tasks, stop_task]

        done, pending = await asyncio.wait(
            all_tasks,
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in done:
            if task is stop_task:
                continue

            if task.cancelled():
                continue

            exception = task.exception()

            if exception:
                logger.error(
                    "Task %s crashed: %s",
                    task.get_name(),
                    exception,
                    exc_info=exception,
                )

        # Cancel remaining tasks if one of the main tasks exits.
        for task in pending:
            task.cancel()

        await asyncio.gather(
            *pending,
            return_exceptions=True,
        )

    finally:
        logger.info("Shutting down...")

        for task in tasks:
            if not task.done():
                task.cancel()

        await asyncio.gather(
            *tasks,
            return_exceptions=True,
        )

        await close_session()
        await close_db()

        logger.info("Shutdown complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Run the Advance Quiz Bot platform."
    )

    parser.add_argument(
        "--only",
        choices=["creator", "runner", "miniapp"],
        default=None,
        help=(
            "Run only one component. "
            "Default: run both bots, plus Mini App "
            "if MINI_APP_DOMAIN is configured."
        ),
    )

    args = parser.parse_args()

    try:
        asyncio.run(main(args.only))

    except KeyboardInterrupt:
        pass
