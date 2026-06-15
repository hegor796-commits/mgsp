from aiogram.types import (
    ReplyKeyboardMarkup, KeyboardButton,
    InlineKeyboardMarkup, InlineKeyboardButton
)


def main_menu_keyboard(role: str) -> ReplyKeyboardMarkup:
    base_buttons = [
        [KeyboardButton(text="📄 Загрузить счет"), KeyboardButton(text="🔍 Найти материал")],
        [KeyboardButton(text="💰 Посмотреть минимальную цену"), KeyboardButton(text="🔄 Найти аналог")],
        [KeyboardButton(text="❓ Помощь")],
    ]

    if role in ("снабженец", "Снабженец", "supply", "admin"):
        base_buttons.insert(2, [
            KeyboardButton(text="✅ Проверить счет"),
            KeyboardButton(text="📊 Выгрузить отчет"),
        ])
        base_buttons.insert(3, [KeyboardButton(text="➕ Добавить данные в базу знаний")])

    if role in ("admin", "администратор"):
        base_buttons.append([KeyboardButton(text="⚙️ Администрирование")])

    return ReplyKeyboardMarkup(keyboard=base_buttons, resize_keyboard=True)


def report_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📊 Скачать Excel", callback_data="report_excel"),
            InlineKeyboardButton(text="📄 Скачать PDF", callback_data="report_pdf"),
        ],
        [
            InlineKeyboardButton(text="🔄 Обновить цены в базе", callback_data="add_items_to_db"),
        ]
    ])


def add_to_db_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да, добавить", callback_data="add_to_db_yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data="add_to_db_no"),
        ]
    ])


def update_price_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Обновить цену", callback_data="update_price_yes"),
            InlineKeyboardButton(text="❌ Оставить", callback_data="update_price_no"),
        ]
    ])


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )


def admin_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Добавить пользователя", callback_data="admin_add_user")],
        [InlineKeyboardButton(text="📦 Добавить материал", callback_data="admin_add_material")],
        [InlineKeyboardButton(text="📋 Список пользователей", callback_data="admin_list_users")],
        [InlineKeyboardButton(text="🧹 Очистить дубликаты в базе", callback_data="admin_dedup")],
    ])


def period_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Сегодня", callback_data="period_today"),
            InlineKeyboardButton(text="Неделя", callback_data="period_week"),
            InlineKeyboardButton(text="Месяц", callback_data="period_month"),
        ]
    ])
