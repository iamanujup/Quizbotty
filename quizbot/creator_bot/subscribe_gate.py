"""
Advance Quiz Bot — Channel Subscription Verification
"""

from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.errors import UserNotParticipant
from pyrogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from quizbot.shared import config

logger = logging.getLogger(__name__)

_JOIN_PROMPT_PHOTO = "https://graph.org/file/d44f024a08ded19452152.jpg"


async def subscribe_gate(app: Client, m: Message) -> bool:
    """
    Block command if user is banned from LOG_GROUP
    or is not a member of REQUIRED_SUB_CHANNEL.
    """

    user_id = m.from_user.id

    # 1. Check whether user is banned from LOG_GROUP.
    if config.LOG_GROUP:
        try:
            member = await app.get_chat_member(
                config.LOG_GROUP,
                user_id,
            )

            status = str(member.status).lower()

            if "banned" in status:
                await m.reply_text("🚫 Banned")
                return True

        except UserNotParticipant:
            # Not being in LOG_GROUP does not mean
            # the user has not joined the required channel.
            pass

        except Exception as exc:
            logger.warning(
                "LOG_GROUP membership check failed: %s",
                exc,
            )

    # 2. Check REQUIRED_SUB_CHANNEL separately.
    if not config.REQUIRED_SUB_CHANNEL:
        return False

    channel = config.REQUIRED_SUB_CHANNEL.strip()

    try:
        member = await app.get_chat_member(
            channel,
            user_id,
        )

        status = str(member.status).lower()

        is_member = (
            "member" in status
            or "administrator" in status
            or "owner" in status
        )

        if "restricted" in status:
            is_member = bool(
                getattr(member, "is_member", False)
            )

        if is_member:
            return False

    except UserNotParticipant:
        pass

    except Exception as exc:
        logger.exception(
            "Required channel membership check failed: %s",
            exc,
        )
        return False

    # 3. User has not joined the required channel.
    join_channel = channel.lstrip("@")

    await m.reply_photo(
        _JOIN_PROMPT_PHOTO,
        caption="📢 Please join our channel to continue.",
        reply_markup=InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🔗 Join",
                        url=f"https://t.me/{join_channel}",
                    )
                ]
            ]
        ),
    )

    return True
