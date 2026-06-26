from typing import Optional


def check_invoice(items: list, db, ai_extractor=None, newly_added: set = None) -> list:
    """
    Check each item in the invoice against the database.
    Returns list of dicts with item data + status, min_price, deviation_percent,
    savings_per_unit, savings_amount.
    """
    results = []

    if newly_added is None:
        newly_added = set()

    for item in items:
        name = item.get("name", "")
        price_no_vat = item.get("price_no_vat")

        # Items added for the first time this session have no reference price —
        # mark them clearly so the user knows they weren't actually verified.
        if name and name.lower().strip() in newly_added:
            results.append({
                **item,
                "status": "Первое поступление",
                "min_price": price_no_vat,
                "deviation_percent": None,
                "savings_per_unit": None,
                "savings_amount": None,
                "material_id": None,
                "min_supplier": "",
                "min_material_name": "",
            })
            continue
        quantity = item.get("quantity") or 1

        # Search in DB — exact match first, then substring, then AI similarity
        exact = db.get_material(name) if name else None
        found_materials = [exact] if exact else (db.search_materials(name) if name else [])

        # If still not found, try AI similarity on candidates by first word
        if not found_materials and ai_extractor and name:
            first_word = name.split()[0] if name.split() else name
            candidates = db.search_materials(first_word)
            for candidate in candidates[:5]:
                cand_name = candidate.get("Нормализованное наименование", "")
                if ai_extractor.is_same_material(name, cand_name):
                    found_materials = [candidate]
                    break

        if not found_materials:
            results.append({
                **item,
                "status": "Материал не найден в базе",
                "min_price": None,
                "deviation_percent": None,
                "savings_per_unit": None,
                "savings_amount": None,
                "material_id": None,
            })
            continue

        # Use first match
        material = found_materials[0]
        material_id = material.get("ID")
        min_price = material.get("Минимальная цена без НДС")

        if min_price is None:
            results.append({
                **item,
                "status": "Материал не найден в базе",
                "min_price": None,
                "deviation_percent": None,
                "savings_per_unit": None,
                "savings_amount": None,
                "material_id": material_id,
            })
            continue

        try:
            min_price = float(min_price)
        except (TypeError, ValueError):
            results.append({
                **item,
                "status": "Материал не найден в базе",
                "min_price": None,
                "deviation_percent": None,
                "savings_per_unit": None,
                "savings_amount": None,
                "material_id": material_id,
            })
            continue

        if price_no_vat is None:
            status = "Цена не указана"
            deviation_percent = None
            savings_per_unit = None
            savings_amount = None
        else:
            try:
                price_no_vat_f = float(price_no_vat)
            except (TypeError, ValueError):
                price_no_vat_f = None

            if price_no_vat_f is None:
                status = "Цена не указана"
                deviation_percent = None
                savings_per_unit = None
                savings_amount = None
            elif price_no_vat_f <= min_price:
                status = "Можно оплачивать"
                deviation_percent = 0.0
                savings_per_unit = 0.0
                savings_amount = 0.0
            else:
                status = "Требуется согласование"
                deviation_percent = round((price_no_vat_f - min_price) / min_price * 100, 2)
                savings_per_unit = round(price_no_vat_f - min_price, 2)
                savings_amount = round(savings_per_unit * float(quantity), 2)

        result_dict = {
            **item,
            "status": status,
            "min_price": min_price,
            "deviation_percent": deviation_percent,
            "savings_per_unit": savings_per_unit,
            "savings_amount": savings_amount,
            "material_id": material_id,
        }
        if status == "Требуется согласование":
            result_dict["min_supplier"] = str(material.get("Поставщик минимальной цены") or "")
            result_dict["min_material_name"] = str(material.get("Нормализованное наименование") or "")
        results.append(result_dict)

    return results


def calculate_savings(check_results: list) -> dict:
    """Calculate total savings and statistics from check results."""
    total_savings = 0.0
    overpriced_count = 0
    ok_count = 0
    not_found_count = 0
    new_count = 0
    total_items = len(check_results)

    for item in check_results:
        status = item.get("status", "")
        if status == "Можно оплачивать":
            ok_count += 1
        elif status == "Требуется согласование":
            overpriced_count += 1
            savings = item.get("savings_amount") or 0
            total_savings += float(savings)
        elif status == "Материал не найден в базе":
            not_found_count += 1
        elif status == "Первое поступление":
            new_count += 1

    return {
        "total_savings": round(total_savings, 2),
        "overpriced_count": overpriced_count,
        "ok_count": ok_count,
        "not_found_count": not_found_count,
        "new_count": new_count,
        "total_items": total_items,
    }
