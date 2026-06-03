import json
import re
from pathlib import Path
from typing import Dict, List, Tuple


class MedicationReconcilerTool:
    """
    Reconciles admission and discharge medications.

    Safety rule:
    If admission medications are missing or unreadable, do not assume discharge medicines are 'new'.
    Mark the comparison as unable to determine and require clinician review.
    """

    MOCK_INTERACTIONS = {
        ("WARFARIN", "ASPIRIN"): "Increased bleeding risk.",
        ("LISINOPRIL", "SPIRONOLACTONE"): "Hyperkalemia risk.",
        ("METFORMIN", "CONTRAST"): "Potential renal/lactic acidosis concern depending on renal function.",
        ("IBUPROFEN", "ASPIRIN"): "Increased bleeding/GI irritation risk.",
    }

    def reconcile(self, evidence_map: Dict) -> Dict:
        facts = evidence_map.get("facts", {})

        admission_meds = facts.get("admission_medications", [])
        discharge_meds = facts.get("discharge_medications", [])

        report = {
            "status": "completed",
            "admission_medications_found": len(admission_meds),
            "discharge_medications_found": len(discharge_meds),
            "medication_changes": [],
            "interaction_checks": [],
            "review_flags": [],
        }

        if not discharge_meds:
            report["review_flags"].append(
                {
                    "type": "missing_discharge_medications",
                    "message": "No readable discharge medication list was found. Clinician review required.",
                    "severity": "high",
                }
            )
            return report

        if not admission_meds:
            report["review_flags"].append(
                {
                    "type": "admission_medication_list_missing",
                    "message": "Admission medication list was not clearly available. Medication changes cannot be safely classified as added/stopped/changed.",
                    "severity": "high",
                }
            )

            for med in discharge_meds:
                normalized = self._normalize_medication_line(med.get("value", ""))

                report["medication_changes"].append(
                    {
                        "medication_raw": med.get("value"),
                        "medication_normalized": normalized,
                        "change_type": "unable_to_determine",
                        "admission_status": "unknown",
                        "discharge_status": "present",
                        "reason": "Admission medication list not available in readable source notes.",
                        "requires_clinician_review": True,
                        "source_file": med.get("source_file"),
                        "page": med.get("page"),
                        "confidence": med.get("confidence", "unknown"),
                    }
                )

                if med.get("confidence") == "low":
                    report["review_flags"].append(
                        {
                            "type": "low_confidence_discharge_medication",
                            "message": f"OCR confidence is low for discharge medication: {med.get('value')}",
                            "source_file": med.get("source_file"),
                            "page": med.get("page"),
                            "severity": "medium",
                        }
                    )

            report["interaction_checks"] = self._mock_drug_interaction_check(discharge_meds)
            return report

        # Future path: when admission meds are available, compare normalized names.
        admission_names = {
            self._normalize_medication_line(med.get("value", "")): med
            for med in admission_meds
        }

        discharge_names = {
            self._normalize_medication_line(med.get("value", "")): med
            for med in discharge_meds
        }

        for name, discharge_med in discharge_names.items():
            if name in admission_names:
                change_type = "continued_or_possibly_unchanged"
                requires_review = False
                reason = "Medication appears in both admission and discharge lists."
            else:
                change_type = "possibly_added"
                requires_review = True
                reason = "Medication appears in discharge list but not in readable admission list."

            report["medication_changes"].append(
                {
                    "medication_raw": discharge_med.get("value"),
                    "medication_normalized": name,
                    "change_type": change_type,
                    "reason": reason,
                    "requires_clinician_review": requires_review,
                    "source_file": discharge_med.get("source_file"),
                    "page": discharge_med.get("page"),
                    "confidence": discharge_med.get("confidence", "unknown"),
                }
            )

        for name, admission_med in admission_names.items():
            if name not in discharge_names:
                report["medication_changes"].append(
                    {
                        "medication_raw": admission_med.get("value"),
                        "medication_normalized": name,
                        "change_type": "possibly_stopped",
                        "reason": "Medication appears in admission list but not in discharge list.",
                        "requires_clinician_review": True,
                        "source_file": admission_med.get("source_file"),
                        "page": admission_med.get("page"),
                        "confidence": admission_med.get("confidence", "unknown"),
                    }
                )

        report["interaction_checks"] = self._mock_drug_interaction_check(discharge_meds)
        return report

    def _normalize_medication_line(self, value: str) -> str:
        value = value.upper()
        value = value.replace("TAB.", "TAB ")
        value = value.replace("TAB,", "TAB ")
        value = value.replace("TABLET", "TAB")

        value = re.sub(r"[^A-Z0-9\s]", " ", value)
        value = re.sub(r"\s+", " ", value).strip()

        # Try to keep medicine name + strength but avoid pretending OCR is perfect.
        value = re.sub(r"^TAB\s+", "", value)

        return value if value else "UNCLEAR_MEDICATION_TEXT"

    def _mock_drug_interaction_check(self, discharge_meds: List[Dict]) -> List[Dict]:
        normalized_names = [
            self._normalize_medication_line(med.get("value", ""))
            for med in discharge_meds
        ]

        results = []

        for left, right in self._pairs(normalized_names):
            issue = self._lookup_mock_interaction(left, right)

            if issue:
                results.append(
                    {
                        "medication_a": left,
                        "medication_b": right,
                        "interaction": issue,
                        "requires_clinician_review": True,
                    }
                )

        if not results:
            results.append(
                {
                    "status": "no_mock_interaction_detected",
                    "message": "No interaction was detected by the mock interaction checker. This is not a real clinical drug-interaction database.",
                    "requires_clinician_review": False,
                }
            )

        return results

    def _lookup_mock_interaction(self, left: str, right: str) -> str:
        for med_a, med_b in self.MOCK_INTERACTIONS:
            if med_a in left and med_b in right:
                return self.MOCK_INTERACTIONS[(med_a, med_b)]
            if med_b in left and med_a in right:
                return self.MOCK_INTERACTIONS[(med_a, med_b)]

        return ""

    def _pairs(self, items: List[str]) -> List[Tuple[str, str]]:
        pairs = []

        for i in range(len(items)):
            for j in range(i + 1, len(items)):
                pairs.append((items[i], items[j]))

        return pairs


def save_medication_reconciliation(report: Dict, output_path: str) -> None:
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with output_path_obj.open("w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)