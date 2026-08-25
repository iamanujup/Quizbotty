"""
Advance Quiz Bot — Open Source Project
Reference: https://t.me/advance_quiz_bot
File: quiz_uploader.py
Description: Handles .txt and .json document uploads to generate Telegram Polls.
"""

from __future__ import annotations

import os
import json
import re
from typing import Optional
from pyrogram import Client, filters

# ==============================================================================
# PARSING LOGIC (Helper Functions)
# ==============================================================================

def _is_emoji(char: str) -> bool:
    if char == "✅":
        return False
    cp = ord(char)
    if 0x1F300 <= cp <= 0x1FAFF: return True
    if 0x2600 <= cp <= 0x26FF: return True
    if 0x2700 <= cp <= 0x27BF: return True
    if 0xFE00 <= cp <= 0xFE0F: return True
    if 0x1F1E0 <= cp <= 0x1F1FF: return True
    if 0x231A <= cp <= 0x231B: return True
    if 0x23E9 <= cp <= 0x23F3: return True
    if 0x25AA <= cp <= 0x25FE: return True
    if 0x2614 <= cp <= 0x2615: return True
    if 0x2648 <= cp <= 0x2653: return True
    return False

def _line_is_emoji_separator(line: str) -> bool:
    s = line.strip()
    if not s:
        return False
    for ch in s:
        if ch in ("️", "‍", "︎"):
            continue
        if not _is_emoji(ch):
            return False
    return True

def clean_markdown(text: str) -> str:
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)
    text = re.sub(r"\*(.+?)\*", r"\1", text)
    text = re.sub(r"__(.+?)__", r"\1", text)
    text = re.sub(r"`(.+?)`", r"\1", text)
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)
    return text

_TABLE_LINE_RE = re.compile(r"^\|.*\|$")

def _pad_table_blocks(text: str) -> str:
    if "|" not in text:
        return text
    lines = text.split("\n")
    segments: list[tuple[str, bool]] = []
    i, n = 0, len(lines)
    while i < n:
        if _TABLE_LINE_RE.match(lines[i].strip()):
            block = []
            while i < n and _TABLE_LINE_RE.match(lines[i].strip()):
                block.append(lines[i])
                i += 1
            segments.append(("\n".join(block), True))
        else:
            segments.append((lines[i], False))
            i += 1
    if not segments:
        return text
    out = segments[0][0]
    for k in range(1, len(segments)):
        prev_is_table = segments[k - 1][1]
        cur_is_table = segments[k][1]
        sep = "\n\n" if (prev_is_table or cur_is_table) else "\n"
        out += sep + segments[k][0]
    if segments[-1][1]:
        out += "\n\n"
    return out

_ABCD_RE = re.compile(r"^[A-Da-d]\)")

def parse_question_block(blk: str) -> Optional[dict]:
    blk = clean_markdown(blk)
    all_lines = blk.split("\n")
    if not any(ln.strip() for ln in all_lines):
        return None

    exp = None
    filtered = []
    for ln in all_lines:
        if ln.strip().startswith("Ex:"):
            exp = ln.strip()[3:].strip()
        else:
            filtered.append(ln)
    all_lines = filtered

    non_blank_idx = [i for i, ln in enumerate(all_lines) if ln.strip()]
    if not non_blank_idx:
        return None

    sep_line_idx = None
    for i in non_blank_idx:
        if _line_is_emoji_separator(all_lines[i]):
            sep_line_idx = i
            break

    abcd_line_idx = None
    for i in non_blank_idx:
        if _ABCD_RE.match(all_lines[i].strip()):
            abcd_line_idx = i
            break

    first_nonblank = non_blank_idx[0]
    if sep_line_idx is not None:
        q_lines = all_lines[:sep_line_idx]
        opt_lines = all_lines[sep_line_idx + 1:]
    elif abcd_line_idx is not None and abcd_line_idx > first_nonblank:
        q_lines = all_lines[:abcd_line_idx]
        opt_lines = all_lines[abcd_line_idx:]
    else:
        q_lines = all_lines[: first_nonblank + 1]
        opt_lines = all_lines[first_nonblank + 1:]

    while q_lines and not q_lines[0].strip():
        q_lines = q_lines[1:]
    while q_lines and not q_lines[-1].strip():
        q_lines = q_lines[:-1]
    question = _pad_table_blocks("\n".join(q_lines))

    opts: list[str] = []
    coids: list[int] = []
    for ln in opt_lines:
        if not ln.strip():
            continue
        ln = ln.strip()
        ln = re.sub(r"^[A-Da-d]\)\s*", "", ln)
        if "✅" in ln:
            coids.append(len(opts))
            ln = ln.replace("✅", "").strip()
        opts.append(ln)

    if not question or len(opts) < 2 or not coids:
        return None

    coid = coids[0] if len(coids) == 1 else coids
    return {
        "question": question,
        "options": opts,
        "correct_option_id": coid,
        "explanation": exp,
    }


# ==============================================================================
# PYROGRAM HANDLER
# ==============================================================================

@Client.on_message(filters.document & filters.private)
async def handle_quiz_file(client, message):
    file_name = message.document.file_name.lower()
    
    # 1. Extension Check
    if not (file_name.endswith('.txt') or file_name.endswith('.json')):
        await message.reply_text("⚠️ Only .txt or .json files are supported for quiz questions.")
        return
    
    status_msg = await message.reply_text("File download aur process ho rahi hai... ⏳")
    
    try:
        file_path = await message.download()
        polls_data = []
        
        # 2. JSON File Parsing
        if file_name.endswith('.json'):
            with open(file_path, "r", encoding="utf-8") as f:
                raw_data = json.load(f)
                if isinstance(raw_data, list):
                    for item in raw_data:
                        if "question" in item and "options" in item:
                            polls_data.append(item)
                            
        # 3. TXT File Parsing
        elif file_name.endswith('.txt'):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            
            blocks = content.split('\n\n')
            for block in blocks:
                if block.strip():
                    parsed_q = parse_question_block(block)
                    if parsed_q:
                        polls_data.append(parsed_q)
        
        if not polls_data:
            await status_msg.edit_text("❌ Is file mein koi valid quiz data nahi mila ya format galat hai.")
            os.remove(file_path)
            return
            
        await status_msg.edit_text(f"✅ Total **{len(polls_data)}** questions mile hain. Polls bhejna shuru kar raha hoon...")
        
        # 4. Send Polls
        sent_count = 0
        for poll_dict in polls_data:
            correct_id = poll_dict.get("correct_option_id", 0)
            
            # Telegram quiz type ek hi correct answer support karta hai (integer)
            if isinstance(correct_id, list):
                correct_id = correct_id[0] 

            kwargs = {
                "question": poll_dict["question"][:300],  # Telegram limit 300 chars
                "options": [opt[:100] for opt in poll_dict["options"]], # Option limit 100 chars
                "type": "quiz",
                "correct_option_id": correct_id,
                "is_anonymous": False
            }
            if "explanation" in poll_dict and poll_dict["explanation"]:
                kwargs["explanation"] = poll_dict["explanation"][:200] # Explanation limit 200 chars
                
            await client.send_poll(chat_id=message.chat.id, **kwargs)
            sent_count += 1
            
        os.remove(file_path)
        await message.reply_text(f"🎉 Done! **{sent_count}** polls successfully create ho gaye hain.")
        
    except Exception as e:
        await message.reply_text(f"Ek error aayi: {e}")
        if os.path.exists(file_path):
            os.remove(file_path)
