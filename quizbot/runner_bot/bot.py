
"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from telegram import Update
from telegram.ext import Application
from telegram.request import HTTPXRequest

from quizbot.shared import config

from . import handlers
from .handlers.admin import watchdog_loop
from .handlers.scheduling import init_schedule_manager
from .state import tasks

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler()


async def post_init(application: Application) -> None:
    """Start scheduler and watchdog."""

    init_schedule_manager(scheduler)
    scheduler.start()

    tasks.spawn(
        watchdog_loop(),
        name="watchdog",
    )

    logger.info(
        "Runner Bot post_init complete (scheduler + watchdog started)."
    )


async def post_shutdown(application: Application) -> None:
    """Stop scheduler."""

    scheduler.shutdown(wait=False)

    logger.info(
        "Runner Bot post_shutdown complete."
    )


def build_application() -> Application:
    """Construct PTB Application with timeout configuration."""

    api_request = HTTPXRequest(
        connection_pool_size=32,
        connect_timeout=30,
        read_timeout=60,
        write_timeout=30,
        pool_timeout=30,
    )

    polling_request = HTTPXRequest(
        connection_pool_size=4,
        connect_timeout=30,
        read_timeout=60,
        write_timeout=30,
        pool_timeout=30,
    )

    application = (
        Application.builder()
        .token(config.RUNNER_BOT_TOKEN)
        .request(api_request)
        .get_updates_request(polling_request)
        .get_updates_read_timeout(60)
        .concurrent_updates(True)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    handlers.register(application)

    return application


async def run_runner_bot() -> None:
    """Run Runner Bot with manual PTB lifecycle."""

    application = build_application()

    initialized = False
    started = False
    polling_started = False

    try:
        await application.initialize()
        initialized = True

        await application.start()
        started = True

        await application.updater.start_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True,
            timeout=20,
            read_timeout=60,
        )

        polling_started = True

        logger.info("Runner Bot polling started.")

        # Wait until launcher requests shutdown.
        await asyncio.Future()

    finally:
        logger.info("Runner Bot shutting down...")

        if polling_started:
            try:
                await application.updater.stop()
            except Exception:
                logger.exception(
                    "Error while stopping Runner Bot polling"
                )

        if started:
            try:
                await application.stop()
            except Exception:
                logger.exception(
                    "Error while stopping Runner Bot application"
                )

        if initialized:
            try:
                await application.shutdown()
            except Exception:
                logger.exception(
                    "Error while shutting down Runner Bot application"
                )
