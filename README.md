# NCCN Guideline Intelligence Pipeline

## Overview

This project aims to automate the detection, analysis, and distribution of updates in NCCN clinical guidelines.

The goal is to transform a manual, reactive process into an automated and scalable system that provides timely and structured insights.

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
