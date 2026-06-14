import os
import asyncio
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command

from bot.config import settings
from bot.keyboards import main_menu_keyboard, report_keyboard, cancel_keyboard
from bot.services.ocr import detect_and_parse
from bot.services.ai_extractor import AIExtractor
from bot.services.price_checker import check_invoice, calculate_savings
from bot.services.report_generator import generate_excel_report, generate_pdf_report

router = Router()
ai_extractor = AIExtractor(settings.ANTHROPIC_API_KEY)


class InvoiceStates(StatesGroup):
    waiting_for_file = State()


@router.message(F.text.in_(["📄 Загрузить счет", "✅ Проверить счет"]))
async def handle_upload_invoice(message: Message, state: FSMContext):
    await state.set_state(InvoiceStates.waiting_for_file)
    await message.answer(
        "Пожалуйста, загрузите файл счета (PDF, Excel, Word или изображение).",
        reply_markup=cancel_keyboard()
    )


@router.message(InvoiceStates.waiting_for_file, F.document | F.photo)
async def handle_file(message: Message, state: FSMContext, bot: Bot, user: dict):
    await message.answer("Файл получен. Обрабатываю, пожалуйста подождите...")

    try:
        db = message.bot["db"]
    except Exception:
        from bot.main import db as global_db
        db = global_db

    try:
        # Determine file info
        if message.document:
            file_id = message.document.file_id
            file_name = message.document.file_name or "invoice_file"
        elif message.photo:
            file_id = message.photo[-1].file_id
            file_name = "invoice_photo.jpg"
        else:
            await message.answer("Неподдерживаемый тип файла.")
            return

        # Download file
        os.makedirs(settings.STORAGE_PATH, exist_ok=True)
        file_path = os.path.join(settings.STORAGE_PATH, file_name)
        await bot.download(file_id, destination=file_path)

        # OCR
        await message.answer("Извлекаю текст из документа...")
        text = detect_and_parse(file_path)
        if not text or len(text.strip()) < 10:
            await message.answer(
                "Не удалось извлечь текст из файла. Попробуйте другой формат."
            )
            await state.clear()
            return

        # AI extraction
        await message.answer("Анализирую данные с помощью ИИ...")
        invoice_data = ai_extractor.extract_invoice(text)

        items = invoice_data.get("items", [])
        if not items:
            await message.answer(
                "Не удалось найти позиции в счете. "
                "Возможно, документ не является счетом или его формат не поддерживается."
            )
            await state.clear()
            return

        # Price check
        await message.answer("Сверяю цены с базой данных...")
        check_results = check_invoice(items, db)
        savings = calculate_savings(check_results)

        # Build summary message
        invoice_num = invoice_data.get("invoice_number") or "—"
        invoice_date = invoice_data.get("invoice_date") or "—"
        supplier = invoice_data.get("supplier") or "—"

        total = savings["total_items"]
        ok = savings["ok_count"]
        need_approval = savings["overpriced_count"]
        not_found = savings["not_found_count"]
        total_savings = savings["total_savings"]

        if need_approval == 0 and not_found == 0:
            conclusion = "Счет можно оплачивать полностью."
        elif need_approval > 0 and not_found == 0:
            conclusion = f"Требуется согласование по {need_approval} позициям. Потенциальная экономия: {total_savings:.2f} руб."
        elif need_approval == 0 and not_found > 0:
            conclusion = f"{not_found} позиций не найдены в базе данных. Требуется ручная проверка."
        else:
            conclusion = (
                f"Требуется согласование по {need_approval} позициям. "
                f"{not_found} позиций не найдены в базе. "
                f"Потенциальная экономия: {total_savings:.2f} руб."
            )

        summary = (
            f"✅ Счет № {invoice_num} от {invoice_date} проверен.\n"
            f"Поставщик: {supplier}\n\n"
            f"📊 Всего позиций: {total}\n"
            f"✅ Можно оплачивать: {ok}\n"
            f"⚠️ Требуют согласования: {need_approval}\n"
            f"❓ Не найдены в базе: {not_found}\n"
            f"💰 Потенциальная экономия: {total_savings:.2f} руб. без НДС\n\n"
            f"📋 Итог: {conclusion}"
        )

        # Save check to DB
        telegram_id = message.from_user.id
        db.add_invoice_check({
            "Номер счета": invoice_num,
            "Дата счета": invoice_date,
            "Поставщик": supplier,
            "Сумма": invoice_data.get("total_amount"),
            "НДС": invoice_data.get("vat_amount"),
            "Валюта": invoice_data.get("currency", "RUB"),
            "Пользователь": str(telegram_id),
            "Статус": "Проверен",
            "Потенциальная экономия": total_savings,
        })
        db.log_action(telegram_id, "Проверка счета", f"Счет №{invoice_num}, экономия {total_savings}")

        # Store results in FSM for report generation
        await state.update_data(
            invoice_data=invoice_data,
            check_results=check_results,
            savings=savings,
        )

        await message.answer(summary, reply_markup=report_keyboard())

    except Exception as e:
        await message.answer(
            f"Произошла ошибка при обработке файла: {str(e)}\n"
            "Попробуйте ещё раз или обратитесь к администратору."
        )
        await state.clear()


@router.callback_query(F.data == "report_excel")
async def handle_download_excel(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Генерирую Excel отчет...")
    try:
        data = await state.get_data()
        invoice_data = data.get("invoice_data", {})
        check_results = data.get("check_results", [])
        savings = data.get("savings", {})

        excel_bytes = generate_excel_report(invoice_data, check_results, savings)
        invoice_num = invoice_data.get("invoice_number") or "отчет"
        filename = f"Проверка_счета_{invoice_num}.xlsx"

        await callback.message.answer_document(
            BufferedInputFile(excel_bytes, filename=filename),
            caption="📊 Отчет в формате Excel"
        )
    except Exception as e:
        await callback.message.answer(f"Ошибка генерации Excel отчета: {e}")


@router.callback_query(F.data == "report_pdf")
async def handle_download_pdf(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Генерирую PDF отчет...")
    try:
        data = await state.get_data()
        invoice_data = data.get("invoice_data", {})
        check_results = data.get("check_results", [])
        savings = data.get("savings", {})

        pdf_bytes = generate_pdf_report(invoice_data, check_results, savings)
        invoice_num = invoice_data.get("invoice_number") or "отчет"
        filename = f"Проверка_счета_{invoice_num}.pdf"

        await callback.message.answer_document(
            BufferedInputFile(pdf_bytes, filename=filename),
            caption="📄 Отчет в формате PDF"
        )
    except Exception as e:
        await callback.message.answer(f"Ошибка генерации PDF отчета: {e}")


@router.message(F.text == "❌ Отмена")
async def handle_cancel(message: Message, state: FSMContext, user: dict):
    await state.clear()
    role = user.get("Роль", "user") if user else "user"
    from bot.keyboards import main_menu_keyboard
    await message.answer(
        "Действие отменено.",
        reply_markup=main_menu_keyboard(role)
    )
