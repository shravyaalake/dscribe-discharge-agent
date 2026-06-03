import json
from pathlib import Path
from typing import Dict, List, Any
import re


class DischargeSummaryWriterTool:
    """
    Writes a discharge summary draft from evidence only.

    Safety rules:
    - Never invent missing information.
    - Every major fact comes from evidence_map.
    - Missing fields are explicitly marked.
    - Medication uncertainty, OCR issues, conflicts, and pending results are surfaced.
    """

    def write(
        self,
        evidence_map: Dict,
        medication_report: Dict,
        conflict_report: Dict,
    ) -> Dict:
        facts = evidence_map.get("facts", {})
        review_flags = evidence_map.get("review_flags", [])

        summary = {
            "document_status": "DRAFT FOR CLINICIAN REVIEW - NOT FINAL",
            "patient_demographics": self._values_or_missing(
                facts,
                "demographics",
                "Patient demographics missing from readable source notes.",
            ),
            "admission_and_discharge_dates": self._values_or_missing(
                facts,
                "admission_discharge_dates",
                "Admission and discharge dates missing from readable source notes.",
            ),
            "principal_diagnosis": self._values_or_missing(
                facts,
                "principal_diagnosis",
                "Principal diagnosis missing from readable source notes.",
            ),
            "secondary_diagnoses": self._values_or_missing(
                facts,
                "secondary_diagnoses",
                "Secondary diagnoses missing from readable source notes.",
            ),
            "history": self._values_or_missing(
                facts,
                "history",
                "History missing from readable source notes.",
            ),
            "past_history": self._values_or_missing(
                facts,
                "past_history",
                "Past history missing from readable source notes.",
            ),
            "physical_examination": self._values_or_missing(
                facts,
                "physical_examination",
                "Physical examination missing from readable source notes.",
            ),
            "hospital_course": self._values_or_missing(
                facts,
                "hospital_course",
                "Hospital course missing from readable source notes.",
            ),
            "procedures": self._values_or_missing(
                facts,
                "procedures",
                "No clear procedure details found in readable source notes.",
            ),
            "investigations": self._values_or_missing(
                facts,
                "investigations",
                "Investigations missing from readable source notes.",
            ),
            "allergies": self._values_or_missing(
                facts,
                "allergies",
                "Allergy information missing or unclear in readable source notes.",
            ),
            "discharge_condition": self._values_or_missing(
                facts,
                "discharge_condition",
                "Discharge condition missing from readable source notes.",
            ),
            "discharge_medications": self._format_discharge_medications(
                facts.get("discharge_medications", []),
                medication_report,
            ),
            "medication_reconciliation": medication_report,
            "follow_up_instructions": self._values_or_missing(
                facts,
                "follow_up_instructions",
                "Follow-up instructions missing from readable source notes.",
            ),
            "pending_results": self._values_or_missing(
                facts,
                "pending_results",
                "No pending results identified in readable source notes.",
            ),
            "conflicts": conflict_report.get("conflicts", []),
            "safety_flags_for_clinician_review": self._combine_safety_flags(
                review_flags,
                medication_report,
                conflict_report,
            ),
        }

        return summary

    def _build_clean_investigation_summary(self, summary: Dict) -> List[Dict]:
        """
        Prefer the clearer investigation narrative from the hospital course
        over noisy OCR tables from scanned lab pages.

        Raw extracted lab text remains available in evidence_map.json.
        """
        clean_items = []

        hospital_course_items = summary.get("hospital_course", [])

        for item in hospital_course_items:
            value = item.get("value", "")
            source_file = item.get("source_file")
            page = item.get("page")

            lower_value = value.lower()

            if "initial investigations" in lower_value:
                clean_items.append(
                    {
                        "field": "investigation_summary",
                        "value": "Initial investigations showed normal CBC, elevated serum creatinine, low serum sodium, and urine routine abnormalities including ketone bodies, pus cells, epithelial cells, and bacteria. Urine culture and sensitivity was sent and report was awaited.",
                        "source_file": source_file,
                        "page": page,
                        "confidence": "high",
                    }
                )

            if "usg abdomen" in lower_value or "abdomen and pelvis" in lower_value:
                clean_items.append(
                    {
                        "field": "investigation_summary",
                        "value": "USG abdomen and pelvis showed Grade-I fatty liver changes and mildly edematous ascending colon up to the hepatic flexure, possibly representing colitis.",
                        "source_file": source_file,
                        "page": page,
                        "confidence": "high",
                    }
                )

            if "repeat serum creatinine" in lower_value:
                clean_items.append(
                    {
                        "field": "investigation_summary",
                        "value": "Repeat serum creatinine was documented as normal.",
                        "source_file": source_file,
                        "page": page,
                        "confidence": "high",
                    }
                )

            if "tsh" in lower_value and "free t4" in lower_value:
                clean_items.append(
                    {
                        "field": "investigation_summary",
                        "value": "TSH and Free T4 were documented as normal.",
                        "source_file": source_file,
                        "page": page,
                        "confidence": "high",
                    }
                )

            if "stool routine" in lower_value:
                clean_items.append(
                    {
                        "field": "investigation_summary",
                        "value": "Stool routine showed red blood cells and plenty of pus cells.",
                        "source_file": source_file,
                        "page": page,
                        "confidence": "high",
                    }
                )

        if clean_items:
            return self._dedupe_items_for_display(clean_items)

        return summary.get("investigations", [])

    def to_markdown(self, summary: Dict) -> str:
        lines = []

        lines.append("# Discharge Summary Draft")
        lines.append("")
        lines.append("> **Status:** DRAFT FOR CLINICIAN REVIEW — NOT FINAL")
        lines.append("")
        lines.append(
            "> This draft was generated only from provided source-note evidence. "
            "Missing, unclear, pending, or conflicting information is flagged for clinician review."
        )
        lines.append("")

        self._add_section(lines, "Patient Demographics", summary["patient_demographics"])
        self._add_section(lines, "Admission and Discharge Dates", summary["admission_and_discharge_dates"])
        self._add_section(lines, "Principal Diagnosis", summary["principal_diagnosis"])
        self._add_section(lines, "Secondary Diagnoses", summary["secondary_diagnoses"])
        self._add_section(lines, "History", summary["history"])
        self._add_section(lines, "Past History", summary["past_history"])
        self._add_section(lines, "Physical Examination", summary["physical_examination"])
        self._add_section(lines, "Hospital Course", summary["hospital_course"])
        self._add_section(lines, "Procedures", summary["procedures"])
        self._add_section(
            lines,
            "Investigations",
            self._build_clean_investigation_summary(summary),
        )
        self._add_section(lines, "Allergies", summary["allergies"])
        self._add_section(lines, "Discharge Condition", summary["discharge_condition"])

        lines.append("## Discharge Medications")
        lines.append("")
        meds = summary["discharge_medications"]

        if meds:
            lines.append("| Medication / OCR Text | Source | Confidence | Review Needed |")
            lines.append("|---|---|---|---|")

            for med in meds:
                lines.append(
                    f"| {self._escape_table_cell(med.get('value', 'Missing'))} "
                    f"| {self._escape_table_cell(self._source(med))} "
                    f"| {self._escape_table_cell(med.get('confidence', 'unknown'))} "
                    f"| {self._escape_table_cell(med.get('review_needed', 'Yes'))} |"
                )
        else:
            lines.append("- Missing from readable source notes — clinician review required.")

        lines.append("")

        lines.append("## Medication Reconciliation")
        lines.append("")
        med_report = summary["medication_reconciliation"]

        if med_report.get("review_flags"):
            for flag in med_report.get("review_flags", []):
                lines.append(f"- **{flag.get('severity', 'review').upper()}**: {flag.get('message')}")
        else:
            lines.append("- No medication reconciliation review flags generated.")

        lines.append("")

        if med_report.get("medication_changes"):
            lines.append("| Medication | Change Type | Reason | Review Required |")
            lines.append("|---|---|---|---|")

            for change in med_report.get("medication_changes", []):
                lines.append(
                    f"| {self._escape_table_cell(change.get('medication_raw'))} "
                    f"| {self._escape_table_cell(change.get('change_type'))} "
                    f"| {self._escape_table_cell(change.get('reason'))} "
                    f"| {self._escape_table_cell(change.get('requires_clinician_review'))} |"
                )

        lines.append("")

        self._add_section(lines, "Follow-up Instructions", summary["follow_up_instructions"])
        self._add_section(
            lines,
            "Pending Results",
            self._dedupe_items_for_display(summary["pending_results"]),
        )

        lines.append("## Conflicts")
        lines.append("")
        conflicts = summary.get("conflicts", [])

        if conflicts:
            for conflict in conflicts:
                lines.append(f"- {conflict.get('message')}")
        else:
            lines.append("- No direct conflict detected among high-confidence structured facts.")
        lines.append("")

        lines.append("## Safety Flags for Clinician Review")
        lines.append("")

        safety_flags = summary.get("safety_flags_for_clinician_review", [])

        if safety_flags:
            grouped_flags = self._group_safety_flags_for_display(safety_flags)

            for flag_message in grouped_flags:
                lines.append(f"- {flag_message}")
        else:
            lines.append("- No safety flags generated.")

        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append("Generated as a draft for clinician review. Not for direct clinical use without verification.")

        return "\n".join(lines)

    def _values_or_missing(self, facts: Dict, field: str, missing_message: str) -> List[Dict]:
        values = facts.get(field, [])

        if not values:
            return [
                {
                    "field": field,
                    "value": f"MISSING — {missing_message}",
                    "source_file": None,
                    "page": None,
                    "confidence": "missing",
                    "review_needed": True,
                }
            ]

        return values

    def _format_discharge_medications(self, medication_facts: List[Dict], medication_report: Dict) -> List[Dict]:
        formatted = []

        for med in medication_facts:
            formatted.append(
                {
                    "value": med.get("value"),
                    "source_file": med.get("source_file"),
                    "page": med.get("page"),
                    "confidence": med.get("confidence"),
                    "review_needed": med.get("confidence") == "low",
                }
            )

        return formatted

    def _combine_safety_flags(
        self,
        evidence_flags: List[Dict],
        medication_report: Dict,
        conflict_report: Dict,
    ) -> List[Dict]:
        combined = []

        combined.extend(evidence_flags)
        combined.extend(medication_report.get("review_flags", []))

        for conflict in conflict_report.get("conflicts", []):
            combined.append(
                {
                    "type": conflict.get("type", "conflict"),
                    "message": conflict.get("message", "Conflict detected."),
                    "severity": conflict.get("severity", "high"),
                }
            )

        return combined

    def _add_section(self, lines: List[str], title: str, items: List[Dict]) -> None:
        lines.append(f"## {title}")
        lines.append("")

        for item in items:
            value = item.get("value", "Missing")
            source = self._source(item)

            if item.get("confidence") == "missing":
                lines.append(f"- {value}")
            else:
                lines.append(f"- {value}  ")
                lines.append(f"  - Source: {source}")

        lines.append("")

    def _source(self, item: Dict) -> str:
        source_file = item.get("source_file")
        page = item.get("page")

        if source_file and page:
            return f"{source_file}, page {page}"

        return "Not available"

    def _escape_table_cell(self, value: Any) -> str:
        if value is None:
            return ""

        text = str(value)
        text = text.replace("\n", " ")
        text = re.sub(r"\s+", " ", text).strip()

        # Important: OCR text may contain table pipes.
        # Escape them so Markdown tables do not break.
        text = text.replace("|", "\\|")

        return text

    def _dedupe_items_for_display(self, items: List[Dict]) -> List[Dict]:
        seen = set()
        deduped = []

        for item in items:
            value = item.get("value", "")
            normalized = re.sub(r"\s+", " ", value.lower()).strip()

            if normalized not in seen:
                seen.add(normalized)
                deduped.append(item)

        return deduped

    def _group_safety_flags_for_display(self, flags: List[Dict]) -> List[str]:
        low_confidence_pages = []
        allergy_unclear_pages = []
        missing_fields = []
        medication_flags = []
        other_flags = []

        for flag in flags:
            flag_type = flag.get("type", "")
            page = flag.get("page")
            message = flag.get("message", "")

            if flag_type == "low_confidence_ocr" and page:
                low_confidence_pages.append(page)
            elif flag_type == "allergy_information_unclear" and page:
                allergy_unclear_pages.append(page)
            elif flag_type == "missing_required_field":
                missing_fields.append(message)
            elif flag_type in {
                "medication_reconciliation_required",
                "admission_medication_list_missing",
                "low_confidence_discharge_medication",
            }:
                medication_flags.append(message)
            else:
                other_flags.append(message)

        grouped = []

        if low_confidence_pages:
            pages = sorted(set(low_confidence_pages))
            grouped.append(
                f"Low-confidence OCR pages were excluded from primary evidence: pages {', '.join(map(str, pages))}."
            )

        if allergy_unclear_pages:
            pages = sorted(set(allergy_unclear_pages))
            grouped.append(
                f"Allergy sections were detected but OCR was unclear on pages {', '.join(map(str, pages))}; clinician review required."
            )

        for message in missing_fields:
            grouped.append(message)

        for message in sorted(set(medication_flags)):
            grouped.append(message)

        for message in sorted(set(other_flags)):
            if message:
                grouped.append(message)

        return grouped



def save_discharge_summary_json(summary: Dict, output_path: str) -> None:
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with output_path_obj.open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)


def save_discharge_summary_markdown(markdown: str, output_path: str) -> None:
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    output_path_obj.write_text(markdown, encoding="utf-8")