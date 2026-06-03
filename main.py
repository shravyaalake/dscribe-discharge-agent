import argparse
from pathlib import Path
import pytesseract

pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
from src.agent.trace import TraceLogger
from src.tools.pdf_reader import PDFReaderTool, save_extracted_pages
from src.tools.document_classifier import DocumentClassifierTool, save_document_inventory
from src.tools.evidence_extractor import EvidenceExtractorTool, save_evidence_map
from src.tools.medication_reconciler import (
    MedicationReconcilerTool,
    save_medication_reconciliation,
)
from src.tools.conflict_detector import ConflictDetectorTool, save_conflict_report
from src.tools.summary_writer import (
    DischargeSummaryWriterTool,
    save_discharge_summary_json,
    save_discharge_summary_markdown,
)

MAX_STEPS = 20  # Hard cap to prevent infinite loops

def run_patient_ingestion(patient_folder: str):
    patient_path = Path(patient_folder)

    if not patient_path.exists():
        raise FileNotFoundError(f"Patient folder not found: {patient_folder}")

    patient_id = patient_path.name
    output_dir = Path("outputs") / patient_id
    output_dir.mkdir(parents=True, exist_ok=True)

    trace = TraceLogger(str(output_dir))

    step = 1

    trace.log(
        step=step,
        reasoning="The agent needs to inspect the patient folder and find source PDFs before extracting clinical facts.",
        action="list_patient_files",
        inputs={"patient_folder": str(patient_path)},
        result={"files": [p.name for p in patient_path.glob("*")]},
        next_decision="Read all PDF files found in the patient folder.",
    )

    pdf_files = list(patient_path.glob("*.pdf"))

    if not pdf_files:
        step += 1
        trace.log(
            step=step,
            reasoning="No PDF files were found, so the agent cannot produce a discharge summary.",
            action="stop",
            inputs={"patient_folder": str(patient_path)},
            result={"status": "failed", "error": "No PDF files found."},
            next_decision="Ask user to provide source-note PDFs.",
        )
        return

    all_pages = []

    reader = PDFReaderTool()

    for pdf_file in pdf_files:
        if step >= MAX_STEPS:
            trace.log(
                step=step,
                reasoning="The hard step cap was reached. The agent must stop to avoid an uncontrolled loop.",
                action="stop_due_to_step_cap",
                inputs={"max_steps": MAX_STEPS},
                result={"status": "stopped"},
                next_decision="Report partial extraction results.",
            )
            break

        step += 1

        trace.log(
            step=step,
            reasoning="The agent found a PDF and needs to extract text. It will try normal PDF text extraction first, then OCR if needed.",
            action="read_pdf_with_ocr_fallback",
            inputs={"pdf_file": str(pdf_file)},
            result={"status": "started"},
            next_decision="Extract page-level text and warnings.",
        )

        pages = reader.extract_from_pdf(str(pdf_file))

        for page in pages:
            page["source_file"] = pdf_file.name

        all_pages.extend(pages)

        successful_pages = sum(1 for p in pages if p["status"] == "success")
        failed_pages = sum(1 for p in pages if p["status"] == "failed")
        ocr_pages = sum(1 for p in pages if p["extraction_method"] == "ocr")

        step += 1

        trace.log(
            step=step,
            reasoning="PDF extraction completed. The agent must record whether OCR was required and whether any pages failed.",
            action="summarize_pdf_extraction",
            inputs={"pdf_file": pdf_file.name},
            result={
                "total_pages": len(pages),
                "successful_pages": successful_pages,
                "failed_pages": failed_pages,
                "ocr_pages": ocr_pages,
            },
            next_decision="Save extracted pages for downstream clinical fact extraction.",
        )

    extracted_output_path = output_dir / "extracted_pages.json"
    save_extracted_pages(all_pages, str(extracted_output_path))

        # Step: classify extracted pages
    classifier = DocumentClassifierTool()
    classified_pages = classifier.classify_pages(all_pages)

    inventory_output_path = output_dir / "document_inventory.json"
    save_document_inventory(classified_pages, str(inventory_output_path))

    page_type_counts = {}
    usable_pages = 0

    for page in classified_pages:
        page_type = page.get("page_type", "unknown")
        page_type_counts[page_type] = page_type_counts.get(page_type, 0) + 1

        if page.get("usable_for_summary"):
            usable_pages += 1

    step += 1

    trace.log(
        step=step,
        reasoning="The agent needs to classify extracted pages so it can prioritize reliable clinical sources and avoid relying on unreadable handwritten content.",
        action="classify_pages",
        inputs={"pages": len(all_pages)},
        result={
            "status": "success",
            "page_type_counts": page_type_counts,
            "usable_pages_for_summary": usable_pages,
            "document_inventory_path": str(inventory_output_path),
        },
        next_decision="Use classified pages for structured clinical fact extraction.",
    )

    # Step: extract clinical evidence
    evidence_extractor = EvidenceExtractorTool()
    evidence_map = evidence_extractor.extract(classified_pages)

    evidence_output_path = output_dir / "evidence_map.json"
    save_evidence_map(evidence_map, str(evidence_output_path))

    extracted_fact_counts = {
        field: len(values)
        for field, values in evidence_map.get("facts", {}).items()
    }

    step += 1

    trace.log(
        step=step,
        reasoning="The agent needs structured evidence before writing any discharge summary. Every extracted fact must be linked to a source page to prevent fabrication.",
        action="extract_clinical_evidence",
        inputs={"classified_pages": len(classified_pages)},
        result={
            "status": "success",
            "evidence_map_path": str(evidence_output_path),
            "fact_counts": extracted_fact_counts,
            "review_flags": len(evidence_map.get("review_flags", [])),
            "unusable_pages": len(evidence_map.get("unusable_pages", [])),
        },
        next_decision="Use evidence map for conflict detection, medication reconciliation, and summary drafting.",
    )

    step += 1

    trace.log(
        step=step,
        reasoning="The extracted page text, document inventory, and evidence map are now saved. The next stage will use this evidence for discharge summary drafting.",
        action="save_extracted_pages_inventory_and_evidence",
        inputs={
            "extracted_pages_path": str(extracted_output_path),
            "document_inventory_path": str(inventory_output_path),
            "evidence_map_path": str(evidence_output_path),
        },
        result={
            "status": "success",
            "pages_saved": len(all_pages),
            "classified_pages": len(classified_pages),
            "evidence_fields": list(evidence_map.get("facts", {}).keys()),
        },
        next_decision="Proceed to conflict detection and discharge summary generation.",
    )

        # Step: medication reconciliation
    medication_reconciler = MedicationReconcilerTool()
    medication_report = medication_reconciler.reconcile(evidence_map)

    medication_output_path = output_dir / "medication_reconciliation.json"
    save_medication_reconciliation(medication_report, str(medication_output_path))

    step += 1

    trace.log(
        step=step,
        reasoning="The agent found discharge medications and must reconcile them against admission medications. Since admission medication data may be missing, it must flag uncertainty instead of assuming additions or stops.",
        action="reconcile_medications",
        inputs={
            "discharge_medications": medication_report.get("discharge_medications_found"),
            "admission_medications": medication_report.get("admission_medications_found"),
        },
        result={
            "status": medication_report.get("status"),
            "medication_changes": len(medication_report.get("medication_changes", [])),
            "review_flags": len(medication_report.get("review_flags", [])),
            "interaction_checks": len(medication_report.get("interaction_checks", [])),
            "medication_reconciliation_path": str(medication_output_path),
        },
        next_decision="Run conflict detection before drafting the discharge summary.",
    )

    # Step: conflict detection
    conflict_detector = ConflictDetectorTool()
    conflict_report = conflict_detector.detect(evidence_map)

    conflict_output_path = output_dir / "conflict_report.json"
    save_conflict_report(conflict_report, str(conflict_output_path))

    step += 1

    trace.log(
        step=step,
        reasoning="The agent must check whether reliable source facts disagree. If conflicts exist, it must flag them instead of choosing one value.",
        action="detect_conflicts",
        inputs={
            "evidence_fields": list(evidence_map.get("facts", {}).keys()),
        },
        result={
            "status": conflict_report.get("status"),
            "conflicts": len(conflict_report.get("conflicts", [])),
            "review_flags": len(conflict_report.get("review_flags", [])),
            "conflict_report_path": str(conflict_output_path),
        },
        next_decision="Use evidence, medication reconciliation, and conflict report to draft the discharge summary.",
    )

    step += 1

    trace.log(
        step=step,
        reasoning="The extracted page text, document inventory, evidence map, medication reconciliation, and conflict report are now saved. The next stage will draft the discharge summary using only supported evidence.",
        action="save_all_intermediate_outputs",
        inputs={
            "extracted_pages_path": str(extracted_output_path),
            "document_inventory_path": str(inventory_output_path),
            "evidence_map_path": str(evidence_output_path),
            "medication_reconciliation_path": str(medication_output_path),
            "conflict_report_path": str(conflict_output_path),
        },
        result={
            "status": "success",
            "pages_saved": len(all_pages),
            "classified_pages": len(classified_pages),
            "evidence_fields": list(evidence_map.get("facts", {}).keys()),
            "medication_review_flags": len(medication_report.get("review_flags", [])),
            "conflicts": len(conflict_report.get("conflicts", [])),
        },
        next_decision="Proceed to final discharge summary drafting.",
    )

        # Step: discharge summary drafting
    summary_writer = DischargeSummaryWriterTool()
    discharge_summary = summary_writer.write(
        evidence_map=evidence_map,
        medication_report=medication_report,
        conflict_report=conflict_report,
    )

    discharge_summary_json_path = output_dir / "discharge_summary.json"
    discharge_summary_md_path = output_dir / "discharge_summary.md"

    save_discharge_summary_json(discharge_summary, str(discharge_summary_json_path))
    save_discharge_summary_markdown(
        summary_writer.to_markdown(discharge_summary),
        str(discharge_summary_md_path),
    )

    step += 1

    trace.log(
        step=step,
        reasoning="The agent now has evidence, medication reconciliation, and conflict report. It can draft the discharge summary using only sourced facts and explicit missing-data flags.",
        action="draft_discharge_summary",
        inputs={
            "evidence_map_path": str(evidence_output_path),
            "medication_reconciliation_path": str(medication_output_path),
            "conflict_report_path": str(conflict_output_path),
        },
        result={
            "status": "success",
            "discharge_summary_json_path": str(discharge_summary_json_path),
            "discharge_summary_md_path": str(discharge_summary_md_path),
            "safety_flags": len(discharge_summary.get("safety_flags_for_clinician_review", [])),
        },
        next_decision="Stop after producing final draft and trace outputs.",
    )

    step += 1

    trace.log(
        step=step,
        reasoning="All intermediate outputs and the final discharge summary draft are saved. The agent stops after producing a clinician-review draft.",
        action="finish",
        inputs={
            "extracted_pages_path": str(extracted_output_path),
            "document_inventory_path": str(inventory_output_path),
            "evidence_map_path": str(evidence_output_path),
            "medication_reconciliation_path": str(medication_output_path),
            "conflict_report_path": str(conflict_output_path),
            "discharge_summary_json_path": str(discharge_summary_json_path),
            "discharge_summary_md_path": str(discharge_summary_md_path),
        },
        result={
            "status": "success",
            "safety_flags": len(discharge_summary.get("safety_flags_for_clinician_review", [])),
            "conflicts": len(conflict_report.get("conflicts", [])),
            "medication_review_flags": len(medication_report.get("review_flags", [])),
        },
        next_decision="Stop.",
    )

    print(f"\nDone.")
    print(f"Extracted pages saved to: {extracted_output_path}")
    print(f"Document inventory saved to: {inventory_output_path}")
    print(f"Evidence map saved to: {evidence_output_path}")
    print(f"Medication reconciliation saved to: {medication_output_path}")
    print(f"Conflict report saved to: {conflict_output_path}")
    print(f"Discharge summary JSON saved to: {discharge_summary_json_path}")
    print(f"Discharge summary Markdown saved to: {discharge_summary_md_path}")
    print(f"Trace saved to: {output_dir / 'trace.jsonl'}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--patient-folder",
        required=True,
        help="Path to patient folder containing PDF source notes.",
    )

    args = parser.parse_args()
    run_patient_ingestion(args.patient_folder)