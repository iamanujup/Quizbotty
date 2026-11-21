import asyncio
import logging
import sys
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

# Logging setup
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("launcher")

# --- 1. Dummy Web Server for Render (तााकि Render इसे Web Service समझे) ---
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"Bot is running!")

def run_dummy_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), DummyHandler)
    logger.info(f"Dummy web server running on port {port}")
    server.serve_forever()

# --- 2. Mini App Server (अगर आप बाद में इस्तेमाल करना चाहें) ---
def run_mini_app():
    try:
        from quizbot.mini_app.server import app
        import uvicorn
        port = int(os.environ.get("MINI_APP_PORT", 8080))
        logger.info(f"Starting Mini App server on 0.0.0.0:{port}")
        uvicorn.run(app, host="0.0.0.0", port=port)
    except Exception as e:
        logger.error(f"Mini App failed: {e}")

# --- 3. Database Initialization ---
async def init_database():
    logger.info("Initializing Database...")
    try:
        from quizbot.database.db import init_db
        await init_db()
        logger.info("Database initialized successfully.")
    except ImportError:
        logger.error("Could not find init_db in quizbot.database.db.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

# --- 4. Creator Bot ---
async def _run_creator_bot():
    from quizbot.creator_bot.bot import run_creator_bot
    logger.info("Starting Creator Bot...")
    await run_creator_bot()

# --- 5. Runner Bot ---
async def _run_runner_bot():
    # आपकी bot.py में run_creator_bot फंक्शन है
    from quizbot.runner_bot.bot import run_creator_bot as run_runner_bot
    logger.info("Starting Runner Bot...")
    await run_runner_bot()

# --- 6. Resilient Runner ---
async def _run_resilient(name, runner_func, delay=10):
    while True:
        try:
            await runner_func()
        except Exception as e:
            logger.error(f"{name} failed: {e}; restarting in {delay} seconds")
            await asyncio.sleep(delay)

async def main():
    # सबसे पहले Render के लिए डमी वेब सर्वर शुरू करें
    threading.Thread(target=run_dummy_web_server, daemon=True).start()

    # अगर Mini App डोमेन सेट है, तो उसे भी शुरू करें
    if os.environ.get("MINI_APP_DOMAIN"):
        threading.Thread(target=run_mini_app, daemon=True).start()

    # डेटाबेस इनिशियलाइज़ करें
    await init_database()

    only = None
    if len(sys.argv) > 2 and sys.argv[1] == "--only":
        only = sys.argv[2]

    tasks = []

    if only == "creator":
        tasks.append(asyncio.create_task(_run_resilient("Creator Bot", _run_creator_bot)))
    elif only == "runner":
        tasks.append(asyncio.create_task(_run_resilient("Runner Bot", _run_runner_bot)))
    else:
        tasks.append(asyncio.create_task(_run_resilient("Creator Bot", _run_creator_bot)))
        tasks.append(asyncio.create_task(_run_resilient("Runner Bot", _run_runner_bot)))

    if tasks:
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
