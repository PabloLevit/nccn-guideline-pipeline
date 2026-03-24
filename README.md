# NCCN Guideline Intelligence Pipeline

## Overview

This project aims to automate the detection, analysis, and distribution of updates in NCCN clinical guidelines.

The goal is to transform a manual, reactive process into an automated and scalable system that provides timely and structured insights.

## Configuration  'IMPORTANT'

This project requires environment-specific configuration (e.g., email credentials).

For security reasons, sensitive files such as `secrets.json` are not included in this repository.

To run the tracker, you will need to create your own configuration file with the required credentials.

## System Architecture

The pipeline is composed of three layers:

### 1. NCCN Tracker (Detection Layer)
A Python script that:
- monitors NCCN guideline updates
- detects version changes
- sends an automated email notification

### 2. n8n Workflow (Orchestration Layer)
A visual workflow that:
- listens to tracker emails
- parses which guidelines were updated
- decides whether to trigger analysis
- manages retries and execution flow
- logs and monitors each run

### 3. Analysis Engine (Backend - this repository)
This repository contains the core logic to:
- compare guideline versions
- extract relevant differences
- generate structured outputs

-------------------------
## How to Run

1. Install dependencies:
pip install -r requirements.txt

2. Run the NCCN tracker:
python nccn_tracker.py

3. Run the analysis module (example):
python analyze_doc.py

---

## Orchestration (n8n)

The orchestration layer is implemented externally using n8n and is not included in this repository.

It is responsible for:

- listening to tracker email notifications  
- parsing which NCCN guidelines were updated  
- deciding whether to trigger analysis  
- managing execution flow and retries  
- monitoring job status  
- logging results  
- sending notifications to the team  

---

## Example Output

The system is designed to generate structured summaries of NCCN guideline updates, including:

- changes in biomarker recommendations  
- updates in NGS / molecular profiling guidance  
- modifications in targeted therapies or immunotherapy  
- staging updates  
- newly introduced or removed clinical recommendations  

These outputs can be formatted as:

- structured summaries (text)  
- JSON objects  
- Excel tables  
- or integrated into a centralized knowledge base  

(Example outputs will be added in future versions.)

--------------------------------------

## Repository Structure

- `analyze_doc.py` → core analysis logic  
- `runner_api.py` → API layer for triggering analysis  
- `nccn_tracker.py` → detection script (local execution)  
- `ANCHOR_MAP.json` → parsing reference  
- `tumor_map.json` → tumor classification mapping  
- `requirements.txt` → dependencies  

## Current Status

- NCCN update detection: ✅ implemented  
- Automated email notification: ✅ implemented  
- n8n orchestration: 🔄 in progress  
- automated analysis engine: 🔄 in development  

## Future Goals

- extract clinically relevant changes (NGS, biomarkers, therapies)
- generate structured reports (JSON / Excel / summaries)
- build a centralized knowledge base of NCCN updates
- enable scalable monitoring across all guideline types

## Notes

This repository focuses on the analysis layer and is designed to integrate with external orchestration (n8n) and detection components.

## Author

Pablo Levit

## Workflow
