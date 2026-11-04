from __future__ import annotations

import base64
import html
import logging
import re
from typing import Any, Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, ContextTypes

from quizbot.shared.utils.http import request_json
from quizbot.ai_providers import ai_generate, get_provider_keys
from quizbot.telegram_utils import safe_send_message

logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 12000
TELEGRAM_MESSAGE_LIMIT = 4000
MAX_IMAGE_SIZE = 19 * 1024 * 1024


def _clean_question(text: str) -> str:
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"^/solve(?:@\w+)?\s*", "", text, flags=re.IGNORECASE)
    return text.strip()


def _get_poll_text(message: Any) -> Optional[str]:
    poll = getattr(message, "poll", None)
    if not poll:
        return None

    question = str(getattr(poll, "question", "") or "").strip()
    options = []
    for index, option in enumerate(getattr(poll, "options", []) or []):
        option_text = str(getattr(option, "text", "") or "").strip()
        if option_text:
            options.append(f"{chr(65 + index)}) {option_text}")

    parts = []
    if question:
        parts.append(question)
    if options:
        parts.append("Options:\n" + "\n".join(options))
    return "\n\n".join(parts).strip() or None


def _get_replied_text(message: Any) -> Optional[str]:
    reply = getattr(message, "reply_to_message", None)
    if not reply:
        return None

    poll_text = _get_poll_text(reply)
    if poll_text:
        return poll_text

    text = getattr(reply, "text", None)
    if text:
        return _clean_question(str(text))

    caption = getattr(reply, "caption", None)
    if caption:
        return _clean_question(str(caption))

    return None


def _get_replied_image(message: Any) -> Optional[tuple[str, str]]:
    reply = getattr(message, "reply_to_message", None)
    if not reply:
        return None

    photos = getattr(reply, "photo", None)
    if photos:
        try:
            largest = photos[-1]
            file_id = getattr(largest, "file_id", None)
            if file_id:
                return file_id, "image/jpeg"
        except Exception:
            pass

    document = getattr(reply, "document", None)
    if document:
        mime_type = getattr(document, "mime_type", None) or ""
        if mime_type.startswith("image/"):
            file_id = getattr(document, "file_id", None)
            if file_id:
                return file_id, mime_type

    return None


def _build_text_prompt(question: str, pro: bool = False) -> str:
    mode = (
        "PRO MODE: Give a more detailed competitive-exam solution, verify every "
        "calculation, and provide the most useful shortcut."
        if pro else
        "NORMAL MODE: Give a concise, accurate and exam-oriented solution."
    )

    return f"""You are an expert competitive-exam question solver.

{mode}

Solve the following question accurately.

QUESTION:
{question}

STRICT OUTPUT RULES:
1. Understand the complete question before solving.
2. If options are present, check them against the actual solution.
3. Verify all calculations.
4. Do not rewrite the question or options.
5. Use exactly four sections:
Answer
Shortcut Trick
Verification
Final Answer
6. Use the same language as the question whenever possible.
7. If Hindi, answer in Hindi. If English, answer in English.
8. Give a shortcut only when a genuine shortcut exists.
9. Keep Verification short and decisive.
10. Final Answer must contain only the correct option and answer.
11. Never use LaTeX, $ or $$.
12. Use Unicode symbols: √ × ÷ ≈ − ≤ ≥ ≠ and superscripts such as ² and ³.
13. Write fractions as 3/5.
14. Put important calculations on separate lines.
15. Do not add extra sections.
16. Do not repeat Final Answer elsewhere.

Return exactly:

Answer

[correct option and concise solution]

Shortcut Trick

[short useful trick]

Verification

[short verification]

Final Answer

[correct option and final answer]
""".strip()


def _build_image_prompt(pro: bool = False) -> str:
    mode = (
        "PRO MODE: Give a more detailed competitive-exam solution, verify every "
        "calculation, and provide the most useful shortcut."
        if pro else
        "NORMAL MODE: Give a concise, accurate and exam-oriented solution."
    )

    return f"""You are an expert competitive-exam question solver.

{mode}

The attached image contains a question, possibly with options.

Read the complete image carefully and solve it accurately.

STRICT RULES:
1. Read the complete question and all visible options.
2. Carefully read mathematical symbols, fractions, powers, roots, signs, tables and diagrams.
3. Use only information actually visible in the image.
4. Do not invent unreadable information.
5. Verify all calculations.
6. Do not rewrite the question or options.
7. Use exactly four sections:
Answer
Shortcut Trick
Verification
Final Answer
8. Use the visible question language whenever possible.
9. Give a shortcut only when a genuine shortcut exists.
10. Final Answer must contain only the correct option and answer.
11. Never use LaTeX, $ or $$.
12. Use Unicode symbols: √ × ÷ ≈ − ≤ ≥ ≠ and superscripts such as ² and ³.
13. Write fractions as 3/5.
14. Do not add extra sections or repeat Final Answer.

Return exactly:

Answer

[correct option and concise solution]

Shortcut Trick

[short useful trick]

Verification

[short verification]

Final Answer

[correct option and final answer]
""".strip()


async def _gemini_vision(user_id: int, image_bytes: bytes, mime_type: str,
                         prompt: str, max_tokens: int) -> str:
    keys = await get_provider_keys(user_id, "gemini")
    if not keys:
        raise RuntimeError("No Gemini API key is configured for image solving.")
    if len(image_bytes) > MAX_IMAGE_SIZE:
        raise RuntimeError("Image is too large.")

    image_b64 = base64.b64encode(image_bytes).decode("ascii")

    urls = (
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent",
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent",
    )

    last_error = None
    for key_info in keys:
        api_key = key_info.get("api_key")
        if not api_key:
            continue

        for url in urls:
            payload = {
                "contents": [{
                    "role": "user",
                    "parts": [
                        {"inline_data": {"mime_type": mime_type, "data": image_b64}},
                        {"text": prompt},
                    ],
                }],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "temperature": 0.2,
                },
            }

            try:
                status, data = await request_json(
                    "POST",
                    url=url,
                    json_body=payload,
                    headers={
                        "x-goog-api-key": api_key,
                        "Content-Type": "application/json",
                    },
                )
                if status != 200:
                    raise RuntimeError(f"Gemini returned HTTP {status}: {str(data)[:500]}")

                candidates = data.get("candidates") or []
                if not candidates:
                    raise RuntimeError("Gemini returned no candidates.")

                parts = (candidates[0].get("content") or {}).get("parts") or []
                result = "\n".join(
                    str(p.get("text")) for p in parts if p.get("text")
                ).strip()

                if result:
                    return result
                raise RuntimeError("Gemini returned an empty solution.")
            except Exception as exc:
                last_error = exc
                logger.warning("Gemini vision failed: %s", exc)

    raise RuntimeError(f"All Gemini vision models failed: {last_error}")


def _convert_math_to_unicode(text: str) -> str:
    if not text:
        return ""

    text = text.replace("$$", "").replace("$", "")

    replacements = {
        r"\times": "×", r"\cdot": "×", r"\div": "÷", r"\approx": "≈",
        r"\pm": "±", r"\leq": "≤", r"\le": "≤", r"\geq": "≥", r"\ge": "≥",
        r"\neq": "≠", r"\ne": "≠", r"\infty": "∞", r"\degree": "°",
        r"\circ": "°", r"\left": "", r"\right": "", r"\,": " ", r"\;": " ",
        r"\!": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    text = re.sub(r"\\sqrt\s*\{([^{}]*)\}", r"√\1", text, flags=re.I)
    text = re.sub(r"\\frac\s*\{([^{}]*)\}\s*\{([^{}]*)\}", r"\1/\2", text, flags=re.I)
    text = re.sub(r"\\[a-zA-Z]+", "", text)
    return text.replace("{", "").replace("}", "")


def _format_result(raw: str) -> str:
    if not raw:
        return "❌ Solution could not be generated."

    text = raw.strip()
    text = re.sub(r"```(?:text|markdown|html)?", "", text, flags=re.I)
    text = text.replace("```", "").strip()
    text = _convert_math_to_unicode(text)
    text = html.escape(text)

    text = re.sub(r"(?im)^\s*Answer\s*:?\s*$", "<b>Answer</b>", text)
    text = re.sub(r"(?im)^\s*Shortcut\s*Trick\s*:?\s*$",
                  "\n\n<b>Shortcut Trick</b>", text)
    text = re.sub(r"(?im)^\s*Verification\s*:?\s*$",
                  "\n\n<b>Verification</b>", text)
    text = re.sub(r"(?im)^\s*Final\s*Answer\s*:?\s*$",
                  "\n\n<b>Final Answer</b>", text)

    return re.sub(r"\n{3,}", "\n\n", text).strip()


async def _send_long_result(ctx, chat_id: int, text: str) -> None:
    remaining = text
    while remaining:
        if len(remaining) <= TELEGRAM_MESSAGE_LIMIT:
            chunk, remaining = remaining, ""
        else:
            split_at = remaining.rfind("\n", 0, TELEGRAM_MESSAGE_LIMIT)
            if split_at < 1000:
                split_at = TELEGRAM_MESSAGE_LIMIT
            chunk, remaining = remaining[:split_at], remaining[split_at:].lstrip()

        await safe_send_message(
            ctx, chat_id, chunk,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )


async def solve_command(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return

    chat = update.effective_chat
    user = update.effective_user
    if not chat or not user:
        return

    chat_id, user_id = chat.id, user.id

    try:
        args = list(ctx.args or [])
        pro = bool(args and args[0].strip().lower() == "pro")
        if pro:
            args = args[1:]

        question = _clean_question(" ".join(args).strip())
        image_info = _get_replied_image(message)

        if image_info:
            file_id, mime_type = image_info
            status = await safe_send_message(
                ctx, chat_id, "📤 <b>Uploading image...</b>",
                parse_mode=ParseMode.HTML,
            )

            telegram_file = await ctx.bot.get_file(file_id)
            image_bytes = await telegram_file.download_as_bytearray()

            if status:
                try:
                    await status.edit_text("⏳ <b>Solving...</b>", parse_mode=ParseMode.HTML)
                except Exception:
                    pass

            raw = await _gemini_vision(
                user_id, bytes(image_bytes), mime_type,
                _build_image_prompt(pro), 3000 if pro else 2200
            )
        else:
            if not question:
                question = _get_replied_text(message) or ""
            question = _clean_question(question)

            if not question:
                await safe_send_message(
                    ctx, chat_id,
                    "🧠 <b>AI Question Solver</b>\n\n"
                    "<code>/solve question</code>\n"
                    "<code>/solve pro question</code>\n\n"
                    "Reply to a Text, Poll or Image and send <code>/solve</code>.",
                    parse_mode=ParseMode.HTML,
                )
                return

            if len(question) > MAX_QUESTION_LENGTH:
                await safe_send_message(ctx, chat_id, "❌ Question is too long.")
                return

            status = await safe_send_message(
                ctx, chat_id, "⏳ <b>Solving...</b>",
                parse_mode=ParseMode.HTML,
            )

            raw = await ai_generate(
                user_id=user_id,
                prompt=_build_text_prompt(question, pro),
                max_tokens=3000 if pro else 2200,
            )

        result = _format_result(raw)

        if status and len(result) <= 4096:
            try:
                await status.edit_text(
                    result,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                return
            except Exception:
                pass

        if status and len(result) > 4096:
            try:
                await status.edit_text(
                    result[:4096],
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                await _send_long_result(ctx, chat_id, result[4096:])
                return
            except Exception:
                pass

        await _send_long_result(ctx, chat_id, result)

    except Exception as exc:
        logger.error("solve_command error: %s", exc, exc_info=True)
        try:
            await safe_send_message(
                ctx, chat_id,
                "❌ <b>Solution could not be generated.</b>\nPlease try again.",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


def register(application: Application) -> None:
    application.add_handler(CommandHandler("solve", solve_command))
