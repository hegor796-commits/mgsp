import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import settings
from bot.database import ExcelDatabase
from aiogram import F
from aiogram.filters import Command
from aiogram.types import Message

from bot.handlers.auth import AuthMiddleware
from bot.handlers import invoice, search, reports, admin
from bot.keyboards import main_menu_keyboard

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

    # Register middleware
    dp.update.middleware(AuthMiddleware(db))

    # /start and /help commands
    @dp.message(Command("start"))
    async def cmd_start(message: Message, user: dict = None):
        if user is None:
            return
        role = user.get("Роль", "user")
        name = user.get("ФИО") or message.from_user.full_name
        await message.answer(
            f"Добро пожаловать, {name}!\n\n"
            f"Роль: <b>{role}</b>\n\n"
            "Выберите действие в меню ниже.",
            reply_markup=main_menu_keyboard(role)
        )
        db.log_action(message.from_user.id, "Вход в систему", f"Роль: {role}")

    @dp.message(Command("menu"))
    async def cmd_menu(message: Message, user: dict = None):
        if user is None:
            return
        role = user.get("Роль", "user")
        await message.answer("Главное меню:", reply_markup=main_menu_keyboard(role))

    # Include routers
    dp.include_router(invoice.router)
    dp.include_router(search.router)
    dp.include_router(reports.router)
    dp.include_router(admin.router)

    logger.info("Бот запущен. Начинаю polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), db=db)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
