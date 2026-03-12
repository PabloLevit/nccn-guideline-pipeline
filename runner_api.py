from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from pathlib import Path
import subprocess
import datetime
import uuid
import json
import sys
import os

app = FastAPI(title="NCCN Analysis Runner", version="1.0")

BASE_DIR = Path(__file__).resolve().parent

JOBS_DIR = Path(os.getenv("JOBS_DIR", str(BASE_DIR / "_jobs"))).resolve()
PDF_DIR = Path(os.getenv("PDF_GUIDELINES_DIR", str(BASE_DIR / "PDF Guidelines"))).resolve()
OUT_DIR = Path(os.getenv("OUT_DIR", str(BASE_DIR / "update_reports"))).resolve()
EXCEL_PATH = Path(
    os.getenv("EXCEL_PATH", str(BASE_DIR / "data" / "NCCN_NGS_recommendations_2025_SANDBOX.xlsx"))
).resolve()
ANALYZE_SCRIPT = Path(os.getenv("ANALYZE_SCRIPT", str(BASE_DIR / "analyze_doc.py"))).resolve()

JOBS_DIR.mkdir(parents=True, exist_ok=True)
OUT_DIR.mkdir(parents=True, exist_ok=True)


class RunRequest(BaseModel):
    pdf: str
    tumor: str | None = None


def _job_path(job_id: str) -> Path:
    return JOBS_DIR / f"{job_id}.json"


def _write(job_id: str, data: dict) -> None:
    _job_path(job_id).write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _read(job_id: str) -> dict:
    p = _job_path(job_id)
    if not p.exists():
        return {"status": "NOT_FOUND", "job_id": job_id}
    return json.loads(p.read_text(encoding="utf-8"))


@app.get("/")
def root():
    return {
        "service": "nccn-analysis-runner",
        "status": "ok"
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "analyze_script_exists": ANALYZE_SCRIPT.exists(),
        "pdf_dir_exists": PDF_DIR.exists(),
        "excel_exists": EXCEL_PATH.exists(),
        "jobs_dir": str(JOBS_DIR),
        "out_dir": str(OUT_DIR),
    }


@app.post("/check-updates")
def check_updates():
    # Por ahora sigue mock.
    # Más adelante, si querés, este endpoint puede leer lo parseado desde Gmail/n8n
    return {
        "checked_at": datetime.datetime.now().isoformat(),
        "updates_detected": False,
        "updated_guidelines": [],
        "total_guidelines": 69
    }


@app.post("/run-nccn", status_code=202)
def run_nccn(req: RunRequest):
    if not ANALYZE_SCRIPT.exists():
        raise HTTPException(status_code=500, detail=f"Missing analyze script: {ANALYZE_SCRIPT}")

    job_id = str(uuid.uuid4())

    job_data = {
        "job_id": job_id,
        "status": "RUNNING",
        "pdf": req.pdf,
        "tumor": req.tumor or "",
        "started_at": datetime.datetime.now().isoformat(),
        "worker_python": sys.executable,
        "worker_version": sys.version,
    }
    _write(job_id, job_data)

    py = sys.executable

    code = f"""
import subprocess, json, datetime, sys
from pathlib import Path

job_path = Path(r"{str(_job_path(job_id))}")
analyze_script = Path(r"{str(ANALYZE_SCRIPT)}")
pdf_dir = Path(r"{str(PDF_DIR)}")
excel_path = Path(r"{str(EXCEL_PATH)}")
out_dir = Path(r"{str(OUT_DIR)}")
base_dir = Path(r"{str(BASE_DIR)}")

data = json.loads(job_path.read_text(encoding="utf-8"))
pdf = data["pdf"]
tumor = data.get("tumor") or ""

cmd = [
    sys.executable,
    str(analyze_script),
    "--pdf", pdf,
    "--pdf-dir", str(pdf_dir),
    "--excel", str(excel_path),
    "--out-dir", str(out_dir),
]

if tumor:
    cmd.extend(["--tumor", tumor])

p = subprocess.run(
    cmd,
    capture_output=True,
    text=True,
    cwd=str(base_dir)
)

data["finished_at"] = datetime.datetime.now().isoformat()
data["returncode"] = p.returncode
data["stdout"] = (p.stdout or "")[-20000:]
data["stderr"] = (p.stderr or "")[-20000:]
data["status"] = "DONE" if p.returncode == 0 else "ERROR"

job_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
"""

    subprocess.Popen([py, "-c", code], cwd=str(BASE_DIR))

    return {"job_id": job_id, "status": "RUNNING"}


@app.get("/jobs/{job_id}")
def get_job(job_id: str):
    return _read(job_id)