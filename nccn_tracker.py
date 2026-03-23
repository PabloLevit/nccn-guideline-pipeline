from __future__ import annotations

from pathlib import Path
import json
import re
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import requests
from bs4 import BeautifulSoup
import logging


# ============================================================
# PATHS
# ============================================================
BASE_DIR = Path(__file__).parent
OUTDIR = BASE_DIR / "nccn_tracker_output"
OUTDIR.mkdir(parents=True, exist_ok=True)

VERSIONS_FILE = OUTDIR / "nccn_versions.json"
LOG_FILE = OUTDIR / "nccn_tracker_simple.log"

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[logging.FileHandler(str(LOG_FILE), encoding="utf-8"), logging.StreamHandler()],
)
log = logging.getLogger("nccn_tracker_simple")

# ============================================================
# SECRETS
# ============================================================
SECRETS_PATH = BASE_DIR / "secrets.json"
with open(SECRETS_PATH, "r", encoding="utf-8") as f:
    secrets = json.load(f)

SMTP_USER = secrets["SMTP_USER"]
SMTP_PASS = secrets["SMTP_PASS"]
SMTP_RECIPIENTS = secrets.get("SMTP_RECIPIENTS", [SMTP_USER])
if isinstance(SMTP_RECIPIENTS, str):
    SMTP_RECIPIENTS = [SMTP_RECIPIENTS]

# ============================================================
# EMAIL
# ============================================================
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587


def send_email(subject: str, body_html: str) -> None:
    msg = MIMEMultipart()
    msg["From"] = SMTP_USER
    msg["To"] = ", ".join(SMTP_RECIPIENTS)
    msg["Subject"] = subject
    msg.attach(MIMEText(body_html, "html", "utf-8"))

    with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, SMTP_RECIPIENTS, msg.as_string())

    log.info("📨 Email sent to: " + ", ".join(SMTP_RECIPIENTS))


# ============================================================
# NCCN SCRAPE (Category 1)
# ============================================================
BASE_URL = "https://www.nccn.org"
CATEGORY_1_URL = f"{BASE_URL}/guidelines/category_1"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def parse_category1_versions(html: str) -> dict[str, str]:
    """
    Returns: { guideline_title: version_string }
    """
    soup = BeautifulSoup(html, "html.parser")
    items: list[tuple[str, str]] = []

    for block in soup.select("div.item-name"):
        a_tag = block.find("a", href=True)
        if not a_tag:
            continue

        title = a_tag.get_text(strip=True)
        if "Patient" in title:
            continue

        version_div = block.find_next_sibling("div", class_="item-version")
        version = "N/A"
        if version_div:
            m = re.search(r"Version[:\s]*([\d.]+)", version_div.get_text())
            if m:
                version = m.group(1)

        items.append((title, version))

    # Deduplicate by title (keep first occurrence)
    versions: dict[str, str] = {}
    for title, version in items:
        versions.setdefault(title, version)

    return versions


def load_old_versions() -> dict[str, str]:
    if not VERSIONS_FILE.exists():
        return {}
    try:
        txt = VERSIONS_FILE.read_text(encoding="utf-8").strip()
        return json.loads(txt) if txt else {}
    except Exception:
        log.warning("⚠️ nccn_versions.json is corrupted — resetting.")
        return {}


def save_versions(versions: dict[str, str]) -> None:
    VERSIONS_FILE.write_text(json.dumps(versions, indent=2, ensure_ascii=False), encoding="utf-8")


def build_email_html(timestamp, updates):
    if updates:
        items = "".join(
            f"<li>{u['name']} — {u['old']} → {u['new']}</li>"
            for u in updates
        )
        return f"""
        <p><strong>NCCN Guidelines Update</strong></p>
        <p>Date: {timestamp}<br>
        Status: <strong style='color:#c0392b;'>Updates detected</strong></p>
        <ul>{items}</ul>
        <p style='font-size:12px;color:#666;'>Automated NCCN Category 1 monitoring.</p>
        """
    else:
        return f"""
        <p><strong>NCCN Guidelines Update</strong></p>
        <p>Date: {timestamp}<br>
        Status: <strong style='color:#27ae60;'>No updates detected</strong></p>
        <p style='font-size:12px;color:#666;'>Automated NCCN Category 1 monitoring.</p>
        """


def main() -> None:
    try:
        log.info("🚀 NCCN Tracker (simple) started.")

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
        old_versions = load_old_versions()

        resp = requests.get(CATEGORY_1_URL, headers=HEADERS, timeout=45)
        resp.raise_for_status()

        current_versions = parse_category1_versions(resp.text)

        updates: list[dict] = []
        for name, new_ver in current_versions.items():
            old_ver = old_versions.get(name)
            if old_ver is not None and old_ver != new_ver:
                updates.append({"name": name, "old": old_ver, "new": new_ver})

        # Save latest snapshot no matter what (so next run compares against it)
        save_versions(current_versions)

        # Email
        subject = f"NCCN Tracker — {len(updates)} Updates Detected ({len(current_versions)} Guidelines Total)"
        body_html = build_email_html(timestamp, updates)

        send_email(subject, body_html)

        log.info("🏁 NCCN Tracker (simple) finished successfully.")

    except Exception as e:
        log.exception("💥 NCCN Tracker (simple) crashed")
        # best-effort error email
        try:
            send_email(
                subject="NCCN Tracker — ERROR (simple tracker crashed)",
                body_html=f"<p><strong>Script crashed.</strong></p><pre>{str(e)}</pre>",
            )
        except Exception:
            pass
        raise


if __name__ == "__main__":
    main()
