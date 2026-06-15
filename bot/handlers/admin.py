from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from bot.keyboards import main_menu_keyboard, admin_keyboard, cancel_keyboard

router = Router()


class AddUserStates(StatesGroup):
    waiting_for_telegram_id = State()
    waiting_for_name = State()
    waiting_for_role = State()


class AddMaterialStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_unit = State()
    waiting_for_category = State()


def is_admin(user: dict) -> bool:
    return user and user.get("Роль") == "admin"


@router.message(F.text == "⚙️ Администрирование")
async def handle_admin_menu(message: Message, user: dict):
    if not is_admin(user):
        await message.answer("У вас нет прав для выполнения этой операции.")
        return
    await message.answer(
        "⚙️ <b>Панель администратора</b>\n\nВыберите действие:",
        parse_mode="HTML",
        reply_markup=admin_keyboard()
    )


@router.callback_query(F.data == "admin_add_user")
async def handle_add_user_start(callback: CallbackQuery, state: FSMContext, user: dict):
    if not is_admin(user):
        await callback.answer("Нет прав доступа.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AddUserStates.waiting_for_telegram_id)
    await callback.message.answer(
        "Введите Telegram ID нового пользователя (числовой идентификатор):",
        reply_markup=cancel_keyboard()
    )


@router.message(AddUserStates.waiting_for_telegram_id)
async def handle_add_user_id(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("Введите корректный числовой Telegram ID.")
        return
    await state.update_data(new_telegram_id=int(text))
    await state.set_state(AddUserStates.waiting_for_name)
    await message.answer("Введите ФИО пользователя:")


@router.message(AddUserStates.waiting_for_name)
async def handle_add_user_name(message: Message, state: FSMContext):
    await state.update_data(new_name=message.text.strip())
    await state.set_state(AddUserStates.waiting_for_role)
    await message.answer(
        "Введите роль пользователя:\n"
        "• <code>user</code> — обычный пользователь\n"
        "• <code>снабженец</code> — снабженец\n"
        "• <code>admin</code> — администратор",
        parse_mode="HTML"
    )


@router.message(AddUserStates.waiting_for_role)
async def handle_add_user_role(message: Message, state: FSMContext, user: dict):
    role = message.text.strip().lower()
    valid_roles = ["user", "снабженец", "admin"]
    if role not in valid_roles:
        await message.answer(
            f"Некорректная роль. Допустимые значения: {', '.join(valid_roles)}"
        )
        return

    data = await state.get_data()
    new_id = data.get("new_telegram_id")
    new_name = data.get("new_name")
    await state.clear()

    try:
        from bot.main import db
        db.add_user(new_id, new_name, role)
        db.log_action(
            message.from_user.id,
            "Добавление пользователя",
            f"ID: {new_id}, Имя: {new_name}, Роль: {role}"
        )
        admin_role = user.get("Роль", "admin") if user else "admin"
        await message.answer(
            f"✅ Пользователь успешно добавлен:\n"
            f"Telegram ID: {new_id}\n"
            f"ФИО: {new_name}\n"
            f"Роль: {role}",
            reply_markup=main_menu_keyboard(admin_role)
        )
    except Exception as e:
        await message.answer(f"Ошибка при добавлении пользователя: {e}")


@router.callback_query(F.data == "admin_add_material")
async def handle_add_material_start(callback: CallbackQuery, state: FSMContext, user: dict):
    if not is_admin(user):
        await callback.answer("Нет прав доступа.", show_alert=True)
        return
    await callback.answer()
    await state.set_state(AddMaterialStates.waiting_for_name)
    await callback.message.answer(
        "Введите нормализованное наименование нового материала:",
        reply_markup=cancel_keyboard()
    )


@router.message(AddMaterialStates.waiting_for_name)
async def handle_add_material_name(message: Message, state: FSMContext):
    await state.update_data(mat_name=message.text.strip())
    await state.set_state(AddMaterialStates.waiting_for_unit)
    await message.answer("Введите единицу измерения (например: шт, м, кг, м²):")


@router.message(AddMaterialStates.waiting_for_unit)
async def handle_add_material_unit(message: Message, state: FSMContext):
    await state.update_data(mat_unit=message.text.strip())
    await state.set_state(AddMaterialStates.waiting_for_category)
    await message.answer("Введите категорию материала (или оставьте пустым):")


@router.message(AddMaterialStates.waiting_for_category)
async def handle_add_material_category(message: Message, state: FSMContext, user: dict):
    data = await state.get_data()
    await state.clear()

    mat_name = data.get("mat_name", "")
    mat_unit = data.get("mat_unit", "")
    mat_category = message.text.strip()

    try:
        from bot.main import db
        mat_id = db.add_material({
            "Нормализованное наименование": mat_name,
            "Единица измерения": mat_unit,
            "Категория": mat_category,
            "Активен": "Да",
        })
        db.log_action(
            message.from_user.id,
            "Добавление материала",
            f"Наименование: {mat_name}, ID: {mat_id}"
        )
        role = user.get("Роль", "admin") if user else "admin"
        await message.answer(
            f"✅ Материал добавлен в базу:\n"
            f"ID: {mat_id}\n"
            f"Наименование: {mat_name}\n"
            f"Ед. изм.: {mat_unit}\n"
            f"Категория: {mat_category or '—'}",
            reply_markup=main_menu_keyboard(role)
        )
    except Exception as e:
        await message.answer(f"Ошибка при добавлении материала: {e}")


@router.callback_query(F.data == "admin_list_users")
async def handle_list_users(callback: CallbackQuery, user: dict):
    if not is_admin(user):
        await callback.answer("Нет прав доступа.", show_alert=True)
        return
    await callback.answer()

    try:
        from bot.main import db
        from openpyxl import load_workbook
        wb = load_workbook(db.db_path)
        ws = wb["Пользователи"]
        headers = [cell.value for cell in ws[1]]
        users = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if all(v is None for v in row):
                continue
            users.append(dict(zip(headers, row)))

        if not users:
            await callback.message.answer("Список пользователей пуст.")
            return

        lines = ["👥 <b>Список пользователей:</b>\n"]
        for u in users:
            lines.append(
                f"• {u.get('ФИО', '—')} (ID: {u.get('Telegram ID', '—')})\n"
                f"  Роль: {u.get('Роль', '—')}, "
                f"Активен: {u.get('Активен', '—')}"
            )
        await callback.message.answer(
            "\n".join(lines),
            parse_mode="HTML"
        )
    except Exception as e:
        await callback.message.answer(f"Ошибка получения списка пользователей: {e}")


@router.callback_query(F.data == "admin_dedup")
async def handle_dedup(callback: CallbackQuery, user: dict):
    if not is_admin(user):
        await callback.answer("Нет прав доступа.", show_alert=True)
        return
    await callback.answer()
    try:
        from bot.main import db
        removed = db.deduplicate_materials()
        await callback.message.answer(
            f"Готово. Удалено дублирующихся позиций: {removed}"
        )
    except Exception as e:
        await callback.message.answer(f"Ошибка при очистке дубликатов: {e}")


@router.message(F.text == "➕ Добавить данные в базу знаний")
async def handle_add_to_kb(message: Message, state: FSMContext, user: dict):
    if not is_admin(user) and user.get("Роль") != "снабженец":
        await message.answer("У вас нет прав для выполнения этой операции.")
        return
    await state.set_state(AddMaterialStates.waiting_for_name)
    await message.answer(
        "Введите нормализованное наименование материала для добавления в базу:",
        reply_markup=cancel_keyboard()
    )
