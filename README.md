# Telegram Large TXT File Splitter Bot

A production-ready Telegram Bot built using **Python 3.12** and **python-telegram-bot v22+** designed to parse and split large text files (up to 10GB programmatic threshold) using stream-processing patterns.

## Features
- **Strict Stream Processing**: Uses generator files reading pattern. Never executes `read()` or `readlines()`, preventing memory depletion (OOM) on high loads.
- **Immediate Upload / Cleanup**: Generates and uploads file chunks asynchronously, immediately deleting them from the system disk to operate safely on small system quotas.
- **Admin Access Layer**: Restricts usage to designated users by matching account details with IDs supplied inside environment variables.
- **Live Interrupt Capability**: `/stop` command gracefully ends a running process loop midway through execution.

## Configuration & Deployment on Railway

### 1. Locally Config & Setup
1. Clone your repository.
2. Initialize virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # Or .venv\Scripts\activate on Windows
