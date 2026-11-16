
"""
Advance Quiz Bot — Open Source Project
HTML, JSON and TXT Quiz Import Support
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from ..parsing import filter_words, parse_question_block, strip_source_noise

logger = logging.getLogger(__name__)


def _clean_value(value, remove_words: list[str] | None = None):
    """Normalize imported text while preserving HTML formatting."""
    if value is None:
        return None

    value = str(value)

    if remove_words:
        value = filter_words(value, remove_words)

    return strip_source_noise(value)


def _process_txt(content: str, remove_words: list[str], out_questions: list[dict]) -> int:
    """Parse TXT questions using the existing block parser."""
    ggn_blocks: list[str] = []

    def _replace_ggn(match):
        placeholder = f"GGN_PLACEHOLDER_{len(ggn_blocks)}"
        ggn_blocks.append(match.group(1))
        return f"RT: <ggn>{placeholder}</ggn>"

    protected = re.sub(
        r"<ggn>(.*?)</ggn>",
        _replace_ggn,
        content,
        flags=re.DOTALL,
    )

    blocks = protected.strip().split("\n\n")
    processed = 0

    for block in blocks:
        if not block.strip():
            continue

        lines = block.strip().split("\n")
        has_structured = any(
            ln.strip().startswith(("RT:", "ID:")) for ln in lines
        )

        reply_text = None
        file_id = None
        core_lines = lines

        if has_structured:
            reply_text, file_id, core_lines = None, None, []

            for ln in lines:
                stripped = ln.strip()

                if stripped.startswith("RT:"):
                    rt_content = stripped[3:].strip()
                    ph_match = re.search(
                        r"<ggn>GGN_PLACEHOLDER_(\d+)</ggn>",
                        rt_content,
                    )

                    if ph_match:
                        idx = int(ph_match.group(1))
                        reply_text = (
                            ggn_blocks[idx]
                            if idx < len(ggn_blocks)
                            else rt_content
                        )
                    else:
                        reply_text = rt_content

                    reply_text = _clean_value(reply_text, remove_words)

                elif stripped.startswith("ID:"):
                    file_id = strip_source_noise(stripped[3:].strip())

                else:
                    core_lines.append(ln)

        parsed = parse_question_block("\n".join(core_lines))

        if not parsed or isinstance(parsed["correct_option_id"], list):
            continue

        q_text = _clean_value(parsed["question"], remove_words)
        opts = [
            _clean_value(o, remove_words)
            for o in parsed["options"]
        ]
        exp = _clean_value(parsed.get("explanation"), remove_words)

        if not q_text or len(opts) < 2:
            continue

        out_questions.append({
            "question": q_text,
            "options": opts,
            "correct_option_id": parsed["correct_option_id"],
            "explanation": exp,
            "reply_text": reply_text,
            "file_id": file_id,
        })

        processed += 1

    return processed


def _process_json(
    raw: dict,
    remove_words: list[str],
    out_questions: list[dict],
) -> int:
    """Parse the existing JSON question format."""
    questions = raw.get("questions")

    if not isinstance(questions, list):
        raise ValueError("'questions' should be an array.")

    processed = 0

    for q in questions:
        try:
            if not isinstance(q, dict):
                continue

            if not all(
                k in q
                for k in (
                    "question_text",
                    "options",
                    "correct_option_id",
                )
            ):
                continue

            question_text = _clean_value(
                q["question_text"],
                remove_words,
            )

            options_data = q["options"]

            if not isinstance(options_data, list) or len(options_data) < 2:
                continue

            options = []
            id_to_index = {}

            for opt in options_data:
                if (
                    not isinstance(opt, dict)
                    or "id" not in opt
                    or "text" not in opt
                ):
                    continue

                text = _clean_value(opt["text"], remove_words)

                if not text:
                    continue

                id_to_index[opt["id"]] = len(options)
                options.append(text)

            if len(options) < 2:
                continue

            correct_id = q["correct_option_id"]

            if correct_id not in id_to_index:
                continue

            explanation = _clean_value(
                q.get("explanation"),
                remove_words,
            )

            reply_text = _clean_value(
                q.get("reference_text"),
                remove_words,
            )

            out_questions.append({
                "question": question_text,
                "options": options,
                "correct_option_id": id_to_index[correct_id],
                "explanation": explanation,
                "reply_text": reply_text,
                "file_id": q.get("file_id"),
            })

            processed += 1

        except Exception:
            logger.debug(
                "Skipped malformed question in JSON import",
                exc_info=True,
            )
            continue

    return processed


def _extract_html_questions(content: str) -> list:
    """
    Extract the Qs array from HTML files.

    Supported format:
        const Qs = [
            {
                question: "...",
                options: ["...", "..."],
                correct: 1,
                solution: "..."
            }
        ];
    """

    patterns = [
        r"\b(?:const|let|var)\s+Qs\s*=\s*",
        r"\b(?:const|let|var)\s+questions\s*=\s*",
    ]

    match = None

    for pattern in patterns:
        match = re.search(pattern, content, flags=re.IGNORECASE)

        if match:
            break

    if not match:
        raise ValueError(
            "Could not find test quiz data in HTML. "
            "Expected const Qs = [...]"
        )

    start = match.end()
    decoder = json.JSONDecoder()

    try:
        data, _ = decoder.raw_decode(content[start:].lstrip())
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid quiz data inside HTML: {exc}"
        ) from exc

    if not isinstance(data, list):
        raise ValueError("HTML quiz data must be an array.")

    return data


def _process_html(
    content: str,
    remove_words: list[str],
    out_questions: list[dict],
) -> int:
    """Import questions from HTML quiz files."""
    questions = _extract_html_questions(content)

    processed = 0

    for q in questions:
        try:
            if not isinstance(q, dict):
                continue

            question = q.get("question")
            options_data = q.get("options")
            correct = q.get("correct")

            if not question or not isinstance(options_data, list):
                continue

            if len(options_data) < 2:
                continue

            options = []

            for option in options_data:
                if isinstance(option, dict):
                    option = option.get("text", "")

                if option is None:
                    option = ""

                option = _clean_value(option, remove_words)

                if not option:
                    continue

                options.append(option)

            if len(options) < 2:
                continue

            try:
                correct_index = int(correct)
            except (TypeError, ValueError):
                continue

            # HTML quiz format uses 1-based correct answers.
            # Convert them to the bot's 0-based option index.
            if 1 <= correct_index <= len(options):
                correct_index -= 1
            elif 0 <= correct_index < len(options):
                # Also accept an already zero-based index.
                pass
            else:
                continue

            question = _clean_value(question, remove_words)

            if not question:
                continue

            explanation = _clean_value(
                q.get("solution") or q.get("explanation"),
                remove_words,
            )

            out_questions.append({
                "question": question,
                "options": options,
                "correct_option_id": correct_index,
                "explanation": explanation,
                "reply_text": None,
                "file_id": None,
            })

            processed += 1

        except Exception:
            logger.debug(
                "Skipped malformed question in HTML import",
                exc_info=True,
            )
            continue

    return processed


def process_uploaded_file(
    content: bytes,
    filename: str,
    out_questions: list[dict],
    remove_words: list[str],
) -> tuple[Optional[int], Optional[str]]:
    """
    Process TXT, JSON and HTML quiz files.

    Returns:
        (count_processed, error_message)
    """

    lower = filename.lower()

    try:
        text = content.decode("utf-8-sig")

    except UnicodeDecodeError:
        return None, "❌ File is not valid UTF-8 text."

    try:
        if lower.endswith(".json"):
            data = json.loads(text)

            if not isinstance(data, dict) or "questions" not in data:
                return (
                    None,
                    "❌ Invalid JSON format. "
                    "Expected an object with a 'questions' array.",
                )

            count = _process_json(
                data,
                remove_words,
                out_questions,
            )

        elif lower.endswith(".txt"):
            count = _process_txt(
                text,
                remove_words,
                out_questions,
            )

        elif lower.endswith((".html", ".htm")):
            count = _process_html(
                text,
                remove_words,
                out_questions,
            )

        else:
            return (
                None,
                "❌ Only .txt, .json, .html and .htm files are supported.",
            )

        if count == 0:
            return (
                0,
                "⚠️ No valid questions found in the uploaded file.",
            )

        return count, None

    except json.JSONDecodeError as exc:
        return None, f"❌ Invalid JSON format: {exc}"

    except Exception as exc:
        logger.exception(
            "process_uploaded_file failed for %s",
            filename,
        )

        return None, f"⚠️ Error processing file: {exc}"
