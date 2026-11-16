
"""
Advance Quiz Bot — Rich Quiz Dispatch
Keeps the original question and options inside Telegram polls.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger(__name__)

SendRawFn = Callable[[str, dict[str, Any]], Awaitable[dict[str, Any]]]
PlainSendFn = Callable[[str], Awaitable[Any]]

_HTML_TAG = re.compile(
    r"<(?:b|i|u|s|em|strong|code|pre|mark|h[1-6]|p|ul|ol|li|table|tr|td|th|"
    r"blockquote|details|summary|figure|figcaption|aside|sup|sub|hr|br|div|span|"
    r"tg-spoiler|tg-math|tg-math-block|tg-slideshow|tg-collage|tg-map|"
    r"img|video|audio)[\s/>]",
    re.IGNORECASE,
)

_MD_PATTERNS = [
    re.compile(r"^#{1,6}\s", re.MULTILINE),
    re.compile(r"\*\*\S[\s\S]*?\S\*\*|\*\*\S\*\*"),
    re.compile(r"(?<!\w)__(?!\s)\S[\s\S]*?\s[\s\S]*?(?<!\s)__(?!\w)"),
    re.compile(r"\*(?!\s)(?:[^*\n]|\\.)+?(?<!\s)\*"),
    re.compile(r"~~.+?~~"),
    re.compile(r"==.+?=="),
    re.compile(r"\|\|.+?\|\|"),
    re.compile(r"^\|.+\|.*\n\|[-:\s|]+\|", re.MULTILINE),
    re.compile(r"!\[.*?\]\([^)]+\)"),
    re.compile(r"\[.+?\]\([^)]+\)"),
    re.compile(r"\$\$[\s\S]+?\$\$"),
    re.compile(r"^```", re.MULTILINE),
    re.compile(r"`[^`\n]+`"),
    re.compile(r"^>[ \t]", re.MULTILINE),
    re.compile(r"^---$", re.MULTILINE),
]

_LATEX_PATTERNS = [
    re.compile(r"\$\$[\s\S]+?\$\$"),
    re.compile(r"(?<!\$)\$(?!\$)[^$\n]*[\\^_{}\[\]][^$\n]*(?<!\$)\$(?!\$)"),
    re.compile(r"\\\([\s\S]+?\\\)"),
    re.compile(r"\\\[[\s\S]+?\\\]"),
    re.compile(
        r"\\(?:frac|sqrt|sum|int|prod|lim|infty|alpha|beta|gamma|delta|"
        r"epsilon|theta|lambda|mu|pi|sigma|omega|Omega|nabla|partial|"
        r"cdot|times|div|pm|mp|leq|geq|neq|approx|equiv|propto|"
        r"vec|hat|bar|dot|ddot|overline|underline|mathbf|mathrm|mathit|"
        r"text|begin|end|matrix|pmatrix|bmatrix|cases|aligned)\b"
    ),
]

_OPTION_LETTERS = "ABCDEFGHIJ"


def _normalise_math_spacing(text: str) -> str:
    dd = re.compile(r"\$\$([\s\S]+?)\$\$")
    result = []
    last_end = 0

    for match in dd.finditer(text):
        start, end = match.start(), match.end()
        content = match.group(1).strip()
        before = text[last_end:start]

        if last_end > 0 and before and not before[0].isspace():
            before = " " + before
        if before and not before[-1].isspace():
            before += " "

        result.append(before)
        result.append("$$" + content + "$$")
        last_end = end

    tail = text[last_end:]
    if result and tail and not tail[0].isspace():
        tail = " " + tail

    result.append(tail)
    return "".join(result)


def _is_rich(text: Optional[str]) -> bool:
    if not text or not text.strip():
        return False

    if _HTML_TAG.search(text):
        return True

    return any(pattern.search(text) for pattern in _LATEX_PATTERNS + _MD_PATTERNS)


def _options_are_rich(options: list[str]) -> bool:
    return any(_is_rich(option) for option in options)


def _detect_mode(text: str) -> str:
    stripped = text.lstrip()
    if stripped.startswith("<") and _HTML_TAG.search(stripped[:200]):
        return "html"
    return "markdown"


async def send_rich_or_fallback(
    send_raw: SendRawFn,
    plain_send: PlainSendFn,
    chat_id: int,
    text: str,
    *,
    thread_id: Optional[int] = None,
    plain_limit: int = 4096,
) -> bool:
    mode = _detect_mode(text)
    params: dict[str, Any] = {
        "chat_id": chat_id,
        "rich_message": {mode: text},
    }

    if thread_id:
        params["message_thread_id"] = thread_id

    try:
        await send_raw("sendRichMessage", params)
        return True
    except Exception as exc:
        logger.debug("Rich message failed: %s", exc)

    other = "html" if mode == "markdown" else "markdown"
    params["rich_message"] = {other: text}

    try:
        await send_raw("sendRichMessage", params)
        return True
    except Exception as exc:
        logger.warning("Rich message fallback failed: %s", exc)

    plain = re.sub(r"</?tg-[^>]+>", "", text)

    try:
        for i in range(0, len(plain), plain_limit):
            await plain_send(plain[i:i + plain_limit])
    except Exception as exc:
        logger.error("Plain message fallback failed: %s", exc)

    return False


@dataclass
class RichDispatchResult:
    poll_question_override: Optional[str] = None
    poll_options_override: Optional[list[str]] = None
    suppress_description: bool = False
    suppress_reply_text: bool = False
    case: int = 0
    rich_sent: bool = False
    original_option_count: int = 0


async def enrich_question_dispatch(
    send_raw: SendRawFn,
    plain_send: PlainSendFn,
    chat_id: int,
    q: dict[str, Any],
    idx: int,
    total: int,
    *,
    thread_id: Optional[int] = None,
) -> RichDispatchResult:
    """
    Do not send a separate question message before the poll.
    Do not replace the real question with a placeholder.
    Do not replace the real options with A/B/C/D.

    The original question and options remain unchanged so the poll
    handler can send them directly to Telegram.
    """

    options = q.get("options") or []

    return RichDispatchResult(
        poll_question_override=None,
        poll_options_override=None,
        suppress_description=False,
        suppress_reply_text=False,
        case=0,
        rich_sent=False,
        original_option_count=len(options),
    )
