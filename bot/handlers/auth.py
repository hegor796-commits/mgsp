from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message, CallbackQuery


class AuthMiddleware(BaseMiddleware):
    def __init__(self, db):
        self.db = db
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Extract telegram user from any event type
        if isinstance(event, Message):
            tg_user = event.from_user
        elif isinstance(event, CallbackQuery):
            tg_user = event.from_user
        else:
            tg_user = getattr(event, "from_user", None)

        if tg_user is None:
            return await handler(event, data)

        db_user = self.db.get_user(tg_user.id)

        if db_user is None:
            if isinstance(event, Message):
                await event.answer(
                    "У вас нет доступа к системе. Обратитесь к администратору."
                )
            elif isinstance(event, CallbackQuery):
                await event.answer(
                    "У вас нет доступа к системе.", show_alert=True
                )
            return

        data["user"] = db_user
        return await handler(event, data)
