#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram TXT Processing Bot
Version : 1.0
Author  : Devendra Gurjar
"""

# ==========================
# IMPORTS
# ==========================

import os
import re
import asyncio
import logging
import zipfile
import shutil

from pathlib import Path
from collections import defaultdict
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv

from telegram import (
    Update,
    InputFile,
)

from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# ==========================
# LOAD ENVIRONMENT
# ==========================

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_IDS = os.getenv("OWNER_IDS", "")

OWNER_IDS = [
    int(x.strip())
    for x in OWNER_IDS.split(",")
    if x.strip()
]

# ==========================
# CREATE FOLDERS
# ==========================

UPLOAD_FOLDER = Path("uploads")
OUTPUT_FOLDER = Path("outputs")
LOG_FOLDER = Path("logs")

UPLOAD_FOLDER.mkdir(exist_ok=True)
OUTPUT_FOLDER.mkdir(exist_ok=True)
LOG_FOLDER.mkdir(exist_ok=True)

# ==========================
# LOGGING
# ==========================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
    handlers=[
        RotatingFileHandler(
            LOG_FOLDER / "bot.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
        ),
        logging.StreamHandler(),
    ],
)

logger = logging.getLogger(__name__)

# ==========================
# GLOBAL STORAGE
# ==========================

saved_files = {}

processing = defaultdict(bool)

stop_flags = defaultdict(bool)

print("Bot Base Loaded Successfully...")
