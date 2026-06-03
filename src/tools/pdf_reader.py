import json
from pathlib import Path
from typing import Dict, List, Optional

import fitz  # PyMuPDF
import pytesseract
from PIL import Image


# If tesseract command is not available globally, keep this path.
# Change this only if your install location is different.
DEFAULT_TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


class PDFReaderTool:
    """
    Reads PDF pages.
    First tries normal embedded text extraction.
    If text is empty, renders the page as an image and uses OCR.

    This is required because many clinical PDFs are scanned or handwritten.
    """

    def __init__(self, tesseract_path: Optional[str] = DEFAULT_TESSERACT_PATH):
        if tesseract_path and Path(tesseract_path).exists():
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

    def extract_from_pdf(self, pdf_path: str) -> List[Dict]:
        pdf_path_obj = Path(pdf_path)

        if not pdf_path_obj.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        results = []

        doc = fitz.open(pdf_path)

        for page_index in range(len(doc)):
            page_number = page_index + 1
            page = doc[page_index]

            normal_text = self._extract_text(page)

            if self._is_usable_text(normal_text):
                results.append(
                    {
                        "page": page_number,
                        "status": "success",
                        "extraction_method": "pdf_text",
                        "text": normal_text.strip(),
                        "warnings": [],
                    }
                )
                continue

            # OCR fallback
            ocr_result = self._extract_with_ocr(page)

            results.append(
                {
                    "page": page_number,
                    "status": ocr_result["status"],
                    "extraction_method": "ocr",
                    "text": ocr_result["text"],
                    "warnings": ocr_result["warnings"],
                }
            )

        doc.close()
        return results

    def _extract_text(self, page) -> str:
        try:
            return page.get_text("text") or ""
        except Exception:
            return ""

    def _extract_with_ocr(self, page) -> Dict:
        try:
            # Higher zoom gives better OCR quality.
            zoom = 2
            matrix = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=matrix, alpha=False)

            image = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)

            text = pytesseract.image_to_string(image, lang="eng")

            warnings = []

            if not text.strip():
                warnings.append("OCR returned empty text.")
                return {
                    "status": "failed",
                    "text": "",
                    "warnings": warnings,
                }

            if len(text.strip()) < 30:
                warnings.append("OCR text is very short; page may be unreadable.")

            # Simple handwritten-page warning.
            # OCR can be unreliable on handwritten nursing notes.
            if self._looks_like_low_confidence_ocr(text):
                warnings.append(
                    "OCR may be low confidence. Handwritten or unclear content should be reviewed by clinician."
                )

            return {
                "status": "success",
                "text": text.strip(),
                "warnings": warnings,
            }

        except Exception as exc:
            return {
                "status": "failed",
                "text": "",
                "warnings": [f"OCR failed: {str(exc)}"],
            }

    def _is_usable_text(self, text: str) -> bool:
        if not text:
            return False

        cleaned = text.strip()

        if len(cleaned) < 50:
            return False

        return True

    def _looks_like_low_confidence_ocr(self, text: str) -> bool:
        cleaned = text.strip()

        # Very rough heuristic:
        # if OCR output has many broken short fragments, mark it for review.
        words = cleaned.split()
        if not words:
            return True

        very_short_words = [w for w in words if len(w) <= 2]
        short_ratio = len(very_short_words) / max(len(words), 1)

        return short_ratio > 0.45


def save_extracted_pages(pages: List[Dict], output_path: str) -> None:
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with output_path_obj.open("w", encoding="utf-8") as f:
        json.dump(pages, f, indent=2, ensure_ascii=False)