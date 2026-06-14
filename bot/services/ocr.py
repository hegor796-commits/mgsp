import os
from typing import Optional


def parse_pdf(file_path: str) -> str:
    """Extract text from PDF using pdfplumber; fallback to pytesseract OCR."""
    try:
        import pdfplumber
        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text:
                    text_parts.append(page_text)
        text = "\n".join(text_parts).strip()
        if text:
            return text
    except Exception:
        pass

    # Fallback: OCR with pytesseract
    try:
        import pdfplumber
        from PIL import Image
        import pytesseract
        import io

        text_parts = []
        with pdfplumber.open(file_path) as pdf:
            for i, page in enumerate(pdf.pages):
                try:
                    img = page.to_image(resolution=200).original
                    page_text = pytesseract.image_to_string(img, lang="rus+eng")
                    if page_text.strip():
                        text_parts.append(page_text)
                except Exception:
                    continue
        return "\n".join(text_parts).strip()
    except Exception as e:
        return f"Ошибка обработки PDF: {e}"


def parse_excel(file_path: str) -> str:
    """Read all sheets from Excel and return text representation."""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(file_path, data_only=True)
        text_parts = []
        for sheet_name in wb.sheetnames:
            ws = wb[sheet_name]
            text_parts.append(f"=== Лист: {sheet_name} ===")
            for row in ws.iter_rows(values_only=True):
                row_values = [str(v) if v is not None else "" for v in row]
                if any(v.strip() for v in row_values):
                    text_parts.append("\t".join(row_values))
        return "\n".join(text_parts)
    except Exception as e:
        return f"Ошибка обработки Excel: {e}"


def parse_word(file_path: str) -> str:
    """Extract text from Word document."""
    try:
        from docx import Document
        doc = Document(file_path)
        text_parts = []
        for para in doc.paragraphs:
            if para.text.strip():
                text_parts.append(para.text)
        for table in doc.tables:
            for row in table.rows:
                row_text = "\t".join(cell.text.strip() for cell in row.cells)
                if row_text.strip():
                    text_parts.append(row_text)
        return "\n".join(text_parts)
    except Exception as e:
        return f"Ошибка обработки Word: {e}"


def parse_image(file_path: str) -> str:
    """Extract text from image using pytesseract."""
    try:
        from PIL import Image
        import pytesseract
        img = Image.open(file_path)
        text = pytesseract.image_to_string(img, lang="rus+eng")
        return text.strip()
    except Exception as e:
        return f"Ошибка обработки изображения: {e}"


def detect_and_parse(file_path: str) -> str:
    """Detect file type by extension and call appropriate parser."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".pdf":
        return parse_pdf(file_path)
    elif ext in (".xlsx", ".xls", ".ods"):
        return parse_excel(file_path)
    elif ext in (".docx", ".doc"):
        return parse_word(file_path)
    elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".gif", ".webp"):
        return parse_image(file_path)
    else:
        return f"Неподдерживаемый формат файла: {ext}"
