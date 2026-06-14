import os
from typing import Optional

import pdfplumber
import pytesseract
from PIL import Image
import openpyxl


def parse_pdf(file_path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text += page_text + "\n"
    except Exception:
        pass

    if not text.strip():
        # Fallback to OCR
        try:
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    img = page.to_image(resolution=200).original
                    ocr_text = pytesseract.image_to_string(img, lang="rus+eng")
                    text += ocr_text + "\n"
        except Exception:
            pass

    return text.strip()


def parse_excel(file_path: str) -> str:
    lines = []
    try:
        wb = openpyxl.load_workbook(file_path, data_only=True)
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            lines.append(f"=== Лист: {sheet_name} ===")
            for row in ws.iter_rows(values_only=True):
                row_values = [str(cell) if cell is not None else "" for cell in row]
                if any(v.strip() for v in row_values):
                    lines.append("\t".join(row_values))
    except Exception as e:
        lines.append(f"Ошибка чтения Excel: {e}")
    return "\n".join(lines)


def parse_word(file_path: str) -> str:
    try:
        from docx import Document
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        # Also extract tables
        for table in doc.tables:
            for row in table.rows:
                row_text = "\t".join(cell.text.strip() for cell in row.cells)
                paragraphs.append(row_text)
        return "\n".join(paragraphs)
    except Exception as e:
        return f"Ошибка чтения Word: {e}"


def parse_image(file_path: str) -> str:
    try:
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img, lang="rus+eng")
        return text.strip()
    except Exception as e:
        return f"Ошибка распознавания изображения: {e}"


def detect_and_parse(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return parse_pdf(file_path)
    elif ext in (".xlsx", ".xls"):
        return parse_excel(file_path)
    elif ext in (".docx", ".doc"):
        return parse_word(file_path)
    elif ext in (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif"):
        return parse_image(file_path)
    else:
        # Try as text
        try:
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        except Exception:
            return ""
