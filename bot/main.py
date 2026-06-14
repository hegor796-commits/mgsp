import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.database import ExcelDatabase
from bot.handlers.auth import AuthMiddleware
from bot.handlers import invoice, search, reports, admin

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Global database instance (used by handlers via import)
db = ExcelDatabase(settings.EXCEL_DB_PATH)


async def main():
    logger.info("Инициализация базы данных...")
    db.init_db()

    bot = Bot(token=settings.BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Store db in bot context for handlers
    bot["db"] = db

    # Register middleware
    dp.update.middleware(AuthMiddleware(db))

    # Include routers
    dp.include_router(invoice.router)
    dp.include_router(search.router)
    dp.include_router(reports.router)
    dp.include_router(admin.router)

    logger.info("Бот запущен. Начинаю polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
