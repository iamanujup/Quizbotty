
from __future__ import annotations

import asyncio
import logging
import random
from typing import Any, Optional

from telegram.error import (
    BadRequest,
    NetworkError,
    RetryAfter,
    TelegramError,
    TimedOut,
)
from telegram.ext import ContextTypes

from .state import pending_quiz_settings, session_mgr

logger = logging.getLogger(__name__)

TG_QUESTION_MAX = 300
TG_OPTION_MAX = 100
TG_EXPLANATION_MAX = 200
TG_DESCRIPTION_MAX = 1024

QUESTION_SOFT_LIMIT = 290
OPTION_SOFT_LIMIT = 100
EXPLANATION_TRIM = 200

MAX_RETRIES = 5
RETRY_BASE_DELAY = 1.5
POLL_SEND_DELAY = 0.3


async def send_raw_api(
    ctx: ContextTypes.DEFAULT_TYPE,
    method: str,
    params: dict[str, Any],
) -> Any:
    """Adapter used by rich_quiz."""
    return await ctx.bot.do_api_request(method, api_kwargs=params)


def _get_topic_thread_id(chat_id: int) -> Optional[int]:
    """Return message_thread_id from active session or pending settings."""
    s = session_mgr.get(chat_id)

    if s and s.get("message_thread_id"):
        return s["message_thread_id"]

    ps = pending_quiz_settings.get(chat_id)

    if ps and ps.get("message_thread_id"):
        return ps["message_thread_id"]

    return None


async def safe_send_message(
    ctx: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    text: str,
    **kwargs: Any,
) -> Optional[Any]:
    """Send a message with retry on errors."""

    if "message_thread_id" not in kwargs:
        tid = _get_topic_thread_id(chat_id)
        if tid:
            kwargs["message_thread_id"] = tid

    for attempt in range(MAX_RETRIES):
        try:
            return await ctx.bot.send_message(
                chat_id=chat_id,
                text=text,
                **kwargs,
            )

        except RetryAfter as e:
            await asyncio.sleep(
                e.retry_after + random.uniform(0.5, 2.0)
            )

        except (TimedOut, NetworkError):
            await asyncio.sleep(
                RETRY_BASE_DELAY * (2 ** attempt) + random.random()
            )

        except BadRequest as e:
            logger.error(
                "BadRequest sending message to %s: %s",
                chat_id,
                e,
            )
            return None

        except TelegramError as e:
            if (
                "chat not found" in str(e).lower()
                or "bot was blocked" in str(e).lower()
            ):
                return None

            await asyncio.sleep(
                RETRY_BASE_DELAY * (2 ** attempt)
            )

        except Exception as e:
            logger.error("Unexpected send error: %s", e)
            return None

    logger.error(
        "Failed to send message to %s after %d retries",
        chat_id,
        MAX_RETRIES,
    )
    return None


async def safe_send_poll(
    ctx: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    question: str,
    options: list[str],
    **kwargs: Any,
) -> Optional[Any]:
    """Send a poll with retry on errors."""

    if "message_thread_id" not in kwargs:
        tid = _get_topic_thread_id(chat_id)
        if tid:
            kwargs["message_thread_id"] = tid

    for attempt in range(MAX_RETRIES):
        try:
            return await ctx.bot.send_poll(
                chat_id=chat_id,
                question=question,
                options=options,
                **kwargs,
            )

        except RetryAfter as e:
            await asyncio.sleep(
                e.retry_after + random.uniform(1.0, 3.0)
            )

        except (TimedOut, NetworkError):
            await asyncio.sleep(
                RETRY_BASE_DELAY * (2 ** attempt) + random.random()
            )

        except BadRequest as e:
            err_msg = str(e).lower()

            logger.error(
                "BadRequest sending poll to %s: %s",
                chat_id,
                e,
            )

            if (
                "too long" in err_msg
                or "too short" in err_msg
                or "chat not found" in err_msg
            ):
                return None

            await asyncio.sleep(
                RETRY_BASE_DELAY * (attempt + 1)
            )

        except TelegramError as e:
            if (
                "chat not found" in str(e).lower()
                or "not enough rights" in str(e).lower()
            ):
                logger.error(
                    "Cannot send poll to %s: %s",
                    chat_id,
                    e,
                )
                return None

            await asyncio.sleep(
                RETRY_BASE_DELAY * (2 ** attempt)
            )

        except Exception as e:
            logger.error("Unexpected poll error: %s", e)
            return None

    logger.error(
        "Failed to send poll to %s after %d retries",
        chat_id,
        MAX_RETRIES,
    )
    return None


def _truncate(text: str, limit: int) -> str:
    """Truncate text safely within Telegram limits."""

    if len(text) <= limit:
        return text

    return text[: limit - 3].rstrip() + "..."


def prepare_poll_data(
    question_text: str,
    options: list[str],
    correct_option_id: int,
    explanation: Optional[str],
    reply_text: Optional[str],
    question_index: int,
    total_questions: int,
) -> tuple[str, list[str], Optional[str], Optional[str], Optional[str]]:
    """
    Prepare Telegram quiz poll.

    - Actual question appears in poll title.
    - Original option text is retained.
    - Explanation and examples appear in bulb.
    - Long content is retained in description/overflow.
    """

    prefix = f"[{question_index + 1}/{total_questions}] "

    full_body = (question_text or "").strip()
    full_question = f"{prefix}{full_body}"

    # IMPORTANT: Use the actual question, not generic placeholder.
    poll_question = _truncate(
        full_question,
        TG_QUESTION_MAX,
    )

    question_was_truncated = (
        len(full_question) > TG_QUESTION_MAX
    )

    # Preserve original options individually.
    poll_options: list[str] = []
    long_options: list[tuple[int, str]] = []

    for i, option in enumerate(options):
        original = str(option or "").strip() or "—"

        if len(original) > TG_OPTION_MAX:
            long_options.append((i, original))

        poll_options.append(
            _truncate(original, TG_OPTION_MAX)
        )

    # Prepare description.
    desc_parts: list[str] = []

    if question_was_truncated:
        desc_parts.append(
            f"Q{question_index + 1}/{total_questions}: {full_body}"
        )

    if reply_text and reply_text.strip():
        desc_parts.append(
            f"📝 {reply_text.strip()}"
        )

    if long_options:
        desc_parts.append("Options:")

        for i, original in long_options:
            desc_parts.append(
                f"{chr(65 + i)}) {original}"
            )

    description_text = (
        "\n\n".join(desc_parts)
        if desc_parts else None
    )

    overflow_text = None
    poll_description = None

    if description_text:
        if len(description_text) <= TG_DESCRIPTION_MAX:
            poll_description = description_text
        else:
            overflow_text = description_text

    # Bulb explanation + example/reference.
    explanation_text = (explanation or "").strip()
    reference_text = (reply_text or "").strip()

    if explanation_text and reference_text:
        separator = " | उदाहरण: "

        reference_text = _truncate(
            reference_text,
            80,
        )

        explanation_limit = max(
            1,
            TG_EXPLANATION_MAX
            - len(separator)
            - len(reference_text),
        )

        bulb_text = (
            _truncate(explanation_text, explanation_limit)
            + separator
            + reference_text
        )

    elif reference_text:
        bulb_text = "उदाहरण: " + _truncate(
            reference_text,
            TG_EXPLANATION_MAX - len("उदाहरण: "),
        )

    else:
        bulb_text = explanation_text

    poll_explanation = (
        _truncate(bulb_text, TG_EXPLANATION_MAX)
        if bulb_text else None
    )

    return (
        poll_question,
        poll_options,
        poll_explanation,
        overflow_text,
        poll_description,
    )
