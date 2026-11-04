"""
Advance Quiz Bot — Open Source Project
This project was originally developed by Gagan (github.com/devgaganin).
Reference: https://t.me/advance_quiz_bot
The codebase has been reviewed and verified with the assistance of Claude AI.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from ..parsing import filter_words, parse_question_block, strip_source_noise

logger = logging.getLogger(__name__)


def _process_txt(content: str, remove_words: list[str], out_questions: list[dict]) -> int:
    """Parse a .txt upload using the same block-parsing engine as pasted
    text, plus the legacy `RT:`/`ID:`/`<ggn>...</ggn>` structured-field
    style for reply_text/file_id metadata."""
    ggn_blocks: list[str] = []

    def _replace_ggn(match) -> str:
        placeholder = f"GGN_PLACEHOLDER_{len(ggn_blocks)}"
        ggn_blocks.append(match.group(1))
        return f"RT: <ggn>{placeholder}</ggn>"

    import re

    protected = re.sub(r"<ggn>(.*?)</ggn>", _replace_ggn, content, flags=re.DOTALL)

    blocks = protected.strip().split("\n\n")
    processed = 0

    for block in blocks:
        if not block.strip():
            continue
        lines = block.strip().split("\n")
        has_structured = any(ln.strip().startswith(("RT:", "ID:")) for ln in lines)

        reply_text: Optional[str] = None
        file_id: Optional[str] = None
        core_lines = lines

        if has_structured:
            reply_text, file_id, core_lines = None, None, []
            for ln in lines:
                stripped = ln.strip()
                if stripped.startswith("RT:"):
                    rt_content = stripped[3:].strip()
                    ph_match = re.search(r"<ggn>GGN_PLACEHOLDER_(\d+)</ggn>", rt_content)
                    if ph_match:
                        idx = int(ph_match.group(1))
                        reply_text = ggn_blocks[idx] if idx < len(ggn_blocks) else rt_content
                    else:
                        reply_text = rt_content
                    if remove_words:
                        reply_text = filter_words(reply_text, remove_words)
                    reply_text = strip_source_noise(reply_text)
                elif stripped.startswith("ID:"):
                    file_id = strip_source_noise(stripped[3:].strip())
                else:
                    core_lines.append(ln)

        parsed = parse_question_block("\n".join(core_lines))
        if not parsed or isinstance(parsed["correct_option_id"], list):
            continue

        q_text = parsed["question"]
        opts = parsed["options"]
        exp = parsed.get("explanation")
        if remove_words:
            q_text = filter_words(q_text, remove_words)
            opts = [filter_words(o, remove_words) for o in opts]
            if exp:
                exp = filter_words(exp, remove_words)
        q_text = strip_source_noise(q_text)
        opts = [strip_source_noise(o) for o in opts]
        if exp:
            exp = strip_source_noise(exp)

        if not q_text or len(opts) < 2:
            continue

        out_questions.append(
            {
                "question": q_text, "options": opts,
                "correct_option_id": parsed["correct_option_id"],
                "explanation": exp, "reply_text": reply_text, "file_id": file_id,
            }
        )
        processed += 1

    return processed


def _process_json(raw: dict, remove_words: list[str], out_questions: list[dict]) -> int:
    """Parse the simple JSON schema:
    `{"questions": [{"question_text", "options": [{"id","text"}],
    "correct_option_id", "explanation"?, "reference_text"?, "file_id"?}]}`
    """
    questions = raw.get("questions")
    if not isinstance(questions, list):
        raise ValueError("'questions' should be an array.")

    processed = 0
    for q in questions:
        try:
            if not isinstance(q, dict):
                continue
            if not all(k in q for k in ("question_text", "options", "correct_option_id")):
                continue
            question_text = q["question_text"]
            if remove_words:
                question_text = filter_words(question_text, remove_words)
            question_text = strip_source_noise(question_text)

            options_data = q["options"]
            if not isinstance(options_data, list) or len(options_data) < 2:
                continue

            options: list[str] = []
            id_to_index: dict = {}
            for opt in options_data:
                if not isinstance(opt, dict) or "id" not in opt or "text" not in opt:
                    continue
                text = opt["text"]
                if remove_words:
                    text = filter_words(text, remove_words)
                text = strip_source_noise(text)
                if not text:
                    continue
                id_to_index[opt["id"]] = len(options)
                options.append(text)
            if len(options) < 2:
                continue

            correct_id = q["correct_option_id"]
            if correct_id not in id_to_index:
                continue
            correct_index = id_to_index[correct_id]

            explanation = q.get("explanation")
            if explanation and remove_words:
                explanation = filter_words(explanation, remove_words)
            if explanation:
                explanation = strip_source_noise(explanation)

            reply_text = q.get("reference_text")
            if reply_text and remove_words:
                reply_text = filter_words(reply_text, remove_words)
            if reply_text:
                reply_text = strip_source_noise(reply_text)

            out_questions.append(
                {
                    "question": question_text, "options": options,
                    "correct_option_id": correct_index, "explanation": explanation,
                    "reply_text": reply_text, "file_id": q.get("file_id"),
                }
            )
            processed += 1
        except Exception:
            logger.debug("Skipped malformed question in JSON import", exc_info=True)
            continue
    return processed



def _extract_js_object(source: str, marker: str) -> dict:
    """Extract a JSON object assigned to a known JS variable, respecting strings."""
    match = re.search(r"\b(?:const|let|var)\s+" + re.escape(marker) + r"\s*=\s*", source)
    if not match:
        raise ValueError(f"Could not find `{marker}` quiz data in HTML.")
    start = match.end()
    while start < len(source) and source[start].isspace():
        start += 1
    if start >= len(source) or source[start] != "{":
        raise ValueError(f"`{marker}` is not a JSON object.")
    depth = 0
    in_string = False
    escaped = False
    for pos in range(start, len(source)):
        ch = source[pos]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(source[start:pos + 1])
    raise ValueError(f"Incomplete `{marker}` data in HTML.")


def _process_html(content: str, remove_words: list[str], out_questions: list[dict]) -> int:
    """Import quiz HTML files that embed a `const test = {...}` data object.

    Supports the supplied Testbook-style export: qMap controls question order,
    content stores localized HTML, and correct maps question IDs to option indexes.
    HTML markup is intentionally retained so image URLs, tables and formatting
    in questions/solutions survive into the Mini App rich renderer.
    """
    data = _extract_js_object(content, "test")
    qmap = data.get("qMap")
    contents = data.get("content")
    correct_map = data.get("correct")
    if not isinstance(qmap, dict) or not isinstance(contents, dict) or not isinstance(correct_map, dict):
        raise ValueError("Unsupported HTML quiz structure: expected qMap, content and correct data.")

    # Prefer Hindi when available; otherwise import the first available language.
    languages = data.get("languages") or []
    preferred = "hn" if any(isinstance(x, dict) and x.get("code") == "hn" for x in languages) else None
    processed = 0
    section_data = data.get("sections") or {}

    def clean_html(value):
        if value is None:
            return ""
        value = str(value)
        # Preserve markup, but apply configured word filters to visible text only
        # would require rewriting HTML nodes; avoid corrupting tags/attributes.
        return value

    for qnum, mapping in sorted(qmap.items(), key=lambda item: int(item[0]) if str(item[0]).isdigit() else 10**9):
        try:
            if not isinstance(mapping, dict):
                continue
            qid = str(mapping.get("id", ""))
            localized = contents.get(qid)
            if not isinstance(localized, dict):
                continue
            lang = preferred if preferred in localized else None
            item = localized.get(lang) if lang else None
            if not isinstance(item, dict) or not item.get("text") or not isinstance(item.get("options"), list) or len(item.get("options", [])) < 2:
                # Some exports contain an empty Hindi translation for a subset
                # of questions; use the first complete language for that item.
                lang = next((code for code, candidate in localized.items()
                             if isinstance(candidate, dict) and candidate.get("text")
                             and isinstance(candidate.get("options"), list)
                             and len(candidate.get("options", [])) >= 2), None)
                item = localized.get(lang) if lang else None
            if not isinstance(item, dict):
                continue
            question = clean_html(item.get("text"))
            options = item.get("options")
            solution = clean_html(item.get("solution"))
            correct_id = correct_map.get(qid)
            if not question or not isinstance(options, list) or len(options) < 2:
                continue
            if not isinstance(correct_id, int) or correct_id < 0 or correct_id >= len(options):
                continue
            options = [clean_html(option) for option in options]
            passage = clean_html(item.get("passage"))
            if passage:
                question = passage + question
            section_key = str(mapping.get("section", ""))
            section = section_data.get(section_key, {}) if isinstance(section_data, dict) else {}
            out_questions.append({
                "question": question,
                "options": options,
                "correct_option_id": correct_id,
                "explanation": solution or None,
                "reply_text": None,
                "file_id": None,
                "section_name": section.get("name") if isinstance(section, dict) else None,
                "source_language": lang,
            })
            processed += 1
        except Exception:
            logger.debug("Skipped malformed question in HTML import", exc_info=True)
            continue
    if processed == 0:
        raise ValueError("No valid questions found. Check that this is a supported quiz HTML export.")
    return processed

def process_uploaded_file(
    content: bytes, filename: str, out_questions: list[dict], remove_words: list[str]
) -> tuple[Optional[int], Optional[str]]:
    """Parse an uploaded .txt, .json or supported .html quiz file (bytes already in
    memory) and append parsed questions to `out_questions` in place.
    Returns (count_processed, error_message).
    """
    lower = filename.lower()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return None, "❌ File is not valid UTF-8 text."

    try:
        if lower.endswith(".html") or lower.endswith(".htm"):
            count = _process_html(text, remove_words, out_questions)
        elif lower.endswith(".json"):
            data = json.loads(text)
            if not isinstance(data, dict) or "questions" not in data:
                return None, "❌ Invalid JSON format. Expected an object with a 'questions' array."
            count = _process_json(data, remove_words, out_questions)
        elif lower.endswith(".txt"):
            count = _process_txt(text, remove_words, out_questions)
        else:
            return None, "❌ Only .txt, .json and supported .html quiz files are supported."
        return count, None
    except json.JSONDecodeError as exc:
        return None, f"❌ Invalid JSON format: {exc}"
    except Exception as exc:
        logger.exception("process_uploaded_file failed for %s", filename)
        return None, f"⚠️ Error processing file: {exc}"
