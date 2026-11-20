
"""
Advance Quiz Bot — Creator Bot
FloodWait protection and safe startup retry.
"""

from __future__ import annotations

import asyncio
import logging

from pyrogram import Client
from pyrogram.errors import FloodWait

from quizbot.shared import config

logger = logging.getLogger(__name__)


def build_client() -> Client:
    """Build Creator Bot client with persistent session."""

    return Client(
        "creator_bot",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.CREATOR_BOT_TOKEN,
        workers=50,
    )


async def wait_for_retry(
    stop_event: asyncio.Event,
    seconds: int,
) -> None:
    """Wait without blocking other bot tasks."""

    logger.warning(
        "Creator Bot waiting %s seconds before retry.",
        seconds,
    )

    try:
        await asyncio.wait_for(
            stop_event.wait(),
            timeout=seconds,
        )
    except asyncio.TimeoutError:
        pass


async def run_creator_bot(
    stop_event: asyncio.Event | None = None,
) -> None:
    """Start Creator Bot with FloodWait protection."""

    own_event = stop_event or asyncio.Event()

    while not own_event.is_set():

        app = build_client()

        from .handlers import register

        try:
            register(app)

            await app.start()

            me = await app.get_me()

            logger.info(
                "Creator Bot started as @%s",
                me.username,
            )

            await own_event.wait()
            return

        except asyncio.CancelledError:
            raise

        except FloodWait as error:

            delay = max(int(error.value), 1) + 5

            logger.warning(
                "Telegram FloodWait: waiting %s seconds.",
                delay,
            )

            await wait_for_retry(
                own_event,
                delay,
            )

        finally:

            if app.is_connected:
                try:
                    await app.stop()

                    logger.info(
                        "Creator Bot stopped."
                    )

                except Exception:
                    logger.exception(
                        "Creator Bot shutdown error."
                    )


if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO,
    )

    asyncio.run(
        run_creator_bot()
    )
