import os
from datetime import date, datetime
from typing import Optional
import openpyxl
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill


class ExcelDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def init_db(self):
        """Create xlsx with all required sheets if not exists."""
        if os.path.exists(self.db_path):
            return

        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        wb = Workbook()

        # Remove default sheet
        default_sheet = wb.active
        wb.remove(default_sheet)

        # Материалы
        ws = wb.create_sheet("Материалы")
        ws.append([
            "ID", "Нормализованное наименование", "Единица измерения",
            "Минимальная цена без НДС", "Поставщик минимальной цены",
            "Дата последнего обновления", "Категория", "Активен"
        ])
        self._bold_header(ws)

        # История цен
        ws = wb.create_sheet("История цен")
        ws.append([
            "ID", "ID материала", "Цена без НДС", "Цена с НДС",
            "Поставщик", "Номер счета", "Дата счета", "Дата добавления", "Пользователь"
        ])
        self._bold_header(ws)

        # Аналоги
        ws = wb.create_sheet("Аналоги")
        ws.append(["ID", "ID материала", "ID аналога", "Коэффициент замены", "Примечание"])
        self._bold_header(ws)

        # Поставщики
        ws = wb.create_sheet("Поставщики")
        ws.append(["ID", "Наименование", "ИНН", "Контакт", "Email", "Телефон", "Рейтинг"])
        self._bold_header(ws)

        # Пользователи
        ws = wb.create_sheet("Пользователи")
        ws.append(["Telegram ID", "ФИО", "Роль", "Email", "Активен", "Дата добавления"])
        self._bold_header(ws)
        ws.append([0, "Администратор", "admin", "", "Да", str(date.today())])

        # Проверки счетов
        ws = wb.create_sheet("Проверки счетов")
        ws.append([
            "ID", "Номер счета", "Дата счета", "Поставщик", "Сумма",
            "НДС", "Валюта", "Дата проверки", "Пользователь", "Статус", "Потенциальная экономия"
        ])
        self._bold_header(ws)

        # Журнал
        ws = wb.create_sheet("Журнал")
        ws.append(["ID", "Дата", "Пользователь (Telegram ID)", "Действие", "Детали"])
        self._bold_header(ws)

        wb.save(self.db_path)

    def _bold_header(self, ws):
        for cell in ws[1]:
            cell.font = Font(bold=True)

    def _load_wb(self):
        return load_workbook(self.db_path)

    def _save_wb(self, wb):
        wb.save(self.db_path)

    def _sheet_to_dicts(self, ws) -> list:
        headers = [cell.value for cell in ws[1]]
        result = []
        for row in ws.iter_rows(min_row=2, values_only=True):
            if all(v is None for v in row):
                continue
            result.append(dict(zip(headers, row)))
        return result

    def _next_id(self, ws) -> int:
        max_id = 0
        for row in ws.iter_rows(min_row=2, min_col=1, max_col=1, values_only=True):
            val = row[0]
            if isinstance(val, (int, float)) and val > max_id:
                max_id = int(val)
        return max_id + 1

    def get_user(self, telegram_id) -> Optional[dict]:
        try:
            wb = self._load_wb()
            ws = wb["Пользователи"]
            headers = [cell.value for cell in ws[1]]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[0] is not None and str(row[0]) == str(telegram_id):
                    return dict(zip(headers, row))
            return None
        except Exception:
            return None

    def get_material(self, normalized_name: str) -> Optional[dict]:
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            headers = [cell.value for cell in ws[1]]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[1] and str(row[1]).lower() == normalized_name.lower():
                    return dict(zip(headers, row))
            return None
        except Exception:
            return None

    def search_materials(self, query: str) -> list:
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            headers = [cell.value for cell in ws[1]]
            result = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[1] and query.lower() in str(row[1]).lower():
                    result.append(dict(zip(headers, row)))
            return result
        except Exception:
            return []

    def get_min_price(self, material_id) -> Optional[float]:
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if str(row[0]) == str(material_id):
                    val = row[3]
                    return float(val) if val is not None else None
            return None
        except Exception:
            return None

    def get_analogs(self, material_id) -> list:
        try:
            wb = self._load_wb()
            ws = wb["Аналоги"]
            headers = [cell.value for cell in ws[1]]
            result = []
            for row in ws.iter_rows(min_row=2, values_only=True):
                if str(row[1]) == str(material_id):
                    result.append(dict(zip(headers, row)))
            return result
        except Exception:
            return []

    def add_material(self, data: dict) -> str:
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            new_id = self._next_id(ws)
            ws.append([
                new_id,
                data.get("Нормализованное наименование", ""),
                data.get("Единица измерения", ""),
                data.get("Минимальная цена без НДС", None),
                data.get("Поставщик минимальной цены", ""),
                data.get("Дата последнего обновления", str(date.today())),
                data.get("Категория", ""),
                data.get("Активен", "Да"),
            ])
            self._save_wb(wb)
            return str(new_id)
        except Exception as e:
            raise RuntimeError(f"Ошибка добавления материала: {e}")

    def update_min_price(self, material_id, price: float, supplier: str,
                          invoice_num: str, invoice_date: str, user):
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            for row in ws.iter_rows(min_row=2):
                if str(row[0].value) == str(material_id):
                    current = row[3].value
                    if current is None or float(price) < float(current):
                        row[3].value = price
                        row[4].value = supplier
                        row[5].value = str(date.today())
                        break
            self._save_wb(wb)
            self.add_price_history({
                "ID материала": material_id,
                "Цена без НДС": price,
                "Поставщик": supplier,
                "Номер счета": invoice_num,
                "Дата счета": invoice_date,
                "Пользователь": str(user),
            })
        except Exception as e:
            raise RuntimeError(f"Ошибка обновления цены: {e}")

    def add_price_history(self, data: dict):
        try:
            wb = self._load_wb()
            ws = wb["История цен"]
            new_id = self._next_id(ws)
            ws.append([
                new_id,
                data.get("ID материала", ""),
                data.get("Цена без НДС", None),
                data.get("Цена с НДС", None),
                data.get("Поставщик", ""),
                data.get("Номер счета", ""),
                data.get("Дата счета", ""),
                str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                data.get("Пользователь", ""),
            ])
            self._save_wb(wb)
        except Exception as e:
            raise RuntimeError(f"Ошибка добавления истории цен: {e}")

    def add_invoice_check(self, data: dict):
        try:
            wb = self._load_wb()
            ws = wb["Проверки счетов"]
            new_id = self._next_id(ws)
            ws.append([
                new_id,
                data.get("Номер счета", ""),
                data.get("Дата счета", ""),
                data.get("Поставщик", ""),
                data.get("Сумма", None),
                data.get("НДС", None),
                data.get("Валюта", "RUB"),
                str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                data.get("Пользователь", ""),
                data.get("Статус", ""),
                data.get("Потенциальная экономия", None),
            ])
            self._save_wb(wb)
        except Exception as e:
            raise RuntimeError(f"Ошибка сохранения проверки счета: {e}")

    def get_all_materials(self) -> list:
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            return self._sheet_to_dicts(ws)
        except Exception:
            return []

    def log_action(self, telegram_id, action: str, details: str = ""):
        try:
            wb = self._load_wb()
            ws = wb["Журнал"]
            new_id = self._next_id(ws)
            ws.append([
                new_id,
                str(datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
                str(telegram_id),
                action,
                details,
            ])
            self._save_wb(wb)
        except Exception:
            pass

    def add_user(self, telegram_id, name: str, role: str, email: str = ""):
        try:
            wb = self._load_wb()
            ws = wb["Пользователи"]
            ws.append([
                telegram_id,
                name,
                role,
                email,
                "Да",
                str(date.today()),
            ])
            self._save_wb(wb)
        except Exception as e:
            raise RuntimeError(f"Ошибка добавления пользователя: {e}")
