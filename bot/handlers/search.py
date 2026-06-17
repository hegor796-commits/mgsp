from aiogram import Router, F
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import StateFilter

from bot.keyboards import main_menu_keyboard, cancel_keyboard

router = Router()


class SearchStates(StatesGroup):
    waiting_for_material_name = State()
    waiting_for_min_price_query = State()
    waiting_for_analog_query = State()


@router.message(StateFilter("*"), F.text == "❌ Отмена")
async def handle_cancel_search(message: Message, state: FSMContext, user: dict):
    await state.clear()
    role = user.get("Роль", "user") if user else "user"
    await message.answer("Действие отменено.", reply_markup=main_menu_keyboard(role))


@router.message(F.text == "🔍 Найти материал")
async def handle_find_material(message: Message, state: FSMContext):
    await state.set_state(SearchStates.waiting_for_material_name)
    await message.answer(
        "Введите наименование материала для поиска:",
        reply_markup=cancel_keyboard()
    )


@router.message(SearchStates.waiting_for_material_name)
async def handle_material_search_result(message: Message, state: FSMContext, user: dict):
    query = message.text.strip()
    if not query:
        await message.answer("Введите наименование материала.")
        return

    await state.clear()

    try:
        from bot.main import db
        results = db.search_materials(query)
    except Exception as e:
        await message.answer(f"Ошибка поиска: {e}")
        return

    role = user.get("Роль", "user") if user else "user"

    if not results:
        await message.answer(
            f"Материалы по запросу «{query}» не найдены в базе данных.",
            reply_markup=main_menu_keyboard(role)
        )
        return

    lines = [f"🔍 Результаты поиска по запросу «{query}»:\n"]
    for i, mat in enumerate(results[:15], 1):
        name = mat.get("Нормализованное наименование", "—")
        unit = mat.get("Единица измерения", "—")
        min_price = mat.get("Минимальная цена без НДС")
        supplier = mat.get("Поставщик минимальной цены", "—")
        price_str = f"{min_price:.2f} руб." if min_price is not None else "не указана"
        lines.append(
            f"{i}. {name}\n"
            f"   Ед. изм.: {unit}\n"
            f"   Мин. цена: {price_str}\n"
            f"   Поставщик: {supplier}\n"
        )

    if len(results) > 15:
        lines.append(f"...и ещё {len(results) - 15} результатов. Уточните запрос.")

    await message.answer("\n".join(lines), reply_markup=main_menu_keyboard(role))


@router.message(F.text == "💰 Посмотреть минимальную цену")
async def handle_min_price(message: Message, state: FSMContext):
    await state.set_state(SearchStates.waiting_for_min_price_query)
    await message.answer(
        "Введите наименование материала для просмотра минимальной цены:",
        reply_markup=cancel_keyboard()
    )


@router.message(SearchStates.waiting_for_min_price_query)
async def handle_min_price_result(message: Message, state: FSMContext, user: dict):
    query = message.text.strip()
    await state.clear()
    role = user.get("Роль", "user") if user else "user"

    try:
        from bot.main import db
        results = db.search_materials(query)
    except Exception as e:
        await message.answer(f"Ошибка поиска: {e}")
        return

    if not results:
        await message.answer(
            f"Материал «{query}» не найден в базе.",
            reply_markup=main_menu_keyboard(role)
        )
        return

    blocks = []
    for mat in results[:15]:
        name = mat.get("Нормализованное наименование", "—")
        min_price = mat.get("Минимальная цена без НДС")
        supplier = mat.get("Поставщик минимальной цены", "—")
        updated = mat.get("Дата последнего обновления", "—")
        price_str = f"{float(min_price):.2f} руб. без НДС" if min_price is not None else "не указана"
        blocks.append(
            f"Наименование: {name}\n"
            f"Мин. цена: {price_str}\n"
            f"Поставщик: {supplier}\n"
            f"Дата обновления: {updated}"
        )

    header = f"💰 Найдено {len(results)} позиций по запросу «{query}»:\n\n"
    await message.answer(
        header + "\n\n".join(blocks),
        reply_markup=main_menu_keyboard(role)
    )


@router.message(F.text == "🔄 Найти аналог")
async def handle_find_analog(message: Message, state: FSMContext):
    await state.set_state(SearchStates.waiting_for_analog_query)
    await message.answer(
        "Введите наименование материала для поиска аналогов:",
        reply_markup=cancel_keyboard()
    )


@router.message(SearchStates.waiting_for_analog_query)
async def handle_analog_search(message: Message, state: FSMContext, user: dict):
    query = message.text.strip()
    await state.clear()
    role = user.get("Роль", "user") if user else "user"

    try:
        from bot.main import db
        from bot.config import settings
        from bot.services.ai_extractor import AIExtractor

        results = db.search_materials(query)

        if results:
            mat = results[0]
            material_id = mat.get("ID")
            db_analogs = db.get_analogs(material_id)
        else:
            mat = None
            db_analogs = []

        lines = [f"🔄 Аналоги для «{query}»:\n"]

        if db_analogs:
            lines.append("📦 Аналоги из базы данных:")
            for analog in db_analogs:
                lines.append(f"  • ID аналога: {analog.get('ID аналога')}, "
                              f"Коэффициент: {analog.get('Коэффициент замены', 1)}")
        else:
            lines.append("В базе данных аналоги не найдены.")

        # AI-based analog search
        all_materials = db.get_all_materials()
        if all_materials:
            extractor = AIExtractor(settings.OPENAI_API_KEY)
            ai_analogs = extractor.find_analogs(query, {}, all_materials)
            if ai_analogs:
                lines.append("\n🤖 Аналоги по мнению ИИ:")
                for a in ai_analogs[:5]:
                    sim = a.get("similarity", 0)
                    lines.append(
                        f"  • {a.get('material_name', '—')}\n"
                        f"    Схожесть: {sim:.0%}\n"
                        f"    {a.get('comment', '')}"
                    )

        await message.answer("\n".join(lines), reply_markup=main_menu_keyboard(role))

    except Exception as e:
        await message.answer(
            f"Ошибка при поиске аналогов: {e}",
            reply_markup=main_menu_keyboard(role)
        )


@router.message(F.text == "❓ Помощь")
async def handle_help(message: Message, user: dict):
    role = user.get("Роль", "user") if user else "user"
    help_text = (
        "ℹ️ <b>Справка по боту анализа счетов</b>\n\n"
        "<b>Доступные функции:</b>\n"
        "📄 <b>Загрузить счет</b> — загрузите файл счета для анализа\n"
        "🔍 <b>Найти материал</b> — поиск материала в базе данных\n"
        "💰 <b>Мин. цена</b> — просмотр минимальной цены материала\n"
        "🔄 <b>Найти аналог</b> — поиск аналогов материала\n\n"
        "<b>Поддерживаемые форматы файлов:</b>\n"
        "PDF, Excel (.xlsx, .xls), Word (.docx), изображения (JPG, PNG)\n\n"
        "<b>Статусы позиций:</b>\n"
        "✅ Можно оплачивать — цена не превышает минимальную в базе\n"
        "⚠️ Требуется согласование — цена выше минимальной\n"
        "❓ Не найден в базе — материал отсутствует в базе данных\n\n"
        "По вопросам обратитесь к администратору."
    )
    await message.answer(help_text, parse_mode="HTML", reply_markup=main_menu_keyboard(role))
