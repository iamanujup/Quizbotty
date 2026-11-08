import asyncio
import html
import json
import os
from urllib.parse import quote

from telegram import InlineKeyboardButton as Btn
from telegram import InlineKeyboardMarkup as Markup
from telegram import Update
from telegram.constants import ParseMode
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

def _load_env(path=".env"):
    """Chhota .env reader (koi extra library nahi). Format: KEY=value"""
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), path)
    if not os.path.exists(p):
        return
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_load_env()

# ====== SETTINGS ======
BOT_TOKEN = os.environ.get("BOT_TOKEN") or "8645794008:AAF_Ity4wGbBxC21DD83p-NSUhyn2DLX6T0"  # .env me BOT_TOKEN=... likho (ya yaha seedha paste karo)
ADMIN_ID = int(os.environ.get("OWNER_ID") or 8904892914)  # owner ka Telegram user ID (bot me /id bhejke pata karo)
CHANNEL = "@SADHNAAMARG"  # force-join channel (bot ko channel me ADMIN banao)
FREE_TESTS = 5
REFER_BONUS = 10
BOT_LINK = "https://t.me/SADHNAAMARG"  # HTML ke JOIN CHANNEL button ka link
BOT_START_LINK = "https://t.me/MOCKMARGJUBOT"  # bot ka public link
BRAND = "MOCK MARG"  # HTML design me dikhne wala naam
PHOTO_URL = "https://i.ibb.co/JwKwhmrK/premanand.jpg"  # splash photo ("" = sirf emoji)
AUDIO_URL = "https://www.image2url.com/r2/default/audio/1790389409501-6f5e0c57-e05f-4e6f-99b1-6a81a57cbcfc.m4a"  # "" = audio band
MAKE_PDF = True  # HTML ke saath PDF bhi banao (pip install weasyprint)
SECTION_NAMES = []  # jaise ["Reasoning", "GK", "Maths", "Hindi"]; khali = Section 1, 2, ...
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
USERS_FILE = os.path.join(BASE_DIR, "users.json")
# ======================
# Data: [ {"title": coaching, "sections": [ {"title": section, "subs": [
#          {"title": subsection, "files": [{"file_id"/"path": ..., "name": ...}]} ]} ]} ]

ADMIN_ONLY = ("addc", "addsec", "addsub", "addf", "dc", "dsec", "dsub", "rnc", "rnsec", "rnsub")
HTML = ParseMode.HTML
h = html.escape


def make_caption(name):
    """Test file ka caption (sab BOLD, HTML parse mode)."""
    return (
        f"➥🌸 <b>{h(name)}</b>🌸\n\n"
        "<b>@SADHNAAMARG</b>\n"
        "🤖 <a href=\"https://t.me/MOCKMARGJUBOT\">BOT START</a>\n"
        "<b>══━━━━━━━✧❂✧━━━━━━━══</b>\n"
        "<b>share जरूर करें ‼️...</b>"
    )


def _stem_title(name):
    base = os.path.splitext(name or "test")[0]
    for suf in ("_MockMarg_PRINT", "_MockMarg"):
        if base.endswith(suf):
            base = base[: -len(suf)]
    return base


# ---------- Storage ----------
def load():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return []


def save(items):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(items, f, ensure_ascii=False, indent=2)


def load_users():
    if os.path.exists(USERS_FILE):
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=2)


def get_user(users, uid):
    return users.setdefault(
        str(uid),
        {"used": 0, "bonus": 0, "ref_by": None, "credited": False, "invited": 0},
    )


def remaining(rec):
    return FREE_TESTS + rec["bonus"] - rec["used"]


def grid(buttons, cols=2):
    return [buttons[i : i + cols] for i in range(0, len(buttons), cols)]


async def edit(q, text, kb=None):
    try:
        await q.edit_message_text(text, reply_markup=kb, parse_mode=HTML)
    except BadRequest as e:
        if "not modified" not in str(e).lower():
            raise



# ======================================================================
#  MOCK MARG converter  (kisi bhi test HTML ko PET Mock design me badalta hai)
# ======================================================================
import base64
import io
import re
import zlib

DEFAULT_PHOTO = "https://i.ibb.co/JwKwhmrK/premanand.jpg"
DEFAULT_AUDIO = (
    "https://www.image2url.com/r2/default/audio/"
    "1790389409501-6f5e0c57-e05f-4e6f-99b1-6a81a57cbcfc.m4a"
)

# ---------------------------------------------------------------- helpers
def js_str(value):
    """Python string -> safe JS string literal (inside <script>)."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def extract_json(text, start_marker, open_ch, close_ch):
    """Marker ke baad wala balanced JSON (array/object) nikalta hai."""
    i = text.find(start_marker)
    if i < 0:
        return None
    i = text.find(open_ch, i)
    depth, in_str, esc = 0, False, False
    for j in range(i, len(text)):
        c = text[j]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
        else:
            if c == '"':
                in_str = True
            elif c == open_ch:
                depth += 1
            elif c == close_ch:
                depth -= 1
                if depth == 0:
                    return json.loads(text[i : j + 1])
    raise ValueError("JSON poora nahi mila")


_STYLE_TAG = re.compile(r"<style\b[^>]*>.*?</style>", re.S | re.I)
_BAD_CSS = re.compile(
    r"(?:font-family|font-size|margin(?:-top|-bottom|-left|-right)?|line-height)\s*:[^;\"']*;?",
    re.I,
)
_EMPTY_STYLE = re.compile(r'\sstyle\s*=\s*(?:"\s*"|\'\s*\')', re.I)


def clean(fragment):
    """appx HTML se KOKILA font / extra margin hata deta hai taaki PET design ka font lage."""
    if not fragment:
        return ""
    s = _STYLE_TAG.sub("", fragment)

    def fix_style(m):
        return m.group(1) + _BAD_CSS.sub("", m.group(2)) + m.group(3)

    s = re.sub(r'(style\s*=\s*")([^"]*)(")', fix_style, s, flags=re.I)
    s = _EMPTY_STYLE.sub("", s)
    return s.strip()


def img(url):
    return f'<img src="{html.escape(url, quote=True)}" style="max-width:100%">' if url else ""


# ---------------------------------------------------------------- appx -> test
def build_test_from_appx(questions, title, total_seconds, section_names):
    test = {
        "title": title,
        "testTitle": title,
        "questions": len(questions),
        "marks": 0,
        "timer": total_seconds,
        "timeSpent": 0,
        "current": 1,
        "answers": {},
        "correct": {},
        "questionMarks": {},
        "qMap": {},
        "sections": {},
        "currentSection": "all",
        "submitted": False,
        "content": {},
        "languages": [
            {"code": "en", "label": "English", "api_name": "English", "aliases": ["en", "english"]},
            {"code": "hn", "label": "Hindi", "api_name": "Hindi", "aliases": ["hn", "hi", "hindi"]},
        ],
        "currentLanguage": "hn",
    }

    sec_order = []
    for q in questions:
        if q["section_id"] not in sec_order:
            sec_order.append(q["section_id"])
    names = [n.strip() for n in (section_names or []) if n.strip()]
    sec_key = {sid: str(i) for i, sid in enumerate(sec_order)}
    for sid, key in sec_key.items():
        idx = int(key)
        name = names[idx] if idx < len(names) else (
            f"Section {idx + 1}" if len(sec_order) > 1 else "Full Test"
        )
        test["sections"][key] = {"name": name, "start_question": 0, "questions": []}

    total = 0.0
    for n, q in enumerate(questions, start=1):
        qid = str(q["id"])
        key = sec_key[q["section_id"]]
        sec = test["sections"][key]
        if not sec["questions"]:
            sec["start_question"] = n
        sec["questions"].append(n)
        test["qMap"][str(n)] = {"id": qid, "section": key}

        pos = float(q.get("positive_marks") or 0)
        neg = float(q.get("negative_marks") or 0)
        pos = int(pos) if pos == int(pos) else pos
        test["questionMarks"][qid] = {"positive": pos, "negative": neg}
        total += pos

        options = []
        for i in range(1, 11):
            o = clean(q.get(f"option_{i}", "")) or img(q.get(f"option_image_{i}", ""))
            if o:
                options.append(o)
        ans = int(q.get("answer") or 1) - 1
        test["correct"][qid] = max(0, min(ans, max(len(options) - 1, 0)))

        text = clean(q.get("question", ""))
        for k in (1, 2, 3):
            text += img(q.get(f"image_link_{k}", ""))
        solution = clean(q.get("solution_text", ""))
        solution += img(q.get("solution_image_1", "")) + img(q.get("solution_image_2", ""))
        test["content"][qid] = {
            "hn": {
                "text": text,
                "passage": clean(q.get("directive", "")) or clean(q.get("question_heading", "")),
                "options": options,
                "solution": solution,
            }
        }
    test["marks"] = int(total) if total == int(total) else total
    return test



def convert_html(raw, filename="test.html"):
    """Raw HTML text -> (MOCK MARG design wali HTML text, test dict)."""
    m = re.search(r"<title>(.*?)</title>", raw, re.S | re.I)
    title = html.unescape(m.group(1)).strip() if m else os.path.splitext(filename)[0]

    test = extract_json(raw, "const test =", "{", "}")
    if test is None:
        questions = extract_json(raw, "const questions =", "[", "]")
        if questions is None:
            raise ValueError("`const questions` ya `const test` nahi mila - ye HTML format support nahi hai")
        tm = re.search(r"const totalTime\s*=\s*(\d+)\s*\*\s*60", raw)
        seconds = int(tm.group(1)) * 60 if tm else 120 * 60
        test = build_test_from_appx(questions, title, seconds, SECTION_NAMES)
    else:  # PET style HTML: sirf re-brand
        test["title"] = test.get("title") or title
        test["testTitle"] = test["title"]

    page = zlib.decompress(base64.b64decode(_TEMPLATE_B64)).decode("utf-8")
    repl = {
        "{{BRAND_JS}}": js_str(BRAND),
        "{{BOT_LINK_JS}}": js_str(BOT_LINK),
        "{{PHOTO_JS}}": js_str(PHOTO_URL),
        "{{AUDIO_JS}}": js_str(AUDIO_URL),
        "{{TITLE}}": html.escape(test["title"]),
        "{{BRAND}}": html.escape(BRAND),
        "{{BOT_LINK}}": html.escape(BOT_LINK, quote=True),
        "{{PHOTO}}": html.escape(PHOTO_URL, quote=True),
    }
    for k, v in repl.items():
        page = page.replace(k, v)
    page = page.replace("/*__TEST_JSON__*/null", json.dumps(test, ensure_ascii=False).replace("</", "<\\/"))
    return page, test



# ======================================================================
#  PDF maker  (test -> MOCK MARG PDF: cover + questions + answer key + solutions)
# ======================================================================
def _pick(test, qid):
    c = (test.get("content") or {}).get(qid) or {}
    for lang in ("hn", "en"):
        d = c.get(lang) or {}
        if d.get("text") or d.get("options"):
            return d
    return {"text": "", "options": [], "solution": "", "passage": ""}


PDF_CSS = """
@page { size: A4; margin: 15mm 13mm; }
* { box-sizing: border-box; }
body { font-family: 'Noto Sans Devanagari','Mangal','Lohit Devanagari','Nirmala UI',Arial,sans-serif;
       font-size: 10.5pt; line-height: 1.55; color: #3e2723; margin: 0; }
img { max-width: 100%; height: auto; }
p { margin: 0 0 4pt; }
.cover { text-align: center; padding-top: 62mm; page-break-after: always; }
.cover .brand { font-size: 44pt; font-weight: 800; color: #7b241c; letter-spacing: 2pt; }
.cover .line { width: 90mm; height: 3pt; background: #d4a017; margin: 8mm auto; }
.cover .title { font-size: 20pt; font-weight: 700; color: #c0392b; margin: 0 12mm 10mm; }
.cover .stats { font-size: 13pt; color: #5d4037; margin-bottom: 14mm; }
.cover .stats b { color: #7b241c; }
.cover .link { font-size: 13pt; color: #e67e22; font-weight: 700; }
.sec { background: #7b241c; color: #fff; padding: 5pt 10pt; font-weight: 700; font-size: 12pt;
       margin: 10pt 0 8pt; border-radius: 4pt; page-break-after: avoid; }
.q { page-break-inside: avoid; margin: 0 0 9pt; padding-bottom: 6pt; border-bottom: 1px solid #f0e6d3; }
.qn { font-weight: 800; color: #c0392b; }
.passage { background: #fdf6e3; padding: 5pt 8pt; margin-bottom: 4pt; border-left: 3pt solid #d4a017; }
.opt { margin: 2pt 0 2pt 16pt; }
.opt b { color: #7b241c; }
.opt p { display: inline; margin: 0; }
.qline p:first-of-type { display: inline; }
.sol p:first-of-type { display: inline; }
h2 { color: #7b241c; font-size: 16pt; border-bottom: 2pt solid #d4a017; padding-bottom: 3pt; margin: 0 0 8pt; }
.newpage { page-break-before: always; }
table.key { border-collapse: collapse; width: 100%; }
table.key td { border: 1px solid #e6d3a3; padding: 3pt 4pt; text-align: center; font-size: 10pt; }
table.key td.n { background: #fdf6e3; font-weight: 700; color: #7b241c; }
.sol { page-break-inside: avoid; margin: 0 0 8pt; padding-bottom: 5pt; border-bottom: 1px solid #f0e6d3; }
.sol .ans { color: #2e7d32; font-weight: 800; }
.foot { text-align: center; color: #8d6e63; font-size: 9pt; margin-top: 12pt; }
"""


def build_pdf_html(test, auto_print=False):
    e = html.escape
    letters = "ABCDEFGHIJ"
    secs = test.get("sections") or {}
    qmap = test.get("qMap") or {}
    order = sorted(secs, key=lambda k: secs[k].get("start_question", 0))
    marks = test.get("marks", "")
    mins = int(test.get("timer", 0)) // 60
    out = [
        "<!DOCTYPE html><html lang='hi'><head><meta charset='utf-8'>",
        "<link href='https://fonts.googleapis.com/css2?family=Noto+Sans+Devanagari:wght@400;700;800&display=swap' rel='stylesheet'>",
        f"<title>{e(test['title'])}</title><style>{PDF_CSS}</style></head><body>",
        "<div class='cover'>",
        f"<div class='brand'>{e(BRAND)}</div><div class='line'></div>",
        f"<div class='title'>{e(test['title'])}</div>",
        f"<div class='stats'><b>{test.get('questions', 0)}</b> प्रश्न &nbsp;•&nbsp; <b>{e(str(marks))}</b> अंक &nbsp;•&nbsp; <b>{mins}</b> मिनट</div>",
        f"<div class='link'>{e(BOT_LINK)}</div></div>",
    ]
    answers = []  # (n, letter, solution)
    for k in order:
        if len(order) > 1:
            out.append(f"<div class='sec'>{e(secs[k].get('name', ''))}</div>")
        for n in secs[k].get("questions", []):
            qid = (qmap.get(str(n)) or {}).get("id")
            if not qid:
                continue
            c = _pick(test, qid)
            out.append(f"<div class='q'><div class='qline'><span class='qn'>Q{n}.</span> ")
            if c.get("passage"):
                out.append(f"<div class='passage'>{c['passage']}</div>")
            out.append(f"{c.get('text', '')}</div>")
            for i, o in enumerate(c.get("options", [])):
                out.append(f"<div class='opt'><b>({letters[i]})</b> {o}</div>")
            out.append("</div>")
            ci = (test.get("correct") or {}).get(qid, 0)
            answers.append((n, letters[ci] if 0 <= ci < len(letters) else "?", c.get("solution", "")))
    out.append("<div class='newpage'><h2>उत्तर कुंजी (Answer Key)</h2><table class='key'>")
    per_row = 8
    for r in range(0, len(answers), per_row):
        row = answers[r : r + per_row]
        out.append("<tr>" + "".join(f"<td class='n'>{n}</td><td>{a}</td>" for n, a, _ in row)
                   + "<td></td><td></td>" * (per_row - len(row)) + "</tr>")
    out.append("</table></div>")
    if any(sol for _, _, sol in answers):
        out.append("<div class='newpage'><h2>हल (Solutions)</h2>")
        for n, a, sol in answers:
            if sol:
                out.append(f"<div class='sol'><span class='qn'>Q{n}.</span> <span class='ans'>उत्तर: ({a})</span>{sol}</div>")
        out.append("</div>")
    out.append(f"<div class='foot'>{e(BRAND)} • {e(BOT_LINK)}</div>")
    if auto_print:  # browser me khulte hi Print dialog -> "Save as PDF"
        out.append("<script>window.onload=function(){setTimeout(function(){window.print()},1500)}</script>")
    out.append("</body></html>")
    return "".join(out)


class NoPdfEngine(Exception):
    pass


def html_to_pdf(page_html):
    """WeasyPrint (pip install weasyprint) ya Playwright/Chromium. Dono na ho (jaise Pydroid) to NoPdfEngine."""
    try:
        from weasyprint import HTML as WeasyHTML

        return WeasyHTML(string=page_html).write_pdf()
    except (ImportError, OSError):
        pass
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page()
            page.set_content(page_html, wait_until="load", timeout=90000)
            pdf = page.pdf(format="A4", print_background=True)
            browser.close()
            return pdf
    except Exception as e:
        raise NoPdfEngine(str(e)) from e


def test_to_pdf(test):
    return html_to_pdf(build_pdf_html(test))


async def make_test_file(context, chat_id, doc):
    """Uploaded HTML -> MOCK MARG HTML (+ PDF). (files_list, note) lautata hai."""
    tg_file = await doc.get_file()
    raw = bytes(await tg_file.download_as_bytearray()).decode("utf-8", errors="replace")
    stem = os.path.splitext(doc.file_name or "test")[0]
    try:
        page, test = await asyncio.to_thread(convert_html, raw, doc.file_name or "test.html")
    except Exception as e:  # convert nahi hua -> original save
        return (
            [{"file_id": doc.file_id, "name": doc.file_name}],
            f"⚠️ Convert nahi hua ({h(str(e))[:150]}). Original file save ki.",
        )
    name = f"{stem}_MockMarg.html"
    sent = await context.bot.send_document(
        chat_id,
        page.encode("utf-8"),
        filename=name,
        caption=make_caption(test["title"]),
        parse_mode=HTML,
    )
    files = [{"file_id": sent.document.file_id, "name": name, "title": test["title"]}]
    note = f"🎨 {BRAND} HTML ready ({test['questions']} Q)."
    if MAKE_PDF:
        try:
            pdf = await asyncio.to_thread(test_to_pdf, test)
            pname = f"{stem}_MockMarg.pdf"
            psent = await context.bot.send_document(
                chat_id, pdf, filename=pname, caption=make_caption(test["title"]), parse_mode=HTML
            )
            files.append({"file_id": psent.document.file_id, "name": pname, "title": test["title"]})
            note += "\n📕 PDF bhi ban gayi."
        except Exception:
            # Is device par PDF engine nahi (Pydroid) -> print-ready HTML bhejo
            ph = build_pdf_html(test, auto_print=True)
            await context.bot.send_document(
                chat_id,
                ph.encode("utf-8"),
                filename=f"{stem}_MockMarg_PRINT.html",
                caption="🖨 PDF ke liye: is file ko Chrome me kholo → Print → Save as PDF. "
                "Phir wo PDF yaha bhej do, subsection me add ho jayegi.",
            )
            note += "\n🖨 PDF yaha auto nahi bani — Print wali HTML bhej di (Chrome → Save as PDF)."
    return files, note


# ======================================================================
#  Template (PET Mock design, compressed)
# ======================================================================
_TEMPLATE_B64 = (
    "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"
    "H6PSXA=="
)

# ---------- Channel + referral ----------
async def is_member(bot, uid):
    try:
        m = await bot.get_chat_member(CHANNEL, uid)
        return m.status in ("member", "administrator", "creator", "restricted")
    except Exception as e:
        print("Channel check fail (bot channel me admin hai?):", e)
        return False


async def credit_referral(context, uid):
    users = load_users()
    rec = users.get(str(uid))
    if not rec or not rec.get("ref_by") or rec.get("credited"):
        return
    rec["credited"] = True
    ref = users.get(str(rec["ref_by"]))
    if ref:
        ref["bonus"] += REFER_BONUS
        ref["invited"] += 1
    save_users(users)
    if ref:
        try:
            await context.bot.send_message(
                rec["ref_by"],
                f"🎉 <b>Tumhare refer se ek dost ne join kiya!</b>\n+{REFER_BONUS} tests mil gaye.",
                parse_mode=HTML,
            )
        except Exception:
            pass


async def gate(context, uid):
    if uid == ADMIN_ID:
        return True
    if await is_member(context.bot, uid):
        await credit_referral(context, uid)
        return True
    return False


def register(uid, args):
    users = load_users()
    is_new = str(uid) not in users
    rec = get_user(users, uid)
    if is_new and args and args[0].startswith("ref_"):
        try:
            ref = int(args[0][4:])
        except ValueError:
            ref = None
        if ref and ref != uid and str(ref) in users:
            rec["ref_by"] = ref
    save_users(users)


# ---------- Screens ----------
def join_screen():
    text = (
        "🔒 <b>Channel join karna zaroori hai</b>\n\n"
        f"Bot use karne ke liye pehle {h(CHANNEL)} join karo, phir "
        "<b>“Maine join kar liya”</b> dabao."
    )
    kb = Markup(
        [
            [Btn("📢 Channel join karo", url=f"https://t.me/{CHANNEL.lstrip('@')}")],
            [Btn("✅ Maine join kar liya", callback_data="chk")],
        ]
    )
    return text, kb


def home_screen(uid, welcome_name=None):
    admin = uid == ADMIN_ID
    items = load()
    rows = [[Btn(f"🏫 {c['title']}", callback_data=f"c:{i}")] for i, c in enumerate(items)]
    if admin:
        rows.append([Btn("➕ Coaching add karo", callback_data="addc")])
    else:
        rows.append([Btn(f"🎁 Refer karo (+{REFER_BONUS} tests)", callback_data="ref")])
    text = f"👋 <b>Namaste {h(welcome_name)}!</b>\n\n" if welcome_name else ""
    text += "🏫 <b>Coaching chuno</b> 👇" if items else "Abhi koi coaching available nahi hai."
    if admin:
        text += "\n\n👑 <i>Owner mode: /stats · /broadcast · /help</i>"
    else:
        rem = remaining(get_user(load_users(), uid))
        text += f"\n\n🎯 Bache hue tests: <b>{max(rem, 0)}</b>"
    return text, Markup(rows)


def ref_screen(uid, bot_username, limit_reached=False):
    rec = get_user(load_users(), uid)
    link = f"https://t.me/{bot_username}?start=ref_{uid}"
    text = "⚠️ <b>Tumhare free tests khatam ho gaye.</b>\n\n" if limit_reached else ""
    text += (
        f"🎁 <b>Har 1 refer par {REFER_BONUS} naye tests!</b>\n\n"
        f"🔗 Tumhara refer link (tap karke copy karo):\n<code>{link}</code>\n\n"
        f"👥 Ab tak refer: <b>{rec['invited']}</b>\n"
        f"🎯 Bache hue tests: <b>{max(remaining(rec), 0)}</b>\n\n"
        "<i>Refer tab count hota hai jab dost bot start karke channel join kar le.</i>"
    )
    share = f"https://t.me/share/url?url={quote(link)}&text={quote('Ye bot try karo 👇')}"
    kb = Markup(
        [
            [Btn("📤 Dost ko bhejo", url=share)],
            [Btn("⬅️ Back", callback_data="home")],
        ]
    )
    return text, kb


def coaching_screen(i, admin):
    c = load()[i]
    rows = [[Btn(f"📚 {s['title']}", callback_data=f"s:{i}:{j}")] for j, s in enumerate(c["sections"])]
    if admin:
        rows.append([Btn("➕ Section add karo", callback_data=f"addsec:{i}")])
        rows.append(
            [
                Btn("✏️ Naam badlo", callback_data=f"rnc:{i}"),
                Btn("🗑 Delete", callback_data=f"dc:{i}"),
            ]
        )
    rows.append([Btn("⬅️ Back", callback_data="home")])
    text = f"🏫 <b>{h(c['title'])}</b>\n\n"
    text += "📚 Section chuno 👇" if c["sections"] else "Abhi koi section nahi hai."
    return text, Markup(rows)


def section_screen(i, j, admin):
    c = load()[i]
    s = c["sections"][j]
    rows = grid([Btn(f"📂 {u['title']}", callback_data=f"u:{i}:{j}:{k}") for k, u in enumerate(s["subs"])])
    if admin:
        rows.append([Btn("➕ Subsection add karo", callback_data=f"addsub:{i}:{j}")])
        rows.append(
            [
                Btn("✏️ Naam badlo", callback_data=f"rnsec:{i}:{j}"),
                Btn("🗑 Delete", callback_data=f"dsec:{i}:{j}"),
            ]
        )
    rows.append([Btn("⬅️ Back", callback_data=f"c:{i}")])
    text = f"🏫 {h(c['title'])} › 📚 <b>{h(s['title'])}</b>\n\n"
    text += "📂 Subsection chuno 👇" if s["subs"] else "Abhi koi subsection nahi hai."
    return text, Markup(rows)


def sub_screen(i, j, k, admin, extra=""):
    c = load()[i]
    s = c["sections"][j]
    u = s["subs"][k]
    rows = []
    if admin:
        rows.append([Btn("➕ HTML file daalo", callback_data=f"addf:{i}:{j}:{k}")])
        rows.append(
            [
                Btn("✏️ Naam badlo", callback_data=f"rnsub:{i}:{j}:{k}"),
                Btn("🗑 Delete", callback_data=f"dsub:{i}:{j}:{k}"),
            ]
        )
    rows.append([Btn("⬅️ Back", callback_data=f"s:{i}:{j}")])
    n = len(u["files"])
    text = f"🏫 {h(c['title'])} › 📚 {h(s['title'])} › 📂 <b>{h(u['title'])}</b>\n\n"
    text += f"📎 {n} HTML file" if n else "Abhi koi file nahi hai."
    return text + extra, Markup(rows)


# ---------- Commands ----------
async def show_home(update: Update, context: ContextTypes.DEFAULT_TYPE, welcome=False):
    user = update.effective_user
    if not await gate(context, user.id):
        text, kb = join_screen()
    else:
        text, kb = home_screen(user.id, user.first_name if welcome else None)
    await update.message.reply_text(text, reply_markup=kb, parse_mode=HTML)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    register(update.effective_user.id, context.args)
    await show_home(update, context, welcome=True)


async def my_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"🆔 Tumhari Telegram ID: <code>{update.effective_user.id}</code>", parse_mode=HTML)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("pending", None)
    await show_home(update, context)


async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    pending = context.user_data.pop("pending", None)
    if pending and pending[0] == "f":
        i, j, k = pending[1:]
        text, kb = sub_screen(i, j, k, True)
        await update.message.reply_text("✅ Upload poora.\n\n" + text, reply_markup=kb, parse_mode=HTML)
    else:
        await show_home(update, context)


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id == ADMIN_ID:
        text = (
            "👑 <b>Owner commands</b>\n\n"
            "/start – home menu\n"
            "/id – apni Telegram ID dekho\n"
            "/stats – users aur usage ka hisaab\n"
            "/broadcast <i>message</i> – sabko message bhejo\n"
            "/done – multiple file upload poora karo\n"
            "📎 Koi bhi test .html seedha bhejo → MOCK MARG HTML + PDF banke wapas aayegi\n"
            "/cancel – kuch bhi beech me rokna\n\n"
            "Coaching → Section → Subsection → HTML file, sab buttons se add hota hai."
        )
    else:
        text = (
            "ℹ️ <b>Kaise use karein</b>\n\n"
            "/start dabao → Coaching → Section → Subsection chuno, test file mil jayegi.\n"
            f"Har user ko {FREE_TESTS} free tests milte hain. Aur tests ke liye 🎁 Refer karo — "
            f"1 refer par {REFER_BONUS} tests."
        )
    await update.message.reply_text(text, parse_mode=HTML)


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    users = load_users()
    items = load()
    secs = sum(len(c["sections"]) for c in items)
    subs = sum(len(s["subs"]) for c in items for s in c["sections"])
    files = sum(len(u["files"]) for c in items for s in c["sections"] for u in s["subs"])
    opened = sum(u["used"] for u in users.values())
    refs = sum(u["invited"] for u in users.values())
    text = (
        "📊 <b>Bot stats</b>\n\n"
        f"👥 Total users: <b>{len(users)}</b>\n"
        f"📖 Tests khole gaye: <b>{opened}</b>\n"
        f"🎁 Successful refer: <b>{refs}</b>\n\n"
        f"🏫 Coaching: {len(items)} · 📚 Sections: {secs}\n"
        f"📂 Subsections: {subs} · 📎 Files: {files}"
    )
    await update.message.reply_text(text, parse_mode=HTML)


async def broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    msg = update.message.text.partition(" ")[2].strip()
    if not msg:
        await update.message.reply_text("Format: /broadcast Aapka message yahan")
        return
    users = load_users()
    ok = fail = 0
    await update.message.reply_text(f"📣 {len(users)} users ko bhej raha hoon…")
    for uid in users:
        try:
            await context.bot.send_message(int(uid), msg)
            ok += 1
        except Exception:
            fail += 1
        await asyncio.sleep(0.05)
    await update.message.reply_text(f"✅ Bhej diya: {ok}\n❌ Fail (block/left): {fail}")


# ---------- Buttons ----------
async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    uid = q.from_user.id
    admin = uid == ADMIN_ID
    cmd, *rest = q.data.split(":")
    n = [int(x) for x in rest]

    if not admin and not await gate(context, uid):
        if cmd == "chk":
            await q.answer("❌ Abhi tak channel join nahi kiya.", show_alert=True)
        else:
            await q.answer()
            text, kb = join_screen()
            await edit(q, text, kb)
        return

    await q.answer()
    if cmd in ADMIN_ONLY and not admin:
        return

    items = load()
    try:
        if cmd in ("home", "chk"):
            text, kb = home_screen(uid)
            await edit(q, text, kb)

        elif cmd == "ref":
            text, kb = ref_screen(uid, context.bot.username)
            await edit(q, text, kb)

        elif cmd == "c":
            text, kb = coaching_screen(n[0], admin)
            await edit(q, text, kb)

        elif cmd == "s":
            text, kb = section_screen(n[0], n[1], admin)
            await edit(q, text, kb)

        elif cmd == "u":
            i, j, k = n
            sub = items[i]["sections"][j]["subs"][k]
            extra = ""
            if not admin and sub["files"]:
                users = load_users()
                rec = get_user(users, uid)
                if remaining(rec) <= 0:
                    text, kb = ref_screen(uid, context.bot.username, limit_reached=True)
                    await edit(q, text, kb)
                    return
                rec["used"] += 1
                save_users(users)
                extra = f"\n\n🎯 Bache hue tests: <b>{max(remaining(rec), 0)}</b>"
            text, kb = sub_screen(i, j, k, admin, extra)
            await edit(q, text, kb)
            for f in sub["files"]:
                caption = make_caption(f.get("title") or _stem_title(f.get("name")))
                if "file_id" in f:
                    await context.bot.send_document(
                        q.message.chat_id, f["file_id"], caption=caption, parse_mode=HTML
                    )
                elif os.path.exists(f.get("path", "")):
                    with open(f["path"], "rb") as fh:
                        await context.bot.send_document(
                            q.message.chat_id, fh, filename=f["name"], caption=caption, parse_mode=HTML
                        )

        elif cmd == "addc":
            context.user_data["pending"] = ("c",)
            await edit(q, "✍️ <b>Coaching ka naam bhejo</b>\n<i>Ek saath kai: har line me ek naam. (cancel: /cancel)</i>")

        elif cmd == "addsec":
            context.user_data["pending"] = ("sec", n[0])
            await edit(q, "✍️ <b>Section ka naam bhejo</b>\n<i>Ek saath kai: har line me ek naam. (cancel: /cancel)</i>")

        elif cmd == "addsub":
            context.user_data["pending"] = ("sub", n[0], n[1])
            await edit(q, "✍️ <b>Subsection ka naam bhejo</b>\n<i>Ek saath kai: har line me ek naam. (cancel: /cancel)</i>")

        elif cmd == "addf":
            context.user_data["pending"] = ("f", n[0], n[1], n[2])
            await edit(
                q,
                "📎 <b>Ab .html (ya .pdf) file(s) bhejo</b>\n<i>HTML automatically MOCK MARG design me convert hogi (+ PDF).</i>\nEk saath kai files bhej sakte ho.\n"
                "<i>Khatam hone par /done dabao (cancel: /cancel)</i>",
            )

        elif cmd == "rnc":
            context.user_data["pending"] = ("rn", "c", n[0])
            await edit(q, "✏️ <b>Naya naam bhejo</b>\n<i>(cancel: /cancel)</i>")

        elif cmd == "rnsec":
            context.user_data["pending"] = ("rn", "sec", n[0], n[1])
            await edit(q, "✏️ <b>Naya naam bhejo</b>\n<i>(cancel: /cancel)</i>")

        elif cmd == "rnsub":
            context.user_data["pending"] = ("rn", "sub", n[0], n[1], n[2])
            await edit(q, "✏️ <b>Naya naam bhejo</b>\n<i>(cancel: /cancel)</i>")

        elif cmd == "dc":
            items.pop(n[0])
            save(items)
            text, kb = home_screen(uid)
            await edit(q, "🗑 Coaching hata di.\n\n" + text, kb)

        elif cmd == "dsec":
            i, j = n
            items[i]["sections"].pop(j)
            save(items)
            text, kb = coaching_screen(i, admin)
            await edit(q, "🗑 Section hata diya.\n\n" + text, kb)

        elif cmd == "dsub":
            i, j, k = n
            items[i]["sections"][j]["subs"].pop(k)
            save(items)
            text, kb = section_screen(i, j, admin)
            await edit(q, "🗑 Subsection hata diya.\n\n" + text, kb)

    except (IndexError, KeyError):
        text, kb = home_screen(uid)
        await edit(q, "Ye item ab available nahi hai.\n\n" + text, kb)


# ---------- Admin text / file input ----------
async def on_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    pending = context.user_data.get("pending")
    msg = update.message
    if not pending:
        d = msg.document
        if d and (d.file_name or "").lower().endswith((".html", ".htm")):
            _, note = await make_test_file(context, msg.chat_id, d)
            await msg.reply_text(note, parse_mode=HTML)
        return

    kind = pending[0]
    items = load()

    if kind in ("c", "sec", "sub", "rn"):
        if not msg.text:
            await msg.reply_text("Naam text me bhejo.")
            return
        names = [x.strip() for x in msg.text.splitlines() if x.strip()]
        name = names[0]
        try:
            if kind == "c":
                for nm in names:
                    items.append({"title": nm, "sections": []})
                i = len(items) - 1
                screen = lambda: coaching_screen(i, True)
            elif kind == "sec":
                i = pending[1]
                for nm in names:
                    items[i]["sections"].append({"title": nm, "subs": []})
                j = len(items[i]["sections"]) - 1
                screen = lambda: section_screen(i, j, True)
            elif kind == "sub":
                i, j = pending[1], pending[2]
                for nm in names:
                    items[i]["sections"][j]["subs"].append({"title": nm, "files": []})
                screen = lambda: section_screen(i, j, True)
            else:  # rename
                level = pending[1]
                if level == "c":
                    i = pending[2]
                    items[i]["title"] = name
                    screen = lambda: coaching_screen(i, True)
                elif level == "sec":
                    i, j = pending[2], pending[3]
                    items[i]["sections"][j]["title"] = name
                    screen = lambda: section_screen(i, j, True)
                else:
                    i, j, k = pending[2], pending[3], pending[4]
                    items[i]["sections"][j]["subs"][k]["title"] = name
                    screen = lambda: sub_screen(i, j, k, True)
        except (IndexError, KeyError):
            context.user_data.pop("pending", None)
            await msg.reply_text("Ye item ab available nahi hai. /start karo.")
            return
        save(items)
        context.user_data.pop("pending")
        text, kb = screen()
        await msg.reply_text("✅ Ho gaya.\n\n" + text, reply_markup=kb, parse_mode=HTML)

    elif kind == "f":
        doc = msg.document
        fname = (doc.file_name or "").lower() if doc else ""
        if not doc or not fname.endswith((".html", ".htm", ".pdf")):
            await msg.reply_text("Sirf .html ya .pdf file bhejo (khatam karne ke liye /done).")
            return
        i, j, k = pending[1], pending[2], pending[3]
        try:
            files = items[i]["sections"][j]["subs"][k]["files"]
        except (IndexError, KeyError):
            context.user_data.pop("pending", None)
            await msg.reply_text("Ye item ab available nahi hai. /start karo.")
            return
        if fname.endswith(".pdf"):
            new_files, note = [{"file_id": doc.file_id, "name": doc.file_name}], "📕 PDF as-is save ki."
        else:
            new_files, note = await make_test_file(context, msg.chat_id, doc)
        files.extend(new_files)
        save(items)
        await msg.reply_text(
            f"✅ <b>{h(new_files[0]['name'])}</b> add ho gayi (total {len(files)} files).\n{note}\n"
            "Aur bhejo ya /done dabao.",
            parse_mode=HTML,
        )


def main():
    if not BOT_TOKEN or BOT_TOKEN.startswith("PASTE_"):
        raise SystemExit("BOT_TOKEN nahi mila. .env file me BOT_TOKEN=apna_token likho (BotFather se milta hai).")
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("cancel", cancel))
    app.add_handler(CommandHandler("id", my_id))
    app.add_handler(CommandHandler("done", done))
    app.add_handler(CommandHandler("stats", stats))
    app.add_handler(CommandHandler("broadcast", broadcast))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.Document.ALL | (filters.TEXT & ~filters.COMMAND), on_message))
    print("Bot chal raha hai…")
    app.run_polling()


if __name__ == "__main__":
    main()
