import json
import re
from pathlib import Path
from typing import Dict, List


class ConflictDetectorTool:
    """
    Detects conflicting clinical facts.

    Safety rule:
    If reliable source facts disagree, do not choose one silently.
    Produce a conflict report and require clinician review.
    """

    CONFLICT_CHECK_FIELDS = [
        "principal_diagnosis",
        "discharge_condition",
        "admission_discharge_dates",
        "allergies",
    ]

    def detect(self, evidence_map: Dict) -> Dict:
        facts = evidence_map.get("facts", {})

        report = {
            "status": "completed",
            "conflicts": [],
            "review_flags": [],
        }

        for field in self.CONFLICT_CHECK_FIELDS:
            field_facts = facts.get(field, [])

            conflict = self._detect_field_conflict(field, field_facts)

            if conflict:
                report["conflicts"].append(conflict)

        diagnosis_conflict = self._detect_diagnosis_overlap_conflict(facts)

        if diagnosis_conflict:
            report["conflicts"].append(diagnosis_conflict)

        if not report["conflicts"]:
            report["review_flags"].append(
                {
                    "type": "no_conflict_detected",
                    "message": "No direct conflict was detected among high-confidence structured facts. Low-confidence OCR pages are still excluded from final factual claims.",
                    "severity": "info",
                }
            )

        return report

    def _detect_field_conflict(self, field: str, field_facts: List[Dict]) -> Dict:
        if len(field_facts) <= 1:
            return {}

        normalized_to_facts = {}

        for fact in field_facts:
            normalized = self._normalize(fact.get("value", ""))

            if not normalized:
                continue

            normalized_to_facts.setdefault(normalized, []).append(fact)

        if len(normalized_to_facts.keys()) <= 1:
            return {}

        return {
            "type": "field_value_conflict",
            "field": field,
            "message": f"Conflicting values detected for {field}. Clinician review required.",
            "values": [
                {
                    "value": facts[0].get("value"),
                    "source_file": facts[0].get("source_file"),
                    "page": facts[0].get("page"),
                    "confidence": facts[0].get("confidence"),
                }
                for facts in normalized_to_facts.values()
            ],
            "requires_clinician_review": True,
            "severity": "high",
        }

    def _detect_diagnosis_overlap_conflict(self, facts: Dict) -> Dict:
        principal = facts.get("principal_diagnosis", [])
        secondary = facts.get("secondary_diagnoses", [])

        if not principal or not secondary:
            return {}

        principal_values = {self._normalize(fact.get("value", "")) for fact in principal}
        secondary_values = {self._normalize(fact.get("value", "")) for fact in secondary}

        overlap = principal_values.intersection(secondary_values)

        if not overlap:
            return {}

        return {
            "type": "diagnosis_role_conflict",
            "field": "diagnoses",
            "message": "The same diagnosis appears as both principal and secondary. Clinician review required.",
            "overlap": list(overlap),
            "requires_clinician_review": True,
            "severity": "medium",
        }

    def _normalize(self, value: str) -> str:
        value = value.upper()
        value = re.sub(r"[^A-Z0-9\s]", " ", value)
        value = re.sub(r"\s+", " ", value).strip()
        return value


def save_conflict_report(report: Dict, output_path: str) -> None:
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with output_path_obj.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)