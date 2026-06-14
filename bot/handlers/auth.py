from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Message


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
        # Get telegram user from event
        user = getattr(event, "from_user", None)
        if user is None:
            # Try to get from message inside callback query
            if hasattr(event, "message") and event.message:
                user = event.message.from_user
        if user is None:
            return await handler(event, data)

        telegram_id = user.id
        db_user = self.db.get_user(telegram_id)

        if db_user is None:
            # User not found - deny access
            if isinstance(event, Message):
                await event.answer(
                    "У вас нет доступа к системе. Обратитесь к администратору."
                )
            elif hasattr(event, "message") and event.message:
                await event.message.answer(
                    "У вас нет доступа к системе. Обратитесь к администратору."
                )
            return  # Stop propagation

        # Attach user data to handler context
        data["user"] = db_user
        return await handler(event, data)
