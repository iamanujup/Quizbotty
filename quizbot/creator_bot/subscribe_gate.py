"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.errors import UserNotParticipant
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from quizbot.shared import config

logger = logging.getLogger(__name__)

_JOIN_PROMPT_PHOTO = "https://graph.org/file/d44f024a08ded19452152.jpg"


async def subscribe_gate(app: Client, m: Message) -> bool:
    """Return True when the user must be blocked until joining the required channel."""
    user = m.from_user
    if user is None:
        return True

    # Preserve the existing LOG_GROUP ban check, but do not use group
    # membership as a substitute for REQUIRED_SUB_CHANNEL membership.
    if config.LOG_GROUP:
        try:
            log_member = await app.get_chat_member(config.LOG_GROUP, user.id)
            status = str(getattr(log_member.status, "value", log_member.status)).lower().split(".")[-1]
            if status == "banned":
                await m.reply_text("🚫 Banned")
                return True
        except UserNotParticipant:
            pass
        except Exception as exc:
            logger.warning("LOG_GROUP ban check failed for %s: %s", user.id, exc)

    channel = (config.REQUIRED_SUB_CHANNEL or "").strip()
    if not channel:
        logger.error("REQUIRED_SUB_CHANNEL is empty; blocking user rather than bypassing force-sub")
        await m.reply_text("⚠️ Channel verification is temporarily unavailable. Please try again later.")
        return True

    chat_id = channel
    if not chat_id.lstrip("-").isdigit() and not chat_id.startswith("@"):
        chat_id = "@" + chat_id

    try:
        member = await app.get_chat_member(chat_id, user.id)
        status = str(getattr(member.status, "value", member.status)).lower().split(".")[-1]
        is_member = status in {"member", "administrator", "creator", "owner"}
        if status == "restricted":
            is_member = bool(getattr(member, "is_member", False))
        if is_member:
            return False
    except UserNotParticipant:
        pass
    except Exception as exc:
        logger.error("Required channel membership check failed for user %s: %s", user.id, exc)
        await m.reply_text(
            "⚠️ सदस्यता जाँच अभी नहीं हो पा रही है। कृपया कुछ देर बाद फिर कोशिश करें।"
        )
        return True

    channel_username = channel.lstrip("@").lstrip("-")
    await m.reply_text(
        "🔒 MOCKS MARG — Join Required\n\n"
        "Quiz शुरू करने से पहले हमारे Telegram चैनल को जॉइन करें।\n\n"
        "1. JOIN CHANNEL दबाकर चैनल जॉइन करें।\n"
        "2. वापस आकर RETRY / VERIFY दबाएँ।\n\n"
        "सदस्यता सफलतापूर्वक जाँचने के बाद आपका Bot खुलेगा।",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📢 JOIN CHANNEL", url=f"https://t.me/{channel_username}")],
            [InlineKeyboardButton("🔄 RETRY / VERIFY", url="https://t.me/mockmargjubot?start=home")],
        ]),
        disable_web_page_preview=True,
    )
    return True
