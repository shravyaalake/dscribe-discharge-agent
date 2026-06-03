import json
from pathlib import Path
from typing import Dict, List


class DocumentClassifierTool:
    """
    Classifies OCR-extracted PDF pages into clinical document/page types.

    Rule-based classification is used for explainability.
    The agent can use page types to prioritize reliable clinical sources.
    """

    def classify_pages(self, pages: List[Dict]) -> List[Dict]:
        classified_pages = []

        for page in pages:
            text = page.get("text", "") or ""
            page_type = self._classify_text(text)

            classified_page = {
                **page,
                "page_type": page_type,
                "classification_reason": self._classification_reason(text, page_type),
                "usable_for_summary": self._is_usable_for_summary(page, page_type),
            }

            classified_pages.append(classified_page)

        return classified_pages

    def _classify_text(self, text: str) -> str:
        normalized = text.lower()

        # First detect source-document forms that can contain words like "history"
        # but are not the final discharge summary.
        if "admission record" in normalized or "case record" in normalized:
            return "admission_record"

        if "consultation sheet" in normalized:
            return "consultation_sheet"

        # Strong discharge summary markers.
        # Be conservative: "history" alone is not enough because admission records also contain history.
        if "condition at discharge" in normalized:
            return "discharge_summary"

        if "advice on discharge" in normalized:
            return "discharge_summary"

        if "follow-up instructions" in normalized:
            return "discharge_summary"

        if "diagnosis:" in normalized and "course in the hospital" in normalized:
            return "discharge_summary"

        if "condition at discharge" in normalized:
            return "discharge_summary"

        if "advice on discharge" in normalized:
            return "discharge_summary"

        if "follow-up instructions" in normalized:
            return "discharge_summary"

        if "er observation chart" in normalized:
            return "er_observation"

        if "discharge check list" in normalized:
            return "discharge_checklist"

        if "drug chart" in normalized:
            return "drug_chart"

        if "nursing documentation" in normalized:
            return "nursing_note"

        if "nurses notes" in normalized:
            return "nursing_note"

        if "bed sores" in normalized:
            return "bed_sore_chart"

        if "procedure chart" in normalized:
            return "procedure_chart"

        if "monitoring chart" in normalized:
            return "monitoring_chart"

        if "intake/output chart" in normalized:
            return "intake_output_chart"

        if "usg abdomen" in normalized or ("abdomen" in normalized and "pelvis" in normalized):
            return "radiology_report"

        if "clinical pathology report" in normalized:
            return "investigation"

        if "biochemistry report" in normalized:
            return "investigation"

        if "haematology report" in normalized:
            return "investigation"

        if "urine routine" in normalized:
            return "investigation"

        if "investigation checklist" in normalized:
            return "investigation_checklist"

        if "investigations" in normalized:
            return "investigation"

        return "unknown"

    def _classification_reason(self, text: str, page_type: str) -> str:
        if page_type == "discharge_summary":
            return "Detected discharge-summary markers such as diagnosis, history, hospital course, condition at discharge, advice, or follow-up instructions."

        if page_type == "investigation":
            return "Detected laboratory or investigation report markers."

        if page_type == "radiology_report":
            return "Detected USG abdomen/pelvis or radiology-style report markers."

        if page_type == "nursing_note":
            return "Detected nursing documentation or nurses notes markers."

        if page_type == "drug_chart":
            return "Detected drug chart markers."

        if page_type == "admission_record":
            return "Detected case record/admission record markers."

        if page_type == "consultation_sheet":
            return "Detected consultation sheet markers."

        if page_type == "unknown":
            if not text.strip():
                return "No readable text available for classification."
            return "No strong document-type marker found."

        return f"Detected markers matching {page_type}."

    def _is_usable_for_summary(self, page: Dict, page_type: str) -> bool:
        if page.get("status") != "success":
            return False

        warnings = page.get("warnings", [])

        has_low_confidence_warning = any(
            "low confidence" in warning.lower() or "unreadable" in warning.lower()
            for warning in warnings
        )

        if has_low_confidence_warning:
            return False

        strong_types = {
            "discharge_summary",
            "investigation",
            "radiology_report",
            "admission_record",
            "drug_chart",
            "discharge_checklist",
        }

        return page_type in strong_types


def save_document_inventory(classified_pages: List[Dict], output_path: str) -> None:
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with output_path_obj.open("w", encoding="utf-8") as f:
        json.dump(classified_pages, f, indent=2, ensure_ascii=False)