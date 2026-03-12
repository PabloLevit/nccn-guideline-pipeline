import os
import sys
import json
import pathlib
import logging
import concurrent.futures
import re
from datetime import datetime

from PyPDF2 import PdfReader
from openai import OpenAI

# --------------------------------------------------------------
#                        CONFIGURATION
# --------------------------------------------------------------

API_KEY = os.getenv("OPENAI_API_KEY")
if API_KEY is None:
    raise ValueError("OPENAI_API_KEY not found. Please set it first.")

client = OpenAI()

MODEL_ID = "gpt-4o-mini"    
PDF_FILE = "cervical.pdf"  # default PDF, can be overridden by terminal argument
CACHE_FILE = "vector_cache.json"

WINDOW_SIZE = 2000  # character window to validate proximity for section references

SYSTEM_INSTRUCTION = """
You are a data extraction model specialized in NCCN Guidelines.

You MUST ignore all medical knowledge learned during pretraining or fine-tuning.
Your ONLY allowed source of information is the content extracted via file_search
from THIS guideline PDF. If the PDF does not explicitly state something, you MUST
output exactly the negative phrase required in the question instructions.
You are forbidden from inferring, guessing, or completing medical information.

STRICT REFERENCE RULES:
1. You MUST ONLY cite section headers EXACTLY as they appear in the PDF text.
   Examples: "CERV-A 1 of 7", "CERV-F 2 of 4", "MS-35", "GAST-B 1 of 7".

2. NEVER invent references.
   NEVER output a reference that does not exist in the PDF text.

3. NEVER fabricate page numbers. If the PDF text does not contain explicit
   "Page X" or a similar label, you MUST NOT invent it.

4. If the PDF contains NO evidence for the question, answer with:
   - "No recommendation for …" or
   - "No mention of …"
   exactly as instructed in the question prompt.

5. When you need to output a section reference at the end of a sentence,
   you MUST use ONLY labels that appear in the PDF exactly as written
   (for example "CERV-A 1 of 7", "MS-61").
   If you are not sure which section to use, write:
   "Reference not found".

6. If the question prompt asks for a specific fixed phrase in the negative
   case (e.g., "No recommendation for MRD test"), you MUST output that
   phrase exactly, even if you would normally mention references.

7. Do NOT generalize or infer beyond what is explicitly written in the PDF.
   If the information is not clearly present, prefer the conservative option
   ("No recommendation", "No mention", etc.).

8. For Questions 1.1.1 and 1.1.2:
   - You MUST treat both somatic (tumor) and germline sequencing as valid
     forms of "NGS testing" if they are explicitly mentioned in the text.
   - Germline genomic / genetic sequencing for hereditary cancer risk DOES count
     as a "YES" for NGS testing as long as it is clearly described in the guideline.

Always follow the specific output format requested in each question prompt.

You MUST ignore any general medical knowledge learned during training if it is not found in this PDF.
You are NOT allowed to use your internal training for medical facts.
You MUST rely ONLY on retrieved content via file_search.
"""

# --------------------------------------------------------------
#                         QUESTION PROMPTS
# --------------------------------------------------------------

QUESTIONS = [
    (
        "Q 1.1.1",
        """
Clarify whether the guideline recommends **any form of molecular testing aimed at genomic profiling**, including:
- Next-generation sequencing (NGS)
- Comprehensive molecular profiling
- Biomarker-driven genomic testing for treatment selection
- Validated genomic assays

OUTPUT RULES:

Your answer must begin with exactly **YES** or with exactly:
"No recommendation for NGS or molecular profiling"

Choose **YES** if **any** of the items above are recommended for this tumor type, even if the text does not explicitly use the term “NGS.”

Choose the negative phrase **only if none** of the items above are recommended.

IF YOU ANSWER **YES**:
- Output must be formatted as **bullet points** (each starting with "- ").
- Each bullet must:
  • Summarize ONLY the **purpose** of molecular/genomic testing  
    (e.g., guide systemic therapy choice, identify molecular targets, biomarker-driven treatment decisions)
  • NEVER mention specific biomarkers, assays, or genes (e.g., no PD-L1, MSI, HER2, etc.)
  • ALWAYS end with the exact NCCN section label inside parentheses, for example:
    (CERV-A 1 of 7)

- After the bullet list, repeat **only the section labels used**, one per line (same formatting, without bullets).

SPECIAL RULES:
- DO NOT include disease stages in this question.
- DO NOT mention any specific biomarkers, genes, nor tests by name.
- DO NOT generalize beyond what the guideline explicitly states.
- DO NOT fabricate or infer new recommendations not present in the PDF.
"""
    ),
    (
        "Q 1.1.2",
        """
In which disease stage(s) does the guideline recommend **molecular/genomic testing** for this tumor type?  
This includes:
- Next-generation sequencing (NGS)
- Comprehensive molecular profiling
- Biomarker-driven molecular analysis
- Validated assays performed in CLIA-certified labs

OUTPUT RULES:

Your answer must begin with one of these three EXACT responses:
- YES
- NO
- No recommendation for NGS or molecular profiling

Choose **YES** only if the guideline recommends ANY genomic/molecular testing for treatment decision-making.  
Choose **NO** only if explicit language rejects or advises against testing.  
Choose **“No recommendation for NGS or molecular profiling”** only if the guideline makes **no recommendation at all**.

IF YOU ANSWER **YES**:
- List ONLY disease stages (e.g., “metastatic”, “recurrent”, “locally advanced”).
- Provide the contextual reason exactly as the guideline phrases it, WITHOUT adding biomarkers or genetic assays.
- Each stage MUST end with the exact section label in parentheses.
  Example: Metastatic disease (CERV-A 1 of 7)

IMPORTANT RESTRICTIONS:
- DO NOT mention specific biomarkers.
- DO NOT describe testing methods.
- DO NOT provide clinical reasoning beyond the PDF.
- DO NOT reuse wording from Q 1.1.1.
"""
    ),
    (
        "Q 1.2",
        """
Please extract and list all biomarkers (gene + specific alteration or category)
that are explicitly or implicitly recommended in the text for testing with
next-generation sequencing (NGS), including cases where NGS is recommended as
part of comprehensive molecular profiling.

You MUST include for each biomarker:
- Biomarker name + specific alteration
- The subtype or disease setting where it applies
- NCCN Category of Evidence (e.g., Category 1, Category 2A)
- NCCN Category of Preference (e.g., Preferred, Useful in certain circumstances)
- The clinical context (e.g., first-line therapy, subsequent-line therapy)
- The exact section reference at the end

If no biomarkers associated with NGS, sequencing, or comprehensive profiling are mentioned,
output exactly:
"No biomarkers mentioned in the guideline".

Do NOT include biomarkers recommended solely for IHC, FISH, or PCR without connection to sequencing.
Output must be in BULLET POINT format (one biomarker per bullet).
"""
    ),
    (
        "Q 1.3",
        """
Is there a recommendation for PDL1 / MSI / TMB test?

The answer should look exactly like this template:

PDL1 -
MSI -
TMB -

For each line, complete the text according to the guideline.
"""
    ),
    (
        "Q 2",
        """
Does the guideline mention circulating tumor DNA (ctDNA) or circulating free DNA (cfDNA)?

NEW EXTRACTION PHILOSOPHY:
- We are NOT only interested in formal "recommendations".
- We want to extract ANY discussion, mention, comment, or limitation about ctDNA/cfDNA.

OUTPUT RULES:

1) If ctDNA/cfDNA is mentioned ANYWHERE in the text:
   - The answer must begin with the single word:
     YES
   - Then, output BULLET POINTS (each begins with "- ").
   - Each bullet should be a literal or minimally unified sentence from the guideline:
     • You MAY join broken lines,
     • You MUST NOT add new information that is not present in the text.
   - Focus on what the guideline actually says, for example:
     • clinical use
     • diagnostic or monitoring roles
     • limitations
     • “ctDNA preferred” versus tissue
   - Each bullet MUST end with at least one section reference in brackets.

2) If ctDNA/cfDNA is NOT mentioned anywhere in the guideline:
   - Output exactly (one line):
     "No mention of ctDNA or cfDNA."

3) REFERENCES:
   - References MUST be real section labels from the PDF (for example, BINV-Q 6 of 15, MS-76).
   - If you are unable to identify any valid section label, output:
     "Reference not found"
"""
    ),
    (
        "Q 3.1",
        """
Clarify if there is a recommendation for RNA sequencing or RNA-based NGS.

The answer should be one word only: "YES" if RNA sequencing is recommended
in any context, or "NO" if there is no mention of it.

If the answer is "YES":
- Summarize in what terms the guidelines recommend RNA testing.
- Each statement MUST end with the exact section reference.
"""
    ),
    (
        "Q 3.2",
        """
Please extract and list only the key biomarkers mentioned for RNA testing.
If RNA is not mentioned for a specific biomarker, DO NOT include it.

If no biomarkers are mentioned for RNA-based testing, output:
"No biomarkers mentioned for RNA testing."
"""
    ),
    (
        "Q 4",
        """
Is there a recommendation to use a CLIA-approved or CLIA-certified assay/lab?

If validation or CLIA is mentioned but NOT recommended,
output exactly:
"No mention of CLIA-certified or CLIA-approved testing."

If YES:
- Provide only ONE sentence from the guideline.
- Must end with the section reference(s) in brackets.
"""
    ),
    (
        "Q 5",
        """
Is there a recommendation for MRD (minimal residual disease)?

If MRD or "minimal residual disease" does NOT appear in the guideline,
output exactly:
"No recommendation for MRD test".

If YES:
- Summarize with short sentences.
- Each statement MUST end with the section reference.
"""
    ),
    (
        "Q 6",
        """
Is there any mention of the CTC (Circulating Tumor Cells) test?

If CTC is NOT mentioned anywhere in the guideline:
   "No recommendation/mention of CTC"

If YES:
- Summarize using BULLET POINTS.
- Each MUST end with a valid section reference.
"""
    ),
    (
        "Q 7",
        """
Does the guideline mention chemosensitivity tests, resistance tests,
or functional assays?

If NO, write exactly:
"No mention of chemosensitivity, resistance, or functional tests/assays."

If YES:
- Summarize briefly
- MUST include section reference(s).
"""
    ),
]
# ====================== LOG ======================
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# ====================== BUILD SYSTEM PROMPT ======================

def build_system_prompt(valid_refs):
    return (
        SYSTEM_INSTRUCTION
        + "\n\nValid section labels extracted from this PDF:\n"
        + "\n".join(f"- {r}" for r in valid_refs)
        + "\n\nYou MUST only use these section labels when you cite references.\n"
        + 'If you cannot find a suitable label, write: "Reference not found".'
    )

# ====================== VECTOR STORE ======================

def create_vector_store(pdf_path: str):
    cache = {}
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache = json.load(f)
        except Exception:
            cache = {}

    if pdf_path in cache:
        logging.info(f"Using cached vector store: {cache[pdf_path]}")
        return cache[pdf_path]

    logging.info("Creating new vector store…")
    vs = client.vector_stores.create(name=f"VS-{os.path.basename(pdf_path)}")

    logging.info("Uploading PDF to vector store…")
    with open(pdf_path, "rb") as fh:
        client.vector_stores.file_batches.upload_and_poll(
            vector_store_id=vs.id,
            files=[fh],
        )

    cache[pdf_path] = vs.id
    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(cache, f)

    return vs.id

# ====================== PDF UTILITIES ======================

def extract_valid_references(pdf_file: str):
    reader = PdfReader(pdf_file)
    text = ""
    for page in reader.pages:
        try:
            t = page.extract_text()
            if t:
                text += t + "\n"
        except:
            pass

    patterns = [
        r"[A-Z]{2,5}-[A-Z] \d+ of \d+",
        r"[A-Z]{2,5}-[A-Z]{1,3} \d+",
        r"MS-\d+",
    ]
    matches = set()
    for pat in patterns:
        matches.update(re.findall(pat, text))

    return sorted(matches), text

REF_PATTERN = r"[A-Z]{2,5}-[A-Z]{1,3}(?: \d+ of \d+|\s?\d+)"

def strip_internal_pdf_markers(ans: str) -> str:
    return re.sub(r"\[\d+:\d+†[^\]]+\]", "", ans)

def find_refs_near_terms(pdf_text: str, terms, window=3000):
    text_lower = pdf_text.lower()
    label_matches = list(re.finditer(REF_PATTERN, pdf_text))
    label_positions = [(m.start(), m.group(0)) for m in label_matches]
    hits = set()
    for term in terms:
        for m in re.finditer(term.lower(), text_lower):
            pos = m.start()
            best = None
            for lp, label in label_positions:
                if lp <= pos and (pos - lp) <= window:
                    best = label
                if lp > pos:
                    break
            if best:
                hits.add(best)
    return sorted(hits)

# ====================== SEMANTIC GUARDRAILS ======================

# ==========================================================
# 🚨 STRICT SEMANTIC GUARDRAILS (FINAL VERSION)
# Applies to ALL tumors and ALL NCCN guideline editions
# ==========================================================
def semantic_guardrail(qid: str, answer: str, pdf_text: str) -> str:
    # 🧽 CLEAN INTERNAL SEARCH MARKERS FIRST
    answer = strip_internal_pdf_markers(answer or "")
    txt = pdf_text.lower()

    # 💡 Safety helper: test literal text + avoid regex false positives
    def has_any(terms):
        return any(t.lower() in txt for t in [re.sub(r"\\b","",t) for t in terms])

    # =======================================================
    # 🧬 Q 1.1.1 + Q 1.1.2 — Recommendations for NGS/Molecular
    # =======================================================
    if qid in ("Q 1.1.1", "Q 1.1.2"):
        ngs_terms = [
            "ngs", "molecular profiling", "genomic", "genomic testing",
            "molecular testing", "comprehensive", "sequencing",
            "tumor sequencing", "germline sequencing", "somatic sequencing",
            "validated", "biomarker-driven"
        ]

        # Case A: Model invents a YES → convert to negative
        if answer.strip().lower().startswith("yes") and not has_any(ngs_terms):
            return "No recommendation for NGS or molecular profiling"

        # Case B: Validate references in distance window
        if answer.strip().lower().startswith("yes"):
            refs = re.findall(REF_PATTERN, answer)
            real_refs = []
            for ref in refs:
                try:
                    pos = pdf_text.index(ref)
                except ValueError:
                    continue
                window = txt[max(0, pos - WINDOW_SIZE): pos + WINDOW_SIZE]
                if has_any(ngs_terms) and any(k in window for k in ngs_terms):
                    real_refs.append(ref)

            # If NO valid references → force negative
            if not real_refs:
                return "No recommendation for NGS or molecular profiling"

            # Remove invented reference markers
            clean = re.sub(r"\(Reference not found\)", "", answer)
            return clean.strip()

        # Case C — If model returns NO but terms exist → inconsistent → override to YES
        if "no recommendation" in answer.lower() and has_any(ngs_terms):
            return "YES"

        return answer.strip()

    # =======================================================
    # 🧬 Q 1.2 — Biomarkers must be tied to NGS, not IHC/FISH
    # =======================================================
    if qid == "Q 1.2":
        ngs_terms = ["ngs", "sequencing", "molecular", "genomic", "profiling"]
        if not has_any(ngs_terms):
            return "No biomarkers mentioned in the guideline"
        # If answer contains no references → invalid extraction
        if not re.findall(REF_PATTERN, answer):
            return "No biomarkers mentioned in the guideline"
        return answer.strip()

    # =======================================================
    # 🧬 Q 1.3 — PD-L1 / MSI / TMB must NOT be invented
    # =======================================================
    if qid == "Q 1.3":
        # If key terms are missing → return full EMPTY template
        pd = "pdl1" in txt or "pd-l1" in txt or "pd l1" in txt
        ms = "msi" in txt or "dmmr" in txt or "mismatch" in txt
        tb = "tmb" in txt or "tumor mutational burden" in txt
        if not (pd or ms or tb):
            return "PDL1 -\nMSI -\nTMB -"
        return answer.strip()

    # =======================================================
    # 🧪 Q 2 — ctDNA / cfDNA cannot be inferred
    # =======================================================
    if qid == "Q 2":
        dna_terms = ["ctdna", "circulating tumor dna", "cfdna", "circulating free dna"]
        if not has_any(dna_terms):
            return "No mention of ctDNA or cfDNA."
        # If YES but NO references → force reference not found
        if answer.strip().lower().startswith("yes") and not re.findall(REF_PATTERN, answer):
            return answer.strip() + "\nReference not found"
        return answer.strip()

    # =======================================================
    # 🧬 Q 3.1 / Q 3.2 — RNA sequencing cannot be fabricated
    # =======================================================
    if qid == "Q 3.1":
        rna_terms = ["rna", "transcript", "fusion rna"]
        if not has_any(rna_terms):
            return "NO"
        return answer.strip()

    if qid == "Q 3.2":
        if "NO" in answer.upper():
            return "No biomarkers mentioned for RNA testing."
        return answer.strip()

    # =======================================================
    # 🧬 Q 4 — CLIA rules MUST be literal
    # =======================================================
    if qid == "Q 4":
        clia_terms = ["clia", "clinical laboratory improvement"]
        if not has_any(clia_terms):
            return "No mention of CLIA-certified or CLIA-approved testing."
        return answer.strip()

    # =======================================================
    # 🧬 Q 5 — MRD must appear literally or rejected
    # =======================================================
    if qid == "Q 5":
        if "mrd" not in txt and "minimal residual" not in txt:
            return "No recommendation for MRD test"
        return answer.strip()

    # =======================================================
    # 🧬 Q 6 — CTC mention must exist and be contextual
    # =======================================================
    if qid == "Q 6":
        ctc_terms = ["ctc", "circulating tumor cell"]
        if not has_any(ctc_terms):
            return "No recommendation/mention of CTC"
        return answer.strip()

    # =======================================================
    # 🧬 Q 7 — Chemosensitivity/Functional must be literal
    # =======================================================
    if qid == "Q 7":
        chemo_terms = ["chemosensitivity", "functional", "resistance assay", "organoid"]
        if not has_any(chemo_terms):
            return "No mention of chemosensitivity, resistance, or functional tests/assays."
        return answer.strip()

    # =======================================================
    # 🧾 Default → Only returned as-is after cleanup
    # =======================================================
    return answer.strip()



# ====================== ASK QUESTION ======================

def ask_question(vs_id, qid, prompt, system_prompt, valid_refs, pdf_text):
    try:
        resp = client.responses.create(
            model=MODEL_ID,
            max_output_tokens=2000,
            input=[{"role": "system", "content": system_prompt},
                   {"role": "user", "content": prompt}],
            tools=[{"type": "file_search", "vector_store_ids": [vs_id]}],
        )
        out = (resp.output_text or "").strip()
        return semantic_guardrail(qid, out, pdf_text)
    except Exception as e:
        return f"[ERROR] {e}"

# ====================== MAIN ======================

def main():
    pdf = PDF_FILE
    if len(sys.argv) >= 2:
        pdf = sys.argv[1]
    if not os.path.exists(pdf):
        print(f"ERROR: PDF file not found: {pdf}")
        sys.exit(1)

    start = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    stem = pathlib.Path(pdf).stem
    outfile = f"{stem}_results.txt"

    valid_refs, full_text = extract_valid_references(pdf)
    print("\n=== VALID REFERENCES FOUND ===")
    for r in valid_refs:
        print(r)
    print("====================================\n")

    sys_prompt = build_system_prompt(valid_refs)
    vs_id = create_vector_store(pdf)

    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(ask_question, vs_id, qid, q, sys_prompt, valid_refs, full_text): qid for (qid,q) in QUESTIONS}
        for f in concurrent.futures.as_completed(futs):
            results[futs[f]] = f.result()

    if results.get("Q 3.1", "").strip().upper() == "NO":
        results["Q 3.2"] = "No biomarkers mentioned for RNA testing."
    if "no recommendation for ngs" in results.get("Q 1.1.1", "").lower():
        results["Q 1.1.2"] = "No recommendation for NGS or molecular profiling"

    def sort_key(k): return [int(x) for x in re.sub(r"[^0-9\.]", "", k).split(".") if x] or [9999]
    sorted_items = sorted(results.items(), key=lambda x: sort_key(x[0]))

    with open(outfile, "w", encoding="utf-8") as f:
        f.write(f"Document: {pdf}\nModel: {MODEL_ID}\nStarted: {start}\n")
        f.write("-"*80 + "\n\n")
        for qid, ans in sorted_items:
            f.write(f"{qid}\n--------------------\n{ans}\n\n")

    print(f"\n🎉 DONE! Results saved to: {outfile}")

if __name__ == "__main__":
    main()