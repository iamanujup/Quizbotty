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

# Database Initialization (यह नया जोड़ा गया है)
async def init_database():
    logger.info("Initializing Database...")
    try:
        from quizbot.database.db import init_db
        await init_db()
        logger.info("Database initialized successfully.")
    except ImportError:
        logger.error("Could not find init_db in quizbot.database.db. Check your database/db.py file.")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")

# Creator Bot
async def _run_creator_bot():
    from quizbot.creator_bot.bot import run_creator_bot
    logger.info("Starting Creator Bot...")
    await run_creator_bot()

# Runner Bot 
async def _run_runner_bot():
    from quizbot.runner_bot.bot import run_creator_bot as run_runner_bot
    logger.info("Starting Runner Bot...")
    await run_runner_bot()

# Resilient Runner
async def _run_resilient(name, runner_func, delay=10):
    while True:
        try:
            await runner_func()
        except Exception as e:
            logger.error(f"{name} failed: {e}; restarting in {delay} seconds")
            await asyncio.sleep(delay)

async def main():
    # 1. सबसे पहले डेटाबेस शुरू करें
    await init_database()

    # 2. फिर बॉट्स शुरू करें
    only = None
    if len(sys.argv) > 2 and sys.argv[1] == "--only":
        only = sys.argv[2]

    if only == "miniapp":
        run_mini_app()
        return

    tasks = []

    if only == "creator":
        tasks.append(asyncio.create_task(_run_resilient("Creator Bot", _run_creator_bot)))
    elif only == "runner":
        tasks.append(asyncio.create_task(_run_resilient("Runner Bot", _run_runner_bot)))
    else:
        tasks.append(asyncio.create_task(_run_resilient("Creator Bot", _run_creator_bot)))
        tasks.append(asyncio.create_task(_run_resilient("Runner Bot", _run_runner_bot)))

    if os.environ.get("MINI_APP_DOMAIN"):
        import threading
        threading.Thread(target=run_mini_app, daemon=True).start()

    if tasks:
        await asyncio.gather(*tasks)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Stopped by user.")
