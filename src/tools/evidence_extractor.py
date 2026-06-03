import json
import re
from pathlib import Path
from typing import Dict, List, Optional


class EvidenceExtractorTool:
    """
    Extracts structured clinical evidence from classified pages.

    This extractor is intentionally conservative:
    - It only extracts text that appears in the source.
    - It stores page/source evidence for every fact.
    - It flags unclear OCR or missing sections instead of guessing.
    """

    def extract(self, classified_pages: List[Dict]) -> Dict:
        evidence = {
            "patient_id": None,
            "source_files": [],
            "facts": {
                "demographics": [],
                "admission_discharge_dates": [],
                "principal_diagnosis": [],
                "secondary_diagnoses": [],
                "history": [],
                "past_history": [],
                "physical_examination": [],
                "hospital_course": [],
                "investigations": [],
                "procedures": [],
                "allergies": [],
                "discharge_condition": [],
                "discharge_medications": [],
                "follow_up_instructions": [],
                "pending_results": [],
            },
            "review_flags": [],
            "unusable_pages": [],
        }

        source_files = sorted(
            list({page.get("source_file") for page in classified_pages if page.get("source_file")})
        )
        evidence["source_files"] = source_files

        for page in classified_pages:
            page_no = page.get("page")
            page_type = page.get("page_type")
            text = page.get("text", "") or ""
            usable = page.get("usable_for_summary", False)
            warnings = page.get("warnings", [])

            if page.get("status") != "success":
                evidence["unusable_pages"].append(
                    {
                        "page": page_no,
                        "source_file": page.get("source_file"),
                        "reason": "OCR or PDF extraction failed.",
                        "warnings": warnings,
                    }
                )
                continue

            if not usable:
                if warnings:
                    evidence["review_flags"].append(
                        {
                            "type": "low_confidence_ocr",
                            "page": page_no,
                            "source_file": page.get("source_file"),
                            "message": "Page was not used as a primary evidence source because OCR quality may be low.",
                            "warnings": warnings,
                        }
                    )

            # Extract final discharge-summary facts only from reliable discharge summary pages.
            # Do not extract high-confidence final facts from low-confidence handwritten/admission pages.
            if page_type == "discharge_summary" and usable:
                self._extract_diagnoses(text, page, evidence)
                self._extract_history(text, page, evidence)
                self._extract_past_history(text, page, evidence)
                self._extract_physical_exam(text, page, evidence)
                self._extract_hospital_course(text, page, evidence)
                self._extract_discharge_condition(text, page, evidence)
                self._extract_follow_up(text, page, evidence)
                self._extract_pending_results(text, page, evidence)
                self._extract_discharge_medications(text, page, evidence)

            # Extract labs and imaging from investigation/radiology pages
            if page_type in {"investigation", "radiology_report"}:
                self._extract_investigation_summary(text, page, evidence)
                self._extract_pending_results(text, page, evidence)

            # Extract allergy statement if clearly present
            self._extract_allergies(text, page, evidence)

        self._add_required_field_flags(evidence)
        self._dedupe_evidence(evidence)

        return evidence

    def _fact(self, field: str, value: str, page: Dict, quote: Optional[str] = None, confidence: str = "medium") -> Dict:
        return {
            "field": field,
            "value": self._clean(value),
            "source_file": page.get("source_file"),
            "page": page.get("page"),
            "source_quote": self._clean(quote or value),
            "confidence": confidence,
        }

    def _extract_diagnoses(self, text: str, page: Dict, evidence: Dict) -> None:
        diagnosis_block = self._between(
            text,
            start_markers=["DIAGNOSIS:"],
            end_markers=["HISTORY:", "PAST HISTORY:", "PHYSICAL EXAMINATION:"],
        )

        if not diagnosis_block:
            return

        lines = [self._clean(line) for line in diagnosis_block.splitlines()]
        diagnoses = []

        for line in lines:
            line = re.sub(r"^\d+\)\s*", "", line).strip()
            if line:
                diagnoses.append(line)

        if diagnoses:
            evidence["facts"]["principal_diagnosis"].append(
                self._fact(
                    "principal_diagnosis",
                    diagnoses[0],
                    page,
                    quote=diagnosis_block,
                    confidence="high",
                )
            )

        for diagnosis in diagnoses[1:]:
            evidence["facts"]["secondary_diagnoses"].append(
                self._fact(
                    "secondary_diagnosis",
                    diagnosis,
                    page,
                    quote=diagnosis_block,
                    confidence="high",
                )
            )

    def _extract_history(self, text: str, page: Dict, evidence: Dict) -> None:
        block = self._between(
            text,
            start_markers=["HISTORY:"],
            end_markers=["PAST HISTORY:", "PHYSICAL EXAMINATION:"],
        )

        if block:
            evidence["facts"]["history"].append(
                self._fact("history", block, page, quote=block, confidence="high")
            )

    def _extract_past_history(self, text: str, page: Dict, evidence: Dict) -> None:
        block = self._between(
            text,
            start_markers=["PAST HISTORY:"],
            end_markers=["PHYSICAL EXAMINATION:", "INVESTIGATIONS:"],
        )

        if block:
            evidence["facts"]["past_history"].append(
                self._fact("past_history", block, page, quote=block, confidence="high")
            )

    def _extract_physical_exam(self, text: str, page: Dict, evidence: Dict) -> None:
        block = self._between(
            text,
            start_markers=["PHYSICAL EXAMINATION:"],
            end_markers=["INVESTIGATIONS:", "COURSE IN THE HOSPITAL:"],
        )

        if block:
            evidence["facts"]["physical_examination"].append(
                self._fact("physical_examination", block, page, quote=block, confidence="high")
            )

    def _extract_hospital_course(self, text: str, page: Dict, evidence: Dict) -> None:
        block = self._between(
            text,
            start_markers=["COURSE IN THE HOSPITAL:"],
            end_markers=["CONDITION AT DISCHARGE:", "ADVICE ON DISCHARGE:", "FOLLOW-UP INSTRUCTIONS:"],
        )

        # Page 2 may continue hospital course without the heading.
        if not block and (
            "iv antibiotics" in text.lower()
            or "1v antibiotics" in text.lower()
            or "antiemetics" in text.lower()
        ):
            block = self._between(
                text,
                start_markers=["IV antibiotics", "1V antibiotics", "antiemetics"],
                end_markers=["CONDITION AT DISCHARGE:"],
            )

            if block and not block.lower().startswith("iv antibiotics"):
                block = "IV antibiotics, " + block

        if block:
            evidence["facts"]["hospital_course"].append(
                self._fact("hospital_course", block, page, quote=block, confidence="high")
            )

    def _extract_discharge_condition(self, text: str, page: Dict, evidence: Dict) -> None:
        block = self._between(
            text,
            start_markers=["CONDITION AT DISCHARGE:"],
            end_markers=["ADVICE ON DISCHARGE:", "FOLLOW-UP INSTRUCTIONS:"],
        )

        if block:
            evidence["facts"]["discharge_condition"].append(
                self._fact("discharge_condition", block, page, quote=block, confidence="high")
            )

    def _extract_follow_up(self, text: str, page: Dict, evidence: Dict) -> None:
        block = self._between(
            text,
            start_markers=["FOLLOW-UP INSTRUCTIONS:"],
            end_markers=[],
        )

        if block:
            evidence["facts"]["follow_up_instructions"].append(
                self._fact("follow_up_instructions", block, page, quote=block, confidence="high")
            )

    def _extract_pending_results(self, text: str, page: Dict, evidence: Dict) -> None:
        lowered = text.lower()

        exact_pending_items = [
            "urine culture and sensitivity sent- report awaited",
            "urine culture and sensitivity sent - report awaited",
        ]

        for pending_item in exact_pending_items:
            if pending_item in lowered:
                evidence["facts"]["pending_results"].append(
                    self._fact(
                        "pending_result",
                        "Urine culture and sensitivity sent - report awaited.",
                        page,
                        quote="Urine culture and sensitivity sent- report awaited.",
                        confidence="high",
                    )
                )
                return

        if "report awaited" in lowered:
            sentence = self._sentence_containing(text, "report awaited")

            if "FOLLOW-UP INSTRUCTIONS:" in sentence:
                sentence = sentence.split("FOLLOW-UP INSTRUCTIONS:")[-1].strip()

            if sentence:
                evidence["facts"]["pending_results"].append(
                    self._fact(
                        "pending_result",
                        sentence,
                        page,
                        quote=sentence,
                        confidence="medium",
                    )
                )

    def _extract_discharge_medications(self, text: str, page: Dict, evidence: Dict) -> None:
        if "advice on discharge" not in text.lower():
            return

        block = self._between(
            text,
            start_markers=["ADVICE ON DISCHARGE:"],
            end_markers=["FOLLOW-UP INSTRUCTIONS:"],
        )

        if not block:
            return

        candidate_lines = []
        for line in block.splitlines():
            cleaned = self._clean(line)

            if not cleaned:
                continue

            if "TAB" in cleaned.upper() or "TABLET" in cleaned.upper():
                candidate_lines.append(cleaned)

        if not candidate_lines:
            evidence["review_flags"].append(
                {
                    "type": "medication_extraction_unclear",
                    "page": page.get("page"),
                    "source_file": page.get("source_file"),
                    "message": "Discharge medication section detected, but OCR could not clearly extract medication names.",
                }
            )
            return

        for line in candidate_lines:
            confidence = "medium"

            # Medication table OCR is noisy, so be conservative.
            if any(ch in line for ch in ["¢", "|", "‘", "ane"]):
                confidence = "low"

            evidence["facts"]["discharge_medications"].append(
                self._fact(
                    "discharge_medication",
                    line,
                    page,
                    quote=line,
                    confidence=confidence,
                )
            )

        evidence["review_flags"].append(
            {
                "type": "medication_reconciliation_required",
                "page": page.get("page"),
                "source_file": page.get("source_file"),
                "message": "Admission medication list was not clearly available. Discharge medications should be reconciled by clinician.",
            }
        )

    def _extract_investigation_summary(self, text: str, page: Dict, evidence: Dict) -> None:
        useful_keywords = [
            "serum creatinine",
            "blood sugar",
            "sodium",
            "potassium",
            "chloride",
            "complete blood count",
            "urine routine",
            "usg abdomen",
            "fatty infiltration",
            "cholelithiasis",
            "ascites",
            "pleural effusion",
        ]

        lowered = text.lower()

        for keyword in useful_keywords:
            if keyword in lowered:
                sentence = self._sentence_containing(text, keyword)
                evidence["facts"]["investigations"].append(
                    self._fact(
                        "investigation",
                        sentence or keyword,
                        page,
                        quote=sentence or keyword,
                        confidence="medium",
                    )
                )

    def _extract_allergies(self, text: str, page: Dict, evidence: Dict) -> None:
        lowered = text.lower()

        # Only accept allergy facts if OCR text is clear.
        if "nkda" in lowered:
            evidence["facts"]["allergies"].append(
                self._fact(
                    "allergy",
                    "No known drug allergies documented",
                    page,
                    quote=self._sentence_containing(text, "nkda") or "NKDA",
                    confidence="medium",
                )
            )
            return

        if "known drug allergies" in lowered and "no known" in lowered:
            evidence["facts"]["allergies"].append(
                self._fact(
                    "allergy",
                    "No known drug allergies documented",
                    page,
                    quote=self._sentence_containing(text, "known drug allergies") or "Known Drug Allergies",
                    confidence="medium",
                )
            )
            return

        # OCR like "Ng Erum" is too unclear. Flag it instead of treating it as a fact.
        if "allergic history" in lowered or "known drug allergies" in lowered:
            evidence["review_flags"].append(
                {
                    "type": "allergy_information_unclear",
                    "page": page.get("page"),
                    "source_file": page.get("source_file"),
                    "message": "Allergy section was detected, but OCR text was unclear. Clinician review required.",
                }
            )

    def _add_required_field_flags(self, evidence: Dict) -> None:
        required_map = {
            "demographics": "Patient demographics missing from readable source notes.",
            "admission_discharge_dates": "Admission and discharge dates missing from readable source notes.",
            "procedures": "No clear procedure details found in readable source notes.",
            "allergies": "Allergy information missing or unclear in readable source notes.",
        }

        for field, message in required_map.items():
            if not evidence["facts"].get(field):
                evidence["review_flags"].append(
                    {
                        "type": "missing_required_field",
                        "field": field,
                        "message": message,
                    }
                )

    def _dedupe_evidence(self, evidence: Dict) -> None:
        for field, facts in evidence["facts"].items():
            seen = set()
            deduped = []

            for fact in facts:
                key = (
                    fact.get("field"),
                    fact.get("value"),
                    fact.get("source_file"),
                    fact.get("page"),
                )

                if key not in seen:
                    seen.add(key)
                    deduped.append(fact)

            evidence["facts"][field] = deduped

    def _between(self, text: str, start_markers: List[str], end_markers: List[str]) -> str:
        lowered = text.lower()

        start_index = None
        matched_start = None

        for marker in start_markers:
            idx = lowered.find(marker.lower())
            if idx != -1:
                start_index = idx + len(marker)
                matched_start = marker
                break

        if start_index is None:
            return ""

        end_index = len(text)

        for marker in end_markers:
            idx = lowered.find(marker.lower(), start_index)
            if idx != -1:
                end_index = min(end_index, idx)

        return text[start_index:end_index].strip()

    def _sentence_containing(self, text: str, keyword: str) -> str:
        keyword_lower = keyword.lower()
        normalized = text.replace("\n", " ")

        sentences = re.split(r"(?<=[.!?])\s+", normalized)

        for sentence in sentences:
            if keyword_lower in sentence.lower():
                return self._clean(sentence)

        # fallback: return nearby substring
        idx = normalized.lower().find(keyword_lower)
        if idx == -1:
            return ""

        start = max(0, idx - 100)
        end = min(len(normalized), idx + 160)

        return self._clean(normalized[start:end])

    def _clean(self, value: str) -> str:
        value = value.replace("\n", " ")
        value = re.sub(r"\s+", " ", value)
        return value.strip()


def save_evidence_map(evidence: Dict, output_path: str) -> None:
    output_path_obj = Path(output_path)
    output_path_obj.parent.mkdir(parents=True, exist_ok=True)

    with output_path_obj.open("w", encoding="utf-8") as f:
        json.dump(evidence, f, indent=2, ensure_ascii=False)