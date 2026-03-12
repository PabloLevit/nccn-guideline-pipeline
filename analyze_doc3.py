import fitz
import re
import sys
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timezone

# =========================
# CONFIG
# =========================

PDF_DIR = Path("PDF Guidelines")
RESULTS_DIR = Path(".")
RESULTS_DIR.mkdir(exist_ok=True)

TEXT_WINDOW = 160

# =========================
# PDF INGESTION
# =========================

def load_pdf_text(pdf_path):
    doc = fitz.open(pdf_path)
    lines = []
    for page in doc:
        text = page.get_text("text")
        for line in text.split("\n"):
            clean = re.sub(r"\s+", " ", line).strip()
            if len(clean) > 4:
                lines.append(clean)
    return lines


def attach_references(lines):
    """
    Tries to keep nearby NCCN section references with each line.
    """
    current_ref = None
    out = []

    ref_pattern = re.compile(
        r"(Version\s+\d+\.\d+.*?|[A-Z]{2,}-[A-Z0-9]+.*?\d+\s+of\s+\d+)",
        re.IGNORECASE
    )

    for line in lines:
        m = ref_pattern.search(line)
        if m:
            current_ref = m.group(1)

        out.append((line, current_ref or "Reference not specified"))

    return out

# =========================
# 1.1.1 – Tissue NGS
# =========================

NGS_PATTERNS = [
    r"ngs is recommended",
    r"comprehensive molecular profiling",
    r"genomic profiling",
    r"molecular profiling by ngs",
    r"ngs panels? (are|is) recommended",
    r"ngs testing is recommended",
    r"acceptable alternative",
    r"used to determine",
    r"identify.*pan[-\s]?tumor",
]

def Q1_1_1_tissue_ngs(lines):
    evidence = []

    for line, ref in lines:
        for pat in NGS_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                evidence.append((line, ref))

    return evidence


# =========================
# 1.1.2 – Disease Setting / When
# =========================

SETTING_PATTERNS = [
    r"newly diagnosed",
    r"initial evaluation",
    r"prior to treatment",
    r"recurrent",
    r"progressive",
    r"advanced",
    r"metastatic",
    r"unresectable",
    r"stage\s+(iii|iv)",
    r"diagnostic stage",
    r"differential diagnosis",
    r"after progression",
    r"indeterminate cytology",
]

def Q1_1_2_disease_setting(lines):
    evidence = []

    for line, ref in lines:
        for pat in SETTING_PATTERNS:
            if re.search(pat, line, re.IGNORECASE):
                evidence.append((line, ref))

    return evidence


# =========================
# 1.2 – Biomarkers (OPEN SET)
# =========================

BIOMARKER_TRIGGERS = [
    r"testing for",
    r"assessment of",
    r"evaluation of",
    r"recommended to assess",
    r"should be tested",
    r"biomarker",
    r"mutation",
    r"fusion",
    r"rearrangement",
    r"amplification",
    r"overexpression",
    r"expression",
    r"loss of",
    r"deficiency",
    r"status",
    r"panel including",
]

ENTITY_PATTERN = re.compile(
    r"\b[A-Z0-9]{2,}(::[A-Z0-9]{2,})?\b"
)

def Q1_2_biomarkers(lines):
    biomarker_hits = defaultdict(set)

    for line, ref in lines:
        lower = line.lower()
        if any(re.search(p, lower) for p in BIOMARKER_TRIGGERS):
            for ent in ENTITY_PATTERN.findall(line):
                biomarker_hits[ent].add(ref)

    return biomarker_hits


# =========================
# OUTPUT
# =========================

def write_results(pdf_name, q1, q2, q3):
    out_file = RESULTS_DIR / f"{pdf_name} results.txt"

    with open(out_file, "w", encoding="utf-8") as f:
        f.write(f"Processed: {datetime.now(timezone.utc).isoformat()} UTC\n\n")

        f.write("1.1.1 Is there a recommendation for Tissue NGS?\n")
        f.write("YES\n" if q1 else "NO\n")
        for line, ref in q1:
            f.write(f"- {line} ({ref})\n")

        f.write("\n1.1.2 In which disease settings?\n")
        f.write("YES\n" if q2 else "NO\n")
        for line, ref in q2:
            f.write(f"- {line} ({ref})\n")

        f.write("\n1.2 Which biomarkers are recommended?\n")
        f.write("YES\n" if q3 else "NO\n")
        for biomarker, refs in sorted(q3.items()):
            for ref in refs:
                f.write(f"- {biomarker} ({ref})\n")

    print(f"✔ Results written to {out_file}")


# =========================
# MAIN
# =========================

def main():
    pdf_files = sorted(PDF_DIR.glob("*.pdf"))

    if not pdf_files:
        raise RuntimeError("No PDF files found in PDF Guidelines directory.")

    print("\nAvailable NCCN PDFs:")
    for pdf in pdf_files:
        print(f"- {pdf.name}")

    user_input = input("\nEnter tumor or PDF name: ").strip()

    # Allow user to type without .pdf
    if not user_input.lower().endswith(".pdf"):
        user_input += ".pdf"

    pdf_path = PDF_DIR / user_input

    if not pdf_path.exists():
        raise FileNotFoundError(f"\n❌ '{user_input}' not found in PDF Guidelines.")

    raw_lines = load_pdf_text(pdf_path)
    lines = attach_references(raw_lines)

    q1 = Q1_1_1_tissue_ngs(lines)
    q2 = Q1_1_2_disease_setting(lines)
    q3 = Q1_2_biomarkers(lines)

    write_results(pdf_path.stem, q1, q2, q3)


if __name__ == "__main__":
    main()
