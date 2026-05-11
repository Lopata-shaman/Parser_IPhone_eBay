"""
=============================================================
  TELEGRAM BOT + EBAY PARSER  (aiogram 3.x + Playwright)


УСТАНОВКА ЗАВИСИМОСТЕЙ:
    pip install aiogram playwright
    playwright install chromium
"""

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

# ──────────────────────────────────────────────
#  👇  ВСТАВЬТЕ ВАШ ТОКЕН СЮДА
BOT_TOKEN = "bot_token"
# ──────────────────────────────────────────────

from handlers import router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        raise ValueError("❌ Вы не вставили токен бота! Откройте bot.py и замените BOT_TOKEN.")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)

    logger.info("🤖 Бот запущен. Нажмите Ctrl+C для остановки.")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
