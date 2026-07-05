#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram “Railway‑Line‑Cleaner” Bot
-----------------------------------
Upload a .txt file, then use:

  /spl <N>      – split the file into N‑line chunks
  /ext <prefix> – extract all lines that start with the given digit string
  /clear        – keep only the first three pipe‑separated fields

All resulting files are sent only to the bot owner.
"""

import os
import tempfile
from pathlib import Path
import logging
import asyncio
from collections import defaultdict

from telegram import Update, InputFile
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)

# ------------------------------------------------------------------
# Configuration – replace these values!
# ------------------------------------------------------------------
BOT_TOKEN = "8811033165:AAG4NQszrJa3bP0Cgz-nuanE1g7RVVb2coA"          # <-- put your bot token here
OWNER_TELEGRAM_ID = 8665264271         # <-- put the owner's numeric ID here

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# In‑memory storage: chat_id -> Path to the last uploaded file
# ------------------------------------------------------------------
user_files: dict[int, Path] = defaultdict(lambda: None)

# ------------------------------------------------------------------
# Helper functions
# ------------------------------------------------------------------
async def send_to_owner(context: ContextTypes.DEFAULT_TYPE, file_path: Path, caption: str = ""):
    """Send a file from the bot to the owner."""
    try:
        with open(file_path, "rb") as fp:
            await context.bot.send_document(
                chat_id=OWNER_TELEGRAM_ID,
                document=InputFile(fp, filename=file_path.name),
                caption=caption,
            )
    except Exception as e:
        logger.error(f"Failed to send file to owner: {e}")

def split_file(file_path: Path, lines_per_chunk: int) -> list[Path]:
    """Split a file into multiple parts, each containing at most `lines_per_chunk` lines."""
    parts = []
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    total_lines = len(lines)
    for i in range(0, total_lines, lines_per_chunk):
        chunk_lines = lines[i:i + lines_per_chunk]
        part_path = file_path.with_name(f"{file_path.stem}_part_{i//lines_per_chunk + 1}.txt")
        with open(part_path, "w", encoding="utf-8") as p:
            p.writelines(chunk_lines)
        parts.append(part_path)
    return parts

def extract_prefix(file_path: Path, prefix: str) -> Path:
    """Return a new file containing only lines that start with the given prefix."""
    output_path = file_path.with_name(f"{file_path.stem}_ext_{prefix}.txt")
    with open(file_path, "r", encoding="utf-8") as src, \
         open(output_path, "w", encoding="utf-8") as dst:
        for line in src:
            if line.startswith(prefix):
                dst.write(line)
    return output_path

def clear_file(file_path: Path) -> Path:
    """Return a new file where each line keeps only the first three pipe‑separated fields."""
    output_path = file_path.with_name(f"{file_path.stem}_cleared.txt")
    with open(file_path, "r", encoding="utf-8") as src, \
         open(output_path, "w", encoding="utf-8") as dst:
        for line in src:
            parts = line.split("|")
            if len(parts) >= 3:
                dst.write("|".join(parts[:3]) + ("\n" if not line.endswith("\n") else ""))
            else:
                dst.write(line)  # keep line as‑is if not enough fields
    return output_path

# ------------------------------------------------------------------
# Handlers
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Hi! 👋\n\n"
        "Upload a file in .txt format and then use the following commands:\n\n"
        "/spl <N>      – split TXT file into N‑line parts.\n"
        "/ext <prefix> – extract lines that start with the given digit string.\n"
        "/clear        – keep only the first three pipe‑separated fields of every line.\n\n"
        "All processed files will be sent to the bot owner."
    )

async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming document uploads."""
    doc = update.message.document
    if not doc or not doc.file_name.lower().endswith(".txt"):
        await update.message.reply_text("Please send a .txt file.")
        return

    # Store file temporarily
    file_id = doc.file_id
    file = await context.bot.get_file(file_id)
    tmp_file = Path(tempfile.mktemp(suffix=".txt", prefix="upload_"))
    await file.download(custom_path=str(tmp_file))

    # Remember this file for the chat
    user_files[update.effective_chat.id] = tmp_file

    await update.message.reply_text("TXT file received successfully 🔥")

async def spl_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /spl <N> command."""
    chat_id = update.effective_chat.id
    user_file = user_files.get(chat_id)

    if not user_file or not user_file.exists():
        await update.message.reply_text("No file uploaded yet. Please send a .txt file first.")
        return

    # Parse number argument
    if not context.args:
        await update.message.reply_text("Usage: /spl <number_of_lines_per_part>")
        return

    try:
        n = int(context.args[0])
        if n <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("Please provide a positive integer.")
        return

    parts = split_file(user_file, n)
    await update.message.reply_text(f"Splitting into {len(parts)} parts…")
    for part in parts:
        await send_to_owner(context, part, caption=f"Part ({part.name})")
        part.unlink(missing_ok=True)  # clean up

async def ext_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /ext <prefix> command."""
    chat_id = update.effective_chat.id
    user_file = user_files.get(chat_id)

    if not user_file or not user_file.exists():
        await update.message.reply_text("No file uploaded yet. Please send a .txt file first.")
        return

    if not context.args:
        await update.message.reply_text("Usage: /ext <digit_prefix>")
        return

    prefix = context.args[0]
    if not prefix.isdigit():
        await update.message.reply_text("Prefix must consist only of digits.")
        return

    ext_file = extract_prefix(user_file, prefix)
    await update.message.reply_text(f"Extracted lines with prefix {prefix}…")
    await send_to_owner(context, ext_file, caption=f"Extracted lines for {prefix}")
    ext_file.unlink(missing_ok=True)

async def clear_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /clear command."""
    chat_id = update.effective_chat.id
    user_file = user_files.get(chat_id)

    if not user_file or not user_file.exists():
        await update.message.reply_text("No file uploaded yet. Please send a .txt file first.")
        return

    cleared_file = clear_file(user_file)
    await update.message.reply_text("Cleaning file…")
    await send_to_owner(context, cleared_file, caption="Cleaned file")
    cleared_file.unlink(missing_ok=True)

async def unknown_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle unknown commands."""
    await update.message.reply_text("Sorry, I didn't understand that command.")

# ------------------------------------------------------------------
# Main entry point
# ------------------------------------------------------------------
async def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Command handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("spl", spl_handler))
    app.add_handler(CommandHandler("ext", ext_handler))
    app.add_handler(CommandHandler("clear", clear_handler))

    # Document (file) handler
    app.add_handler(MessageHandler(filters.Document.ALL, document_handler))

    # Unknown commands
    app.add_handler(MessageHandler(filters.COMMAND, unknown_handler))

    # Run the bot until Ctrl‑C
    await app.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
