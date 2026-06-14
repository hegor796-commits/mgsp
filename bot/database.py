import os
from datetime import date, datetime
from typing import Optional
from openpyxl import Workbook, load_workbook


MATERIAL_HEADERS = [
    "ID", "Нормализованное наименование", "Единица измерения",
    "Минимальная цена без НДС", "Поставщик минимальной цены",
    "Дата последнего обновления", "Категория", "Активен"
]

USER_HEADERS = [
    "Telegram ID", "ФИО", "Роль", "Email", "Активен", "Дата добавления"
]

ANALOG_HEADERS = [
    "ID", "ID материала", "ID аналога", "Коэффициент замены", "Примечание"
]


def _row_to_dict(headers: list, row: tuple) -> dict:
    return dict(zip(headers, row))


class ExcelDatabase:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def init_db(self):
        if self.db_path:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        if os.path.exists(self.db_path):
            return

        wb = Workbook()
        wb.remove(wb.active)

        ws = wb.create_sheet("Материалы")
        ws.append(MATERIAL_HEADERS)

        ws2 = wb.create_sheet("История цен")
        ws2.append(["ID", "ID материала", "Цена без НДС", "Цена с НДС",
                    "Поставщик", "Номер счета", "Дата счета", "Дата добавления", "Пользователь"])

        ws3 = wb.create_sheet("Аналоги")
        ws3.append(ANALOG_HEADERS)

        ws4 = wb.create_sheet("Поставщики")
        ws4.append(["ID", "Наименование", "ИНН", "Контакт", "Email", "Телефон", "Рейтинг"])

        ws5 = wb.create_sheet("Пользователи")
        ws5.append(USER_HEADERS)
        ws5.append([0, "Администратор", "admin", "", "Да", date.today().strftime("%Y-%m-%d")])

        ws6 = wb.create_sheet("Проверки счетов")
        ws6.append(["ID", "Номер счета", "Дата счета", "Поставщик", "Сумма", "НДС",
                    "Валюта", "Дата проверки", "Пользователь", "Статус", "Потенциальная экономия"])

        ws7 = wb.create_sheet("Журнал")
        ws7.append(["ID", "Дата", "Пользователь (Telegram ID)", "Действие", "Детали"])

        wb.save(self.db_path)

    def _load_wb(self):
        return load_workbook(self.db_path)

    def _save_wb(self, wb):
        wb.save(self.db_path)

    def _next_id(self, ws) -> int:
        max_id = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0] is not None:
                try:
                    max_id = max(max_id, int(row[0]))
                except (ValueError, TypeError):
                    pass
        return max_id + 1

    def get_user(self, telegram_id) -> Optional[dict]:
        try:
            wb = self._load_wb()
            ws = wb["Пользователи"]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[0] is not None and str(row[0]) == str(telegram_id):
                    return _row_to_dict(USER_HEADERS, row)
            return None
        except Exception:
            return None

    def add_user(self, telegram_id, name: str, role: str, email: str = ""):
        wb = self._load_wb()
        ws = wb["Пользователи"]
        ws.append([telegram_id, name, role, email, "Да", date.today().strftime("%Y-%m-%d")])
        self._save_wb(wb)

    def get_material(self, normalized_name: str) -> Optional[dict]:
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[1] and str(row[1]).lower() == normalized_name.lower():
                    return _row_to_dict(MATERIAL_HEADERS, row)
            return None
        except Exception:
            return None

    def search_materials(self, query: str) -> list:
        results = []
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            q = query.lower()
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[1] and q in str(row[1]).lower():
                    results.append(_row_to_dict(MATERIAL_HEADERS, row))
        except Exception:
            pass
        return results

    def get_all_materials(self) -> list:
        results = []
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if row[0] is not None:
                    results.append(_row_to_dict(MATERIAL_HEADERS, row))
        except Exception:
            pass
        return results

    def get_min_price(self, material_id) -> Optional[float]:
        try:
            wb = self._load_wb()
            ws = wb["Материалы"]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if str(row[0]) == str(material_id):
                    return float(row[3]) if row[3] is not None else None
            return None
        except Exception:
            return None

    def get_analogs(self, material_id) -> list:
        results = []
        try:
            wb = self._load_wb()
            ws = wb["Аналоги"]
            for row in ws.iter_rows(min_row=2, values_only=True):
                if str(row[1]) == str(material_id):
                    results.append(_row_to_dict(ANALOG_HEADERS, row))
        except Exception:
            pass
        return results

    def add_material(self, data: dict) -> str:
        wb = self._load_wb()
        ws = wb["Материалы"]
        new_id = self._next_id(ws)
        ws.append([
            new_id,
            data.get("Нормализованное наименование", ""),
            data.get("Единица измерения", ""),
            data.get("Минимальная цена без НДС"),
            data.get("Поставщик минимальной цены", ""),
            data.get("Дата последнего обновления", date.today().strftime("%Y-%m-%d")),
            data.get("Категория", ""),
            data.get("Активен", "Да"),
        ])
        self._save_wb(wb)
        return str(new_id)

    def update_min_price(self, material_id, price: float, supplier: str,
                         invoice_num: str, invoice_date: str, user):
        wb = self._load_wb()
        ws = wb["Материалы"]
        for row in ws.iter_rows(min_row=2):
            if str(row[0].value) == str(material_id):
                row[3].value = price
                row[4].value = supplier
                row[5].value = date.today().strftime("%Y-%m-%d")
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

    def add_price_history(self, data: dict):
        wb = self._load_wb()
        ws = wb["История цен"]
        new_id = self._next_id(ws)
        ws.append([
            new_id,
            data.get("ID материала"),
            data.get("Цена без НДС"),
            data.get("Цена с НДС"),
            data.get("Поставщик", ""),
            data.get("Номер счета", ""),
            data.get("Дата счета", ""),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get("Пользователь", ""),
        ])
        self._save_wb(wb)

    def add_invoice_check(self, data: dict):
        wb = self._load_wb()
        ws = wb["Проверки счетов"]
        new_id = self._next_id(ws)
        ws.append([
            new_id,
            data.get("Номер счета", ""),
            data.get("Дата счета", ""),
            data.get("Поставщик", ""),
            data.get("Сумма"),
            data.get("НДС"),
            data.get("Валюта", "RUB"),
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            data.get("Пользователь", ""),
            data.get("Статус", ""),
            data.get("Потенциальная экономия"),
        ])
        self._save_wb(wb)

    def log_action(self, telegram_id, action: str, details: str = ""):
        try:
            wb = self._load_wb()
            ws = wb["Журнал"]
            new_id = self._next_id(ws)
            ws.append([
                new_id,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                str(telegram_id),
                action,
                details,
            ])
            self._save_wb(wb)
        except Exception:
            pass
