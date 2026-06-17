import os
from typing import Optional

import pdfplumber
import pytesseract
from PIL import Image
import openpyxl


MAX_PDF_PAGES = 5  # invoices are rarely longer; later pages are usually T&C


def parse_pdf(file_path: str) -> str:
    text = ""
    try:
        with pdfplumber.open(file_path) as pdf:
            pages = pdf.pages[:MAX_PDF_PAGES]
            for page in pages:
                tables = page.extract_tables()
                if tables:
                    for table in tables:
                        for row in table:
                            row_text = "\t".join(
                                (cell or "").strip().replace("\n", " ") for cell in row
                            )
                            if row_text.strip():
                                text += row_text + "\n"
                else:
                    page_text = page.extract_text()
                    if page_text:
                        text += page_text + "\n"
    except Exception:
        pass

    if not text.strip():
        # Fallback to OCR. psm 6 with preserved interword spacing keeps table
        # columns aligned. Use 150 DPI instead of 300 — printed invoice text
        # is fully readable at 150 DPI and renders 4x faster, preventing large
        # scanned PDFs from stalling batch processing for hours.
        try:
            with pdfplumber.open(file_path) as pdf:
                pages = pdf.pages[:MAX_PDF_PAGES]
                for page in pages:
                    img = page.to_image(resolution=150).original
                    ocr_text = pytesseract.image_to_string(
                        img, lang="rus+eng",
                        config="--psm 6 -c preserve_interword_spaces=1"
                    )
                    text += ocr_text + "\n"
        except Exception:
            pass

    return text.strip()


def parse_excel(file_path: str) -> str:
    ext = os.path.splitext(file_path)[1].lower()
    lines = []
    if ext == ".xls":
        try:
            import xlrd
            wb = xlrd.open_workbook(file_path)
            for sheet_name in wb.sheet_names():
                ws = wb.sheet_by_name(sheet_name)
                lines.append(f"=== Лист: {sheet_name} ===")
                for row_idx in range(ws.nrows):
                    row_values = [str(ws.cell_value(row_idx, c)) if ws.cell_value(row_idx, c) != "" else ""
                                  for c in range(ws.ncols)]
                    if any(v.strip() for v in row_values):
                        lines.append("\t".join(row_values))
        except Exception as e:
            lines.append(f"Ошибка чтения XLS: {e}")
    else:
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
        text = pytesseract.image_to_string(
            img, lang="rus+eng",
            config="--psm 6 -c preserve_interword_spaces=1"
        )
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
