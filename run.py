import asyncio
import logging
import sys
import os

# Logging setup
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    level=logging.INFO
)
logger = logging.getLogger("launcher")

# Mini App Server (FastAPI/Uvicorn)
def run_mini_app():
    try:
        from quizbot.mini_app.server import app
        import uvicorn
        port = int(os.environ.get("PORT", 10000))
        logger.info(f"Starting Mini App server on 0.0.0.0:{port}")
        uvicorn.run(app, host="0.0.0.0", port=port)
    except ImportError as e:
        logger.error(f"Mini App import failed: {e}")
    except Exception as e:
        logger.error(f"Mini App failed: {e}")

# Creator Bot
async def _run_creator_bot():
    try:
        from quizbot.creator_bot.bot import run_creator_bot
        logger.info("Starting Creator Bot (Pyrogram)...")
        await run_creator_bot()
    except ImportError:
        # Fallback for different function names
        from quizbot.creator_bot.bot import start_creator_bot
        logger.info("Starting Creator Bot (Fallback)...")
        await start_creator_bot()

# Runner Bot
async def _run_runner_bot():
    try:
        # यहाँ हमने नाम बदल दिया है ताकि ImportError न आए
        from quizbot.runner_bot.bot import run_runner_bot
        logger.info("Starting Runner Bot...")
        await run_runner_bot()
    except ImportError:
        # अगर नाम बदल गया है तो यह वर्जन ट्राई करेगा
        try:
            from quizbot.runner_bot.bot import start_runner_bot as run_runner_bot
            logger.info("Starting Runner Bot (Fallback)...")
            await run_runner_bot()
        except ImportError:
            # अगर ऊपर वाले दोनों नाम नहीं हैं
            try:
                from quizbot.runner_bot.bot import start_bot as run_runner_bot
                logger.info("Starting Runner Bot (Fallback 2)...")
                await run_runner_bot()
            except ImportError as e:
                logger.error(f"Runner Bot failed to import: {e}. Please check quizbot/runner_bot/bot.py for the correct function name.")
                raise e

# Resilient Runner (इसे हमने FloodWait के लिए थोड़ा बेहतर बना दिया है)
async def _run_resilient(name, runner_func, delay=10):
    while True:
        try:
            await runner_func()
        except Exception as e:
            logger.error(f"{name} failed: {e}; restarting in {delay} seconds")
            await asyncio.sleep(delay)

async def main():
    # चेक करें कि कौन सा बॉट चलाना है (कमांड लाइन आर्ग्युमेंट्स से)
    only = None
    if len(sys.argv) > 2 and sys.argv[1] == "--only":
        only = sys.argv[2]

    # Mini App हमेशा अलग थ्रेड/प्रोसेस में चलता है
    if only == "miniapp":
        run_mini_app()
        return

    tasks = []

    if only == "creator":
        tasks.append(asyncio.create_task(_run_resilient("Creator Bot", _run_creator_bot)))
    elif only == "runner":
        tasks.append(asyncio.create_task(_run_resilient("Runner Bot", _run_runner_bot)))
    else:
        # डिफ़ॉल्ट: दोनों बॉट्स एक साथ चलाएं
        tasks.append(asyncio.create_task(_run_resilient("Creator Bot", _run_creator_bot)))
        tasks.append(asyncio.create_task(_run_resilient("Runner Bot", _run_runner_bot)))

    # अगर MINI_APP_DOMAIN सेट है, तो मिनी-ऐप भी चलाएं
    if os.environ.get("MINI_APP_DOMAIN"):
        import threading
        threading.Thread(target=run_mini_app, daemon=True).start()

    # बॉट्स को चलते रहने दें
    if tasks:
        await asyncio.gather(*tasks)
    else:
        logger.info("No bots started. Use --only creator/runner/miniapp or set MINI_APP_DOMAIN.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
