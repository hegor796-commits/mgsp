import json
import re
from openai import OpenAI


SYSTEM_PROMPT = """Ты — специализированный ассистент для анализа счетов и накладных на русском языке.
Ты извлекаешь структурированные данные из текста финансовых документов.
Всегда отвечай только в формате JSON без дополнительных пояснений.
При неуверенности указывай null для соответствующих полей.
"""


class AIExtractor:
    def __init__(self, api_key: str):
        self.client = OpenAI(api_key=api_key)
        self.model = "gpt-4o"

    def _call_openai(self, prompt: str, system: str = None) -> str:
        response = self.client.chat.completions.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": system or SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        return response.choices[0].message.content

    def _parse_json(self, text: str) -> dict:
        match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", text)
        if match:
            text = match.group(1)
        else:
            match = re.search(r"(\{[\s\S]+\})", text)
            if match:
                text = match.group(1)
        return json.loads(text.strip())

    def extract_invoice(self, text: str) -> dict:
        prompt = f"""Извлеки данные из следующего текста счета/накладной и верни их в формате JSON.

ВАЖНО про цены и НДС:
- В таблице может быть только ОДНА колонка цены (например "Цена" или "Сумма") без разделения
  на "с НДС"/"без НДС". В этом случае нужно определить, включён ли НДС в эту цену.
- Если в документе есть фраза вида "В том числе НДС 20%", "В том числе НДС 22%", "Цена с учетом НДС"
  и т.п. — это значит, что указанная в таблице цена УЖЕ ВКЛЮЧАЕТ НДС. В таком случае:
    1) заполни price_with_vat этим значением из таблицы;
    2) вычисли price_no_vat = price_with_vat / (1 + ставка_НДС/100), используя найденную в
       документе ставку НДС (если ставка явно не указана — используй 20%).
  Округляй price_no_vat до 2 знаков после запятой.
- Если в документе явно указано, что цена "без НДС" (НДС не облагается, НДС 0%, "без НДС"),
  то заполни price_no_vat этим значением, а price_with_vat оставь равным price_no_vat (НДС = 0).
- Если в таблице есть отдельные колонки и для цены без НДС, и для цены с НДС — заполни оба поля
  соответствующими значениями напрямую, без пересчёта.
- НИКОГДА не оставляй оба поля price_no_vat и price_with_vat пустыми, если в строке товара
  присутствует хотя бы одна денежная величина (цена за единицу или сумма по позиции, которую
  можно поделить на количество).

Текст документа:
{text[:8000]}

Верни JSON со следующей структурой:
{{
  "invoice_number": "номер счета или null",
  "invoice_date": "дата в формате YYYY-MM-DD или null",
  "supplier": "наименование поставщика или null",
  "inn": "ИНН поставщика или null",
  "total_amount": число или null,
  "vat_amount": число или null,
  "currency": "RUB или другая валюта",
  "confidence": число от 0 до 1,
  "items": [
    {{
      "name": "наименование товара",
      "article": "артикул или null",
      "brand": "бренд/производитель или null",
      "color": "цвет или null",
      "power": "мощность или null",
      "diameter": "диаметр или null",
      "thickness": "толщина или null",
      "material_type": "тип материала или null",
      "unit": "единица измерения",
      "quantity": число или null,
      "price_no_vat": цена без НДС или null,
      "price_with_vat": цена с НДС или null,
      "amount": сумма или null
    }}
  ]
}}
"""
        try:
            response = self._call_openai(prompt)
            return self._parse_json(response)
        except json.JSONDecodeError:
            return self._empty_invoice()
        except Exception as e:
            return {**self._empty_invoice(), "error": str(e)}

    def _empty_invoice(self) -> dict:
        return {
            "invoice_number": None,
            "invoice_date": None,
            "supplier": None,
            "inn": None,
            "total_amount": None,
            "vat_amount": None,
            "currency": "RUB",
            "confidence": 0.0,
            "items": [],
        }

    def extract_materials_for_db(self, text: str) -> list:
        """Extract a list of materials from arbitrary text (price list, catalog, invoice, etc.)"""
        prompt = f"""Извлеки список строительных материалов из текста ниже.
Для каждого материала найди цену максимально внимательно — ищи любую денежную величину
рядом с наименованием: цена за единицу, цена с НДС, цена без НДС, сумма по позиции.
Если есть и сумма, и количество, но нет цены за единицу — вычисли цену за единицу сам (сумма / количество).

Текст:
{text[:8000]}

Верни JSON:
{{
  "materials": [
    {{
      "name": "наименование материала",
      "unit": "единица измерения (шт, м, м2, м3, кг, л, упак и т.д.)",
      "price_no_vat": цена за единицу без НДС числом или null,
      "price_with_vat": цена за единицу с НДС числом или null,
      "quantity": количество числом или null,
      "amount": сумма по позиции числом или null,
      "supplier": "поставщик если указан или null",
      "category": "категория материала (кабели, трубы, крепёж и т.д.) или null"
    }}
  ]
}}

Включай только реальные материалы/товары. Не включай услуги, работы, НДС, итого.
Цену указывай null ТОЛЬКО если её действительно нигде нет в тексте рядом с этой позицией.
"""
        try:
            response = self._call_openai(prompt)
            data = self._parse_json(response)
            materials = data.get("materials", [])
            for mat in materials:
                price = mat.get("price_no_vat")
                if price is None:
                    price = mat.get("price_with_vat")
                if price is None:
                    amount = mat.get("amount")
                    qty = mat.get("quantity")
                    if amount and qty:
                        try:
                            price = float(amount) / float(qty)
                        except (TypeError, ValueError, ZeroDivisionError):
                            price = None
                mat["price"] = price
            return materials
        except Exception:
            return []

    def normalize_name(self, name: str, characteristics: dict) -> str:
        char_str = ", ".join(f"{k}: {v}" for k, v in characteristics.items() if v)
        prompt = f"""Нормализуй наименование строительного материала для базы данных.

Правила (строго соблюдай):
1. Убери название бренда/производителя/поставщика в скобках или после запятой
2. Убери артикул (обычно набор цифр и букв)
3. НЕ сокращай слова — пиши полностью: "наружная" (не "наруж."), "соединительный" (не "соед.")
4. Сохрани все технические характеристики: размер, диаметр, резьбу, марку материала, ГОСТ
5. Первое слово — тип изделия (штуцер, кабель, труба, болт и т.д.)
6. Используй строчные буквы, кроме аббревиатур (ГОСТ, ПВХ, ВВГнг и т.д.)

Наименование: {name}
Характеристики: {char_str}

Верни JSON:
{{"normalized_name": "нормализованное наименование"}}

Примеры:
"Штуцер пневм. наруж. резьба 1/2 ёлочка 6мм (Camozzi)" -> "штуцер пневматический наружная резьба 1/2 ёлочка 6 мм"
"Кабель ВВГнг-LS 3х2,5 ГОСТ (Камкабель) арт.12345" -> "кабель ВВГнг-LS 3х2,5 ГОСТ"
"Труба полипропиленовая d=32мм PN20" -> "труба полипропиленовая диаметр 32 мм PN20"
"""
        try:
            response = self._call_openai(prompt)
            data = self._parse_json(response)
            return data.get("normalized_name", name).strip().lower()
        except Exception:
            return name

    def is_same_material(self, new_name: str, existing_name: str) -> bool:
        """Ask AI whether two material names refer to the same physical item."""
        prompt = f"""Определи, являются ли два наименования одним и тем же строительным материалом.

Наименование 1: {new_name}
Наименование 2: {existing_name}

Считай их одинаковыми ТОЛЬКО если это абсолютно тот же товар с теми же характеристиками.
Разные размеры, диаметры, резьбы, марки — это РАЗНЫЕ товары.

Верни JSON:
{{"same": true/false, "reason": "краткое пояснение"}}
"""
        try:
            response = self._call_openai(prompt)
            data = self._parse_json(response)
            return bool(data.get("same", False))
        except Exception:
            return False

    def find_analogs(self, material_name: str, characteristics: dict,
                     existing_materials: list) -> list:
        if not existing_materials:
            return []

        materials_list = "\n".join(
            f"- {m.get('Нормализованное наименование', '')} (ID: {m.get('ID', '')})"
            for m in existing_materials[:100]
        )
        char_str = ", ".join(f"{k}: {v}" for k, v in characteristics.items() if v)

        prompt = f"""Найди аналоги для следующего материала из списка существующих материалов в базе.

Искомый материал: {material_name}
Характеристики: {char_str}

Список существующих материалов:
{materials_list}

Верни JSON:
{{
  "analogs": [
    {{
      "material_name": "наименование аналога",
      "material_id": "ID аналога",
      "similarity": число от 0 до 1,
      "comment": "пояснение почему это аналог"
    }}
  ]
}}

Включи только реальные аналоги с similarity > 0.5. Если аналогов нет, верни пустой список.
"""
        try:
            response = self._call_openai(prompt)
            data = self._parse_json(response)
            return data.get("analogs", [])
        except Exception:
            return []
