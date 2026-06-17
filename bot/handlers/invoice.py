import os
import json
import asyncio
import zipfile
import shutil
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.filters import Command, StateFilter

from bot.config import settings
from bot.keyboards import main_menu_keyboard, report_keyboard, cancel_keyboard
from bot.services.ocr import detect_and_parse
from bot.services.ai_extractor import AIExtractor
from bot.services.price_checker import check_invoice, calculate_savings
from bot.services.report_generator import generate_excel_report, generate_pdf_report


def _save_invoice_cache(user_id: int, data: dict):
    os.makedirs(settings.STORAGE_PATH, exist_ok=True)
    path = os.path.join(settings.STORAGE_PATH, f"invoice_{user_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, default=str)


def _load_invoice_cache(user_id: int) -> dict:
    path = os.path.join(settings.STORAGE_PATH, f"invoice_{user_id}.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

router = Router()
ai_extractor = AIExtractor(settings.OPENAI_API_KEY)


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
    # Redirect ZIP archives to the batch processor instead of treating them
    # as a single invoice file.
    if message.document and (message.document.file_name or "").lower().endswith(".zip"):
        await state.clear()
        await handle_zip(message, state, bot, user)
        return

    await message.answer("Файл получен. Обрабатываю, пожалуйста подождите...")

    from bot.main import db

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

        # Normalize names via AI and auto-add new items to DB
        await message.answer("Нормализую названия и проверяю базу данных...")
        supplier_raw = invoice_data.get("supplier") or ""
        invoice_num_raw = invoice_data.get("invoice_number") or ""
        invoice_date_raw = invoice_data.get("invoice_date") or ""
        auto_added = 0
        seen_names: set[str] = set()  # deduplicate within this invoice
        for item in items:
            raw_name = item.get("name", "").strip()
            if not raw_name:
                continue
            price = ai_extractor.resolve_price_no_vat(item, invoice_data) or item.get("price_with_vat")
            item["price_no_vat"] = price  # keep consistent with the price stored in the DB below
            unit = item.get("unit") or "шт"
            characteristics = {k: v for k, v in item.items()
                               if k not in ("name", "unit", "quantity", "price_no_vat",
                                            "price_with_vat", "amount") and v}
            normalized = ai_extractor.normalize_name(raw_name, characteristics)
            # Replace name with normalized so price_checker can find it in DB
            item["name"] = normalized
            key = normalized.lower().strip()
            if key in seen_names:
                continue  # duplicate within same invoice
            seen_names.add(key)
            # Exact match check
            existing = db.get_material(normalized)
            if existing is None:
                # Fuzzy check: search by first meaningful word, then ask AI
                first_word = normalized.split()[0] if normalized.split() else normalized
                candidates = db.search_materials(first_word)
                for candidate in candidates[:5]:
                    cand_name = candidate.get("Нормализованное наименование", "")
                    if ai_extractor.is_same_material(normalized, cand_name):
                        existing = candidate
                        item["name"] = cand_name  # point to existing record
                        break

            if existing is None:
                db.add_material({
                    "Нормализованное наименование": normalized,
                    "Единица измерения": unit,
                    "Минимальная цена без НДС": price,
                    "Поставщик минимальной цены": supplier_raw,
                })
                if price:
                    mat = db.get_material(normalized)
                    if mat:
                        db.add_price_history({
                            "ID материала": mat.get("ID"),
                            "Цена без НДС": price,
                            "Поставщик": supplier_raw,
                            "Номер счета": invoice_num_raw,
                            "Дата счета": invoice_date_raw,
                            "Пользователь": str(message.from_user.id),
                        })
                auto_added += 1
            elif price:
                existing_price = existing.get("Минимальная цена без НДС")
                if existing_price is None or float(price) < float(existing_price):
                    db.update_min_price(
                        existing["ID"], float(price), supplier_raw,
                        invoice_num_raw, invoice_date_raw, message.from_user.id
                    )

        # Price check (uses normalized names that are now in DB)
        await message.answer("Сверяю цены с базой данных...")
        check_results = check_invoice(items, db, ai_extractor)
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

        auto_added_line = f"🆕 Автоматически добавлено в базу: {auto_added} новых позиций\n" if auto_added else ""

        summary = (
            f"✅ Счет № {invoice_num} от {invoice_date} проверен.\n"
            f"Поставщик: {supplier}\n\n"
            f"📊 Всего позиций: {total}\n"
            f"✅ Можно оплачивать: {ok}\n"
            f"⚠️ Требуют согласования: {need_approval}\n"
            f"❓ Не найдены в базе: {not_found}\n"
            f"💰 Потенциальная экономия: {total_savings:.2f} руб. без НДС\n"
            f"{auto_added_line}\n"
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

        # Store results in FSM and in file (survives bot restarts)
        await state.update_data(
            invoice_data=invoice_data,
            check_results=check_results,
            savings=savings,
        )
        _save_invoice_cache(telegram_id, {
            "invoice_data": invoice_data,
            "check_results": check_results,
            "savings": savings,
        })

        role = user.get("Роль", "user") if user else "user"
        # Do NOT clear state here — report/update buttons still need FSM data
        await message.answer(summary, reply_markup=main_menu_keyboard(role))
        await message.answer("Выберите действие для получения отчета:", reply_markup=report_keyboard())

    except Exception as e:
        await message.answer(
            f"Произошла ошибка при обработке файла: {str(e)}\n"
            "Попробуйте ещё раз или обратитесь к администратору."
        )
        await state.clear()


def _get_session_data(fsm_data: dict, user_id: int) -> dict:
    """Return FSM data, falling back to file cache if FSM was wiped by restart."""
    if fsm_data.get("invoice_data"):
        return fsm_data
    return _load_invoice_cache(user_id)


@router.callback_query(F.data == "report_excel")
async def handle_download_excel(callback: CallbackQuery, state: FSMContext):
    await callback.answer("Генерирую Excel отчет...")
    try:
        data = _get_session_data(await state.get_data(), callback.from_user.id)
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
        data = _get_session_data(await state.get_data(), callback.from_user.id)
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


@router.callback_query(F.data == "add_items_to_db")
async def handle_add_items_to_db(callback: CallbackQuery, state: FSMContext, user: dict):
    await callback.answer()
    await callback.message.answer("Обновляю цены в базе данных, подождите...")

    from bot.main import db

    data = _get_session_data(await state.get_data(), callback.from_user.id)
    invoice_data = data.get("invoice_data", {})
    items = invoice_data.get("items", [])

    if not items:
        await callback.message.answer("Нет позиций для обновления — загрузите счёт заново.")
        return

    supplier = invoice_data.get("supplier") or ""
    invoice_num = invoice_data.get("invoice_number") or ""
    invoice_date = invoice_data.get("invoice_date") or ""

    added = 0
    updated = 0
    skipped = 0

    for item in items:
        raw_name = item.get("name", "").strip()
        if not raw_name:
            continue

        price = ai_extractor.resolve_price_no_vat(item, invoice_data) or item.get("price_with_vat")
        item["price_no_vat"] = price
        unit = item.get("unit") or "шт"

        # Normalize name via AI
        characteristics = {k: v for k, v in item.items()
                           if k not in ("name", "unit", "quantity", "price_no_vat",
                                        "price_with_vat", "amount") and v}
        normalized = ai_extractor.normalize_name(raw_name, characteristics)

        existing = db.get_material(normalized)

        if existing is None:
            db.add_material({
                "Нормализованное наименование": normalized,
                "Единица измерения": unit,
                "Минимальная цена без НДС": price,
                "Поставщик минимальной цены": supplier,
            })
            if price:
                material_id = db.get_material(normalized).get("ID")
                db.add_price_history({
                    "ID материала": material_id,
                    "Цена без НДС": price,
                    "Поставщик": supplier,
                    "Номер счета": invoice_num,
                    "Дата счета": invoice_date,
                    "Пользователь": str(callback.from_user.id),
                })
            added += 1
        else:
            existing_price = existing.get("Минимальная цена без НДС")
            if price and (existing_price is None or float(price) < float(existing_price)):
                db.update_min_price(
                    existing["ID"], float(price), supplier,
                    invoice_num, invoice_date, callback.from_user.id
                )
                updated += 1
            else:
                skipped += 1

    db.log_action(callback.from_user.id, "Добавление позиций из счета",
                  f"Счет №{invoice_num}: добавлено {added}, обновлено {updated}, пропущено {skipped}")

    await callback.message.answer(
        f"Готово\n\n"
        f"🔄 Цена обновлена (нашли дешевле): {updated}\n"
        f"⏭ Пропущено (цена не ниже имеющейся): {skipped + added}"
    )


@router.message(F.document, F.document.func(lambda d: (d.file_name or "").lower().endswith(".zip")))
async def handle_zip(message: Message, state: FSMContext, bot: Bot, user: dict):
    """Handle a ZIP archive containing multiple invoice files."""
    await state.clear()
    file_size_mb = (message.document.file_size or 0) / 1024 / 1024
    if file_size_mb > 19:
        await message.answer(
            f"⚠️ Файл слишком большой ({file_size_mb:.1f} МБ). "
            "Telegram позволяет загружать файлы до 20 МБ. "
            "Разбейте архив на несколько частей."
        )
        return

    await message.answer(
        "📦 ZIP-архив получен. Начинаю обработку в фоне — "
        "я буду сообщать о прогрессе каждые 10 файлов.\n\n"
        "Пока идёт обработка, можете пользоваться ботом в обычном режиме."
    )

    from bot.main import db
    chat_id = message.chat.id
    user_id = message.from_user.id

    asyncio.create_task(
        _process_zip_background(bot, chat_id, user_id, message.document.file_id, db)
    )


def _process_zip_file(file_path: str, db, user_id: int, api_key: str) -> tuple[int, int, str]:
    """Process one file from a ZIP batch synchronously (runs in a thread).
    Returns (added, updated, skip_reason) — skip_reason is non-empty when
    the file yielded nothing so callers can report diagnostics."""
    from bot.services.ocr import detect_and_parse
    from bot.services.ai_extractor import AIExtractor

    # gpt-4o-mini: ~500 RPM limit vs ~10 RPM for gpt-4o — essential for batch
    extractor = AIExtractor(api_key, model="gpt-4o-mini")

    text = detect_and_parse(file_path)
    if not text or len(text.strip()) < 10:
        return 0, 0, "empty_text"

    invoice_data = extractor.extract_invoice(text)
    items = invoice_data.get("items", [])

    # Fallback: if extract_invoice found nothing, try the price-list extractor
    if not items:
        materials = extractor.extract_materials_for_db(text)
        if materials:
            invoice_data = {
                "invoice_number": None,
                "invoice_date": None,
                "supplier": None,
                "total_amount": None,
                "vat_amount": None,
            }
            items = [
                {
                    "name": m.get("name"),
                    "unit": m.get("unit") or "шт",
                    "price_no_vat": m.get("price_no_vat"),
                    "price_with_vat": m.get("price_with_vat"),
                    "amount": m.get("amount"),
                    "quantity": m.get("quantity"),
                }
                for m in materials
                if m.get("name")
            ]
    if not items:
        return 0, 0, "no_items"

    supplier = invoice_data.get("supplier") or ""
    invoice_num = invoice_data.get("invoice_number") or ""
    invoice_date = invoice_data.get("invoice_date") or ""
    seen: set[str] = set()
    added = updated = 0

    for item in items:
        raw_name = (item.get("name") or "").strip()
        if not raw_name:
            continue
        price = extractor.resolve_price_no_vat(item, invoice_data) or item.get("price_with_vat")
        item["price_no_vat"] = price
        unit = item.get("unit") or "шт"
        characteristics = {k: v for k, v in item.items()
                           if k not in ("name", "unit", "quantity", "price_no_vat",
                                        "price_with_vat", "amount") and v}
        normalized = extractor.normalize_name(raw_name, characteristics)
        key = normalized.lower().strip()
        if key in seen:
            continue
        seen.add(key)

        existing = db.get_material(normalized)
        if existing is None:
            first_word = normalized.split()[0] if normalized.split() else normalized
            for candidate in db.search_materials(first_word)[:10]:
                cand_name = candidate.get("Нормализованное наименование", "")
                if extractor.is_same_material(normalized, cand_name):
                    existing = candidate
                    break

        if existing is None:
            db.add_material({
                "Нормализованное наименование": normalized,
                "Единица измерения": unit,
                "Минимальная цена без НДС": price,
                "Поставщик минимальной цены": supplier,
            })
            if price:
                mat = db.get_material(normalized)
                if mat:
                    db.add_price_history({
                        "ID материала": mat.get("ID"),
                        "Цена без НДС": price,
                        "Поставщик": supplier,
                        "Номер счета": invoice_num,
                        "Дата счета": invoice_date,
                        "Пользователь": str(user_id),
                    })
            added += 1
        elif price:
            existing_price = existing.get("Минимальная цена без НДС")
            if existing_price is None or float(price) < float(existing_price):
                db.update_min_price(
                    existing["ID"], float(price), supplier,
                    invoice_num, invoice_date, user_id
                )
                updated += 1

    return added, updated, ""


async def _process_zip_background(bot: Bot, chat_id: int, user_id: int, file_id: str, db):
    """Background task: unpack ZIP, extract + normalize each invoice, update DB."""
    zip_dir = os.path.join(settings.STORAGE_PATH, f"zip_{user_id}")
    zip_path = os.path.join(settings.STORAGE_PATH, f"zip_{user_id}.zip")
    os.makedirs(settings.STORAGE_PATH, exist_ok=True)

    try:
        await bot.download(file_id, destination=zip_path)

        with zipfile.ZipFile(zip_path, "r") as zf:
            # Filter out macOS/hidden junk files
            members = [
                m for m in zf.namelist()
                if not os.path.basename(m).startswith("._")
                and not os.path.basename(m).startswith("__MACOSX")
                and os.path.basename(m)  # skip directory entries
            ]
            zf.extractall(zip_dir)

        total = len(members)
        if total == 0:
            await bot.send_message(chat_id, "❌ Архив пуст или не содержит поддерживаемых файлов.")
            return

        await bot.send_message(chat_id, f"🗂 Найдено файлов в архиве: {total}. Начинаю обработку...")

        added_total = 0
        updated_total = 0
        errors = 0
        skipped_empty = 0
        skipped_no_items = 0
        processed = 0
        # Process one file at a time; _call_openai also rate-limits to 1 req/s
        semaphore = asyncio.Semaphore(1)

        async def process_one(member: str):
            nonlocal added_total, updated_total, errors, skipped_empty, skipped_no_items, processed
            file_path = os.path.join(zip_dir, member)
            if not os.path.isfile(file_path):
                return
            async with semaphore:
                try:
                    added, updated, skip_reason = await asyncio.to_thread(
                        _process_zip_file, file_path, db, user_id, settings.OPENAI_API_KEY
                    )
                    added_total += added
                    updated_total += updated
                    if skip_reason == "empty_text":
                        skipped_empty += 1
                    elif skip_reason == "no_items":
                        skipped_no_items += 1
                except Exception:
                    errors += 1
                processed += 1

        tasks = [asyncio.create_task(process_one(m)) for m in members]
        for i, task in enumerate(asyncio.as_completed(tasks)):
            await task
            if (i + 1) % 10 == 0 or (i + 1) == len(tasks):
                await bot.send_message(
                    chat_id,
                    f"⏳ Обработано {processed}/{total} файлов...\n"
                    f"✅ Добавлено позиций: {added_total}\n"
                    f"🔄 Цена обновлена: {updated_total}\n"
                    f"📭 Пустых файлов: {skipped_empty}\n"
                    f"📄 Не счетов (нет товаров): {skipped_no_items}\n"
                    f"❌ Ошибок: {errors}"
                )

        db.log_action(user_id, "Пакетная обработка ZIP",
                      f"Файлов: {total}, добавлено: {added_total}, обновлено: {updated_total}, "
                      f"пустых: {skipped_empty}, без товаров: {skipped_no_items}, ошибок: {errors}")

        await bot.send_message(
            chat_id,
            f"🎉 Обработка архива завершена!\n\n"
            f"📂 Всего файлов: {total}\n"
            f"✅ Новых позиций добавлено в базу: {added_total}\n"
            f"🔄 Цен обновлено (нашли дешевле): {updated_total}\n"
            f"📭 Пустых/нечитаемых файлов: {skipped_empty}\n"
            f"📄 Файлов без товаров (договоры, акты и т.п.): {skipped_no_items}\n"
            f"❌ Файлов с ошибками: {errors}"
        )

    except zipfile.BadZipFile:
        await bot.send_message(chat_id, "❌ Не удалось открыть архив. Убедитесь, что файл является корректным ZIP.")
    except Exception as e:
        await bot.send_message(chat_id, f"❌ Ошибка при обработке архива: {e}")
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
        if os.path.exists(zip_dir):
            shutil.rmtree(zip_dir, ignore_errors=True)


@router.message(StateFilter("*"), F.text == "❌ Отмена")
async def handle_cancel(message: Message, state: FSMContext, user: dict):
    await state.clear()
    role = user.get("Роль", "user") if user else "user"
    await message.answer(
        "Действие отменено.",
        reply_markup=main_menu_keyboard(role)
    )
