# Dscribe Discharge Summary Agent

This project is a take-home assignment for the AI Engineer role at Dscribe. It implements an agentic AI-style workflow that reads messy clinical source-note PDFs and generates a structured discharge summary draft for clinician review.

The system prioritizes clinical safety. It does not invent missing information. Any missing, unclear, pending, or conflicting data is explicitly flagged for clinician review.

## What the Agent Does

Given a patient folder containing source-note PDFs, the agent:

1. Reads PDF files.
2. Falls back to OCR when normal PDF text extraction fails.
3. Classifies pages by document type.
4. Extracts structured clinical evidence with source page references.
5. Flags unreadable or low-confidence OCR pages.
6. Performs medication reconciliation.
7. Detects conflicts between extracted facts.
8. Generates a discharge summary draft.
9. Writes a readable step-by-step trace.

## Project Structure

```text
dscribe-discharge-agent/
│
├── data/
│   └── patients/
│       └── patient_2/
│           └── patient_2.pdf
│
├── outputs/
│   └── patient_2/
│       ├── extracted_pages.json
│       ├── document_inventory.json
│       ├── evidence_map.json
│       ├── medication_reconciliation.json
│       ├── conflict_report.json
│       ├── discharge_summary.json
│       ├── discharge_summary.md
│       └── trace.jsonl
│
├── src/
│   ├── agent/
│   │   └── trace.py
│   └── tools/
│       ├── pdf_reader.py
│       ├── document_classifier.py
│       ├── evidence_extractor.py
│       ├── medication_reconciler.py
│       ├── conflict_detector.py
│       └── summary_writer.py
│
├── main.py
├── requirements.txt
└── README.md

## How to Run the Project

Follow these steps from the project root folder:

```bash
cd dscribe-discharge-agent

1. Create a virtual environment
python -m venv venv

2. Activate the virtual environment
venv\Scripts\activate

3. Install dependencies
pip install -r requirements.txt

4. Place the patient PDF
data\patients\patient_2 => data/patients/patient_2/patient_2.pdf

5. Check generated outputs
outputs/patient_2/

Expected files:
extracted_pages.json
document_inventory.json
evidence_map.json
medication_reconciliation.json
conflict_report.json
discharge_summary.json
discharge_summary.md
trace.jsonl

The main clinician-review draft is: outputs/patient_2/discharge_summary.md

OCR Requirement

This project uses Tesseract OCR for scanned/image-based PDFs.

On Windows, install Tesseract OCR and ensure this path exists:
C:\Program Files\Tesseract-OCR\tesseract.exe

6. Run the script: python main.py --patient-folder data/patients/patient_2
