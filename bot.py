#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram “Railway‑Line‑Cleaner” Bot – fully compliant with
Python 3.12+, python‑telegram‑bot v20.8+ and Railway deployment.

Features
--------
 • Stream‑based processing of TXT files up to 10 GB (no `read()` / `readlines()`).
 • Commands: /start, /help, /spl, /ext, /clear, /stop.
 • Multi‑user support – every user gets isolated uploads and outputs.
 • Automatic forwarding of the original file to all OWNER_IDS.
 • Progress updates, cancellation, error handling, and extensive logging.
 • No deprecated APIs – only `ApplicationBuilder` and `app.run_polling()`.
 • Environment‑variable based configuration (BOT_TOKEN, OWNER_IDS).
 • Auto‑creates `uploads/`, `outputs/` and `logs/` folders.
"""

# ------------------------------------------------------------------
# Imports
# ------------------------------------------------------------------
import asyncio
import os
import sys
import logging
import datetime
import uuid
import traceback
from pathlib import Path
from typing import Dict, Optional, List

from telegram import (
    Update,
    InputFile,
    File,
    Message,
    User,
    Chat,
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.error import TelegramError

# ------------------------------------------------------------------
# Configuration – read from environment
# ------------------------------------------------------------------
BOT_TOKEN: str | None = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is missing")

# OWNER_IDS can be comma‑separated string of integers
OWNER_IDS_ENV = os.getenv("OWNER_IDS", "")
if not OWNER_IDS_ENV:
    raise RuntimeError("OWNER_IDS environment variable is missing")
OWNER_IDS: List[int] = [int(x.strip()) for x in OWNER_IDS_ENV.split(",") if x.strip()]

# ------------------------------------------------------------------
# Directories
# ------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"
LOGS_DIR = BASE_DIR / "logs"

for d in (UPLOADS_DIR, OUTPUTS_DIR, LOGS_DIR):
    d.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------
# Logging configuration
# ------------------------------------------------------------------
logger = logging.getLogger("railway_bot")
logger.setLevel(logging.INFO)

# Formatter
fmt = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
formatter = logging.Formatter(fmt)

# Handlers
commands_handler = logging.handlers.RotatingFileHandler(
    LOGS_DIR / "commands.log", maxBytes=5 * 1024 * 1024, backupCount=5
)
commands_handler.setLevel(logging.INFO)
commands_handler.setFormatter(formatter)

errors_handler = logging.handlers.RotatingFileHandler(
    LOGS_DIR / "errors.log", maxBytes=5 * 1024 * 1024, backupCount=5
)
errors_handler.setLevel(logging.ERROR)
errors_handler.setFormatter(formatter)

crashes_handler = logging.handlers.RotatingFileHandler(
    LOGS_DIR / "crashes.log", maxBytes=5 * 1024 * 1024, backupCount=5
)
crashes_handler.setLevel(logging.CRITICAL)
crashes_handler.setFormatter(formatter)

for h in (commands_handler, errors_handler, crashes_handler):
    logger.addHandler(h)

# ------------------------------------------------------------------
# Helper utilities
# ------------------------------------------------------------------
def safe_int(value: str) -> Optional[int]:
    try:
        return int(value)
    except ValueError:
        return None


def format_bytes(b: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if b < 1024.0:
            return f"{b:3.1f}{unit}"
        b /= 1024.0
    return f"{b:.1f}PiB"


async def send_progress(update: Update, context: ContextTypes.DEFAULT_TYPE, progress: float):
    """Send a simple progress message (0–100%) to the user."""
    await update.message.reply_text(f"Progress: {progress:.1f}%")

async def forward_original(update: Update, context: ContextTypes.DEFAULT_TYPE, file_id: str):
    """Forward the original uploaded file to all OWNER_IDS with a caption."""
    user: User = update.effective_user
    chat: Chat = update.effective_chat
    file: File = context.bot.get_file(file_id)  # type: ignore
    caption = (
        f"📄 *File received*\n"
        f"• *User:* {user.first_name or ''} {user.last_name or ''} (@{user.username or 'N/A'})\n"
        f"• *User ID:* `{user.id}`\n"
        f"• *File:* `{file.file_path}`\n"
        f"• *Size:* {format_bytes(file.file_size)}\n"
        f"• *Uploaded:* {datetime.datetime.utcnow().isoformat()} UTC"
    )
    for owner_id in OWNER_IDS:
        try:
            await context.bot.send_document(
                chat_id=owner_id,
                document=InputFile(file_id),
                caption=caption,
                parse_mode="Markdown",
            )
        except TelegramError as exc:
            logger.error(f"Failed to forward file to owner {owner_id}: {exc}")


# ------------------------------------------------------------------
# Per‑user processing state
# ------------------------------------------------------------------
class UserState:
    def __init__(self, file_path: Path):
        self.file_path: Path = file_path
        self.task: Optional[asyncio.Task] = None
        self.cancel_event: asyncio.Event = asyncio.Event()


user_states: Dict[int, UserState] = {}


# ------------------------------------------------------------------
# Command handlers
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 *Welcome!*\n\n"
        "Upload a .txt file and use the following commands:\n\n"
        "/spl <lines>   – split the file into parts of N lines\n"
        "/ext <prefix>  – keep only lines starting with the digit prefix\n"
        "/clear         – keep only the first four pipe‑separated fields\n"
        "/stop          – cancel any ongoing processing\n\n"
        "The bot will automatically forward the original file to the owners."
    )
    logger.info(f"User {update.effective_user.id} used /start")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)  # same help text
    logger.info(f"User {update.effective_user.id} used /help")


# ------------------------------------------------------------------
# File upload handler
# ------------------------------------------------------------------
async def document_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc: Message = update.message  # type: ignore
    if not doc.document:
        return

    filename = doc.document.file_name
    if not filename.lower().endswith(".txt"):
        await update.message.reply_text("❌ Only .txt files are accepted.")
        return

    # Prevent too large uploads (optional limit)
    if doc.document.file_size > 10 * 1024 * 1024 * 1024:  # 10 GB
        await update.message.reply_text("❌ File is larger than 10 GB – not allowed.")
        return

    # Create a unique local file name
    unique_name = f"{uuid.uuid4().hex}_{filename}"
    local_path = UPLOADS_DIR / unique_name

    try:
        # Download file
        await context.bot.get_file(doc.document.file_id)  # ensure file is ready
        await context.bot.get_file(doc.document.file_id).download(custom_path=str(local_path))
    except TelegramError as exc:
        await update.message.reply_text(f"❌ Error downloading file: {exc}")
        logger.error(f"Download error for user {update.effective_user.id}: {exc}")
        return

    # Store state
    user_states[update.effective_chat.id] = UserState(local_path)

    await update.message.reply_text(
        f"✅ File *{filename}* received ({format_bytes(doc.document.file_size)})."
    )
    logger.info(f"User {update.effective_user.id} uploaded file {filename}")

    # Forward original file to owners
    await forward_original(update, context, doc.document.file_id)


# ------------------------------------------------------------------
# Cancellation helper
# ------------------------------------------------------------------
async def cancel_current_task(chat_id: int):
    state = user_states.get(chat_id)
    if not state or not state.task:
        return False
    state.cancel_event.set()
    try:
        await state.task
    except asyncio.CancelledError:
        pass
    except Exception as exc:
        logger.error(f"Error while cancelling task: {exc}")
    finally:
        state.task = None
        state.cancel_event.clear()
    return True


# ------------------------------------------------------------------
# /stop command
# ------------------------------------------------------------------
async def stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    cancelled = await cancel_current_task(chat_id)
    if cancelled:
        await update.message.reply_text("🚫 Operation cancelled.")
        logger.info(f"User {update.effective_user.id} cancelled current task.")
    else:
        await update.message.reply_text("⚠️ No active operation to cancel.")
        logger.info(f"User {update.effective_user.id} tried to cancel but none running.")


# ------------------------------------------------------------------
# /spl command
# ------------------------------------------------------------------
async def spl_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Usage: /spl <number_of_lines_per_part>")
        return

    lines_per_part = safe_int(context.args[0])
    if not lines_per_part or lines_per_part <= 0:
        await update.message.reply_text("❌ Please provide a positive integer.")
        return

    state = user_states.get(chat_id)
    if not state:
        await update.message.reply_text("❌ No file uploaded yet.")
        return

    if state.task:
        await update.message.reply_text("⚠️ Another operation is already running.")
        return

    # Run processing in a background task
    state.task = asyncio.create_task(
        process_spl(update, context, state, lines_per_part)
    )
    await update.message.reply_text(f"🚀 Splitting into parts of {lines_per_part} lines…")
    logger.info(f"User {update.effective_user.id} started /spl {lines_per_part}")


async def process_spl(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state: UserState,
    lines_per_part: int,
):
    file_path = state.file_path
    total_size = os.path.getsize(file_path)
    processed_bytes = 0
    next_progress = 5  # next percentage to report
    part_num = 1

    output_prefix = file_path.stem  # keep original base name
    output_suffix = f"_part_{part_num}"
    output_file = OUTPUTS_DIR / f"{output_prefix}{output_suffix}.txt"

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as src, \
             open(output_file, "w", encoding="utf-8") as dst:
            line_count = 0
            for line in src:
                if state.cancel_event.is_set():
                    logger.info("Splitting cancelled by user.")
                    return

                dst.write(line)
                line_count += 1
                processed_bytes += len(line.encode("utf-8"))

                # Progress reporting
                if processed_bytes * 100 // total_size >= next_progress:
                    await send_progress(update, context, processed_bytes * 100 / total_size)
                    next_progress += 5

                if line_count >= lines_per_part:
                    dst.close()
                    # Forward part to owners
                    await forward_output_file(
                        update, context, output_file.name, output_file
                    )
                    part_num += 1
                    output_file = OUTPUTS_DIR / f"{output_prefix}_part_{part_num}.txt"
                    dst = open(output_file, "w", encoding="utf-8")

            # Final part
            dst.close()
            await forward_output_file(update, context, output_file.name, output_file)

    except Exception as exc:
        logger.error(f"Error during /spl: {exc}\n{traceback.format_exc()}")
        await update.message.reply_text(f"❌ Error during splitting: {exc}")
    finally:
        # Clean up local upload
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        state.task = None
        state.cancel_event.clear()


# ------------------------------------------------------------------
# /ext command
# ------------------------------------------------------------------
async def ext_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text("Usage: /ext <digit_prefix>")
        return

    prefix = context.args[0]
    if not prefix.isdigit():
        await update.message.reply_text("❌ Prefix must be digits only.")
        return

    state = user_states.get(chat_id)
    if not state:
        await update.message.reply_text("❌ No file uploaded yet.")
        return

    if state.task:
        await update.message.reply_text("⚠️ Another operation is already running.")
        return

    state.task = asyncio.create_task(
        process_ext(update, context, state, prefix)
    )
    await update.message.reply_text(f"🚀 Extracting lines that start with \"{prefix}\"…")
    logger.info(f"User {update.effective_user.id} started /ext {prefix}")


async def process_ext(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    state: UserState,
    prefix: str,
):
    file_path = state.file_path
    total_size = os.path.getsize(file_path)
    processed_bytes = 0
    next_progress = 5
    output_file = OUTPUTS_DIR / f"{file_path.stem}_ext_{prefix}.txt"

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as src, \
             open(output_file, "w", encoding="utf-8") as dst:
            for line in src:
                if state.cancel_event.is_set():
                    logger.info("Extraction cancelled by user.")
                    return

                if line.lstrip().startswith(prefix):
                    dst.write(line)

                processed_bytes += len(line.encode("utf-8"))

                if processed_bytes * 100 // total_size >= next_progress:
                    await send_progress(update, context, processed_bytes * 100 / total_size)
                    next_progress += 5

        await forward_output_file(update, context, output_file.name, output_file)

    except Exception as exc:
        logger.error(f"Error during /ext: {exc}\n{traceback.format_exc()}")
        await update.message.reply_text(f"❌ Error during extraction: {exc}")
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        state.task = None
        state.cancel_event.clear()


# ------------------------------------------------------------------
# /clear command
# ------------------------------------------------------------------
async def clear_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    state = user_states.get(chat_id)
    if not state:
        await update.message.reply_text("❌ No file uploaded yet.")
        return

    if state.task:
        await update.message.reply_text("⚠️ Another operation is already running.")
        return

    state.task = asyncio.create_task(process_clear(update, context, state))
    await update.message.reply_text("🚀 Cleaning file (keeping first four pipe fields)…")
    logger.info(f"User {update.effective_user.id} started /clear")


async def process_clear(update: Update, context: ContextTypes.DEFAULT_TYPE, state: UserState):
    file_path = state.file_path
    total_size = os.path.getsize(file_path)
    processed_bytes = 0
    next_progress = 5
    output_file = OUTPUTS_DIR / f"{file_path.stem}_cleared.txt"

    try:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as src, \
             open(output_file, "w", encoding="utf-8") as dst:
            for line in src:
                if state.cancel_event.is_set():
                    logger.info("Clear cancelled by user.")
                    return

                parts = line.split("|")
                if len(parts) >= 4:
                    cleaned = "|".join(parts[:4]) + ("\n" if not line.endswith("\n") else "")
                    dst.write(cleaned)
                else:
                    dst.write(line)

                processed_bytes += len(line.encode("utf-8"))

                if processed_bytes * 100 // total_size >= next_progress:
                    await send_progress(update, context, processed_bytes * 100 / total_size)
                    next_progress += 5

        await forward_output_file(update, context, output_file.name, output_file)

    except Exception as exc:
        logger.error(f"Error during /clear: {exc}\n{traceback.format_exc()}")
        await update.message.reply_text(f"❌ Error during cleaning: {exc}")
    finally:
        try:
            file_path.unlink(missing_ok=True)
        except Exception:
            pass
        state.task = None
        state.cancel_event.clear()


# ------------------------------------------------------------------
# Helper to forward processed file to owners
# ------------------------------------------------------------------
async def forward_output_file(update: Update, context: ContextTypes.DEFAULT_TYPE, filename: str, file_path: Path):
    chat: Chat = update.effective_chat
    caption = (
        f"📤 *Processed file*\n"
        f"• *Original:* `{chat.title or chat.first_name}`\n"
        f"• *File:* `{filename}`\n"
        f"• *Size:* {format_bytes(file_path.stat().st_size)}"
    )
    for owner_id in OWNER_IDS:
        try:
            await context.bot.send_document(
                chat_id=owner_id,
                document=InputFile(file_path),
                caption=caption,
                parse_mode="Markdown",
            )
        except TelegramError as exc:
            logger.error(f"Failed to forward processed file to owner {owner_id}: {exc}")

    # Clean up processed file
    try:
        file_path.unlink(missing_ok=True)
    except Exception:
        pass


# ------------------------------------------------------------------
# Unhandled exception hook – log crashes
# ------------------------------------------------------------------
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logger.critical("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))


sys.excepthook = handle_exception


# ------------------------------------------------------------------
# Main application
# ------------------------------------------------------------------
app = ApplicationBuilder().token(BOT_TOKEN).build()

# Handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(CommandHandler("help", help_cmd))
app.add_handler(CommandHandler("spl", spl_cmd))
app.add_handler(CommandHandler("ext", ext_cmd))
app.add_handler(CommandHandler("clear", clear_cmd))
app.add_handler(CommandHandler("stop", stop_cmd))
app.add_handler(MessageHandler(filters.Document.ALL, document_handler))

# Run the bot – Railway compatible
if __name__ == "__main__":
    app.run_polling()
