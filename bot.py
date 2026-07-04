---

### 3. `bot.py`
This is the main bot file. It handles file streams, cooperative cancellation, owner forwards, and concurrent update delivery.
```python
import os
import re
import shutil
import logging
import asyncio
import zipfile
from logging.handlers import RotatingFileHandler

from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    Application,
    MessageHandler,
    filters,
    ContextTypes,
)

# Load environment variables
load_dotenv()

# Setup logging
os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        RotatingFileHandler("logs/bot.log", maxBytes=5 * 1024 * 1024, backupCount=2),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# System Directories Initialization
for directory in ["uploads", "outputs", "logs"]:
    os.makedirs(directory, exist_ok=True)

# Parse Environment Variables
BOT_TOKEN = os.getenv("8811033165:AAG4NQszrJa3bP0Cgz-nuanE1g7RVVb2coA")
OWNER_IDS = []
owner_env = os.getenv("8665264271")
if owner_env:
    for oid in owner_env.split(','):
        try:
            OWNER_IDS.append(int(oid.strip()))
        except ValueError:
            logger.warning(f"Invalid Owner ID skipped: {oid}")

# In-Memory Concurrency state management
is_processing = {}
cancellation_flags = {}


class ProcessCancelledException(Exception):
    """Exception raised when processing is aborted via /stop."""
    pass


def format_size(size_bytes: int) -> str:
    """Formats file size into human-readable representation."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes / (1024 * 1024):.2f} MB"


async def count_lines(file_path: str) -> int:
    """
    Counts total lines in a file asynchronously and efficiently.
    Uses buffered reading in C-level loop chunks to prevent RAM bloat.
    """
    def sync_count():
        count = 0
        try:
            with open(file_path, 'rb') as f:
                # Read 1MB chunks to count newline markers efficiently
                buf_size = 1024 * 1024
                read_generator = iter(lambda: f.read(buf_size), b"")
                count = sum(buffer.count(b'\n') for buffer in read_generator)
        except Exception as e:
            logger.error(f"Error counting lines for file {file_path}: {e}")
        return count

    return await asyncio.to_thread(sync_count)


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes /start action."""
    user = update.effective_user
    username_or_name = f"@{user.username}" if user.username else user.first_name
    await update.message.reply_text(
        f"Hello {username_or_name}!\n\n"
        f"Upload a file in .txt format ⚡"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes /help action."""
    help_text = (
        "💡 *How to use the TXT Splitter Bot:*\n\n"
        "1️⃣ *Upload a TXT File:* Send any `.txt` file.\n\n"
        "2️⃣ *Choose an action:*\n"
        "🔹 `/spl <N>` or `/splN` — Splits your uploaded TXT file into files containing `N` lines each. (e.g., `/spl 5000` or `/spl5000`)\n"
        "🔹 `/ext <prefix>` or `/ext<prefix>` — Extracts lines starting with your input prefix. (e.g., `/ext 4960` or `/ext4960`)\n"
        "🔹 `/clear` — Cleans formatted lists, keeping only the first 4 fields (CARD|MM|YY|CVV).\n"
        "🔹 `/stop` — Gracefully stops an ongoing process.\n"
        "🔹 `/help` — Show this instruction message again.\n\n"
        "⚠️ _Note: All processes run isolated. File safety is maintained using unique identifiers._"
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")


async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes /stop action."""
    user_id = update.effective_user.id
    if is_processing.get(user_id, False):
        cancellation_flags[user_id] = True
        await update.message.reply_text("🛑 Cancellation request received. Stopping process shortly...")
    else:
        await update.message.reply_text("ℹ️ No active process is running to stop.")


async def spl_command(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_text: str):
    """Executes /spl action."""
    user_id = update.effective_user.id

    # Parse numeric parameter
    match = re.match(r'^/spl\s*(\d+)$', raw_text, re.IGNORECASE)
    if not match:
        await update.message.reply_text(
            "❌ Invalid command usage.\n\n"
            "Please specify lines per file. Example:\n"
            "👉 `/spl 100` or `/spl100` (where 100 is the number of lines per file)",
            parse_mode="Markdown"
        )
        return

    lines_per_file = int(match.group(1))
    if lines_per_file <= 0:
        await update.message.reply_text("❌ Split boundary must be a positive integer.")
        return

    input_path = f"uploads/{user_id}.txt"
    if not os.path.exists(input_path):
        await update.message.reply_text("❌ No TXT file uploaded yet. Please upload a .txt file first.")
        return

    if is_processing.get(user_id, False):
        await update.message.reply_text("⚠️ A process is already running. Use /stop to cancel it first.")
        return

    is_processing[user_id] = True
    cancellation_flags[user_id] = False

    user_output_dir = f"outputs/{user_id}_split"
    zip_path = f"outputs/{user_id}_split_parts.zip"

    try:
        total_lines = await count_lines(input_path)
        if total_lines == 0:
            await update.message.reply_text("❌ The uploaded TXT file is empty.")
            return

        files_to_create = (total_lines + lines_per_file - 1) // lines_per_file

        status_msg = await update.message.reply_text(
            f"🚀 *Processing Started*\n\n"
            f"📊 *Total Lines:* {total_lines}\n"
            f"📄 *Lines Per File:* {lines_per_file}\n"
            f"📁 *Files To Create:* {files_to_create}\n\n"
            f"⏳ *Processing...*",
            parse_mode="Markdown"
        )

        # Re-initialize output directory
        if os.path.exists(user_output_dir):
            shutil.rmtree(user_output_dir)
        os.makedirs(user_output_dir, exist_ok=True)

        if os.path.exists(zip_path):
            os.remove(zip_path)

        part_index = 1
        current_line_count = 0
        out_file = None

        # Process file using asynchronous generators patterns
        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f_in:
            for line in f_in:
                if cancellation_flags.get(user_id, False):
                    raise ProcessCancelledException()

                if out_file is None:
                    part_path = os.path.join(user_output_dir, f"{user_id}_part_{part_index}.txt")
                    out_file = open(part_path, 'w', encoding='utf-8')

                out_file.write(line)
                current_line_count += 1

                if current_line_count % lines_per_file == 0:
                    out_file.close()
                    out_file = None
                    part_index += 1

                # Yield control to Python event loop every 2000 lines to keep bot responsive to /stop
                if current_line_count % 2000 == 0:
                    await asyncio.sleep(0.001)

        if out_file is not None:
            out_file.close()

        generated_files = sorted(os.listdir(user_output_dir))
        total_created = len(generated_files)

        if total_created == 0:
            await status_msg.edit_text("❌ Splitting yielded zero files.")
            return

        await status_msg.edit_text("✅ *Processing Finished!* Delivering output...", parse_mode="Markdown")

        # Select individual delivery or unified ZIP delivery based on volume
        if total_created <= 5:
            for fname in generated_files:
                fpath = os.path.join(user_output_dir, fname)
                with open(fpath, 'rb') as doc_payload:
                    await update.message.reply_document(
                        document=doc_payload,
                        filename=fname,
                        caption=f"📂 Split segment: {fname.split('_')[-1]}"
                    )
        else:
            with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for fname in generated_files:
                    fpath = os.path.join(user_output_dir, fname)
                    zipf.write(fpath, arcname=fname)

            with open(zip_path, 'rb') as zip_payload:
                await update.message.reply_document(
                    document=zip_payload,
                    filename=f"{user_id}_split_parts.zip",
                    caption=f"✅ Created {total_created} files.\n\n📦 Package structured inside single ZIP archive."
                )

    except ProcessCancelledException:
        await update.message.reply_text("❌ Splitting execution cancelled.")
    except Exception as e:
        logger.error(f"Error handling spl command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("❌ An unexpected structural error occurred while executing the split action.")
    finally:
        # Cleanup temporary outputs
        if os.path.exists(user_output_dir):
            shutil.rmtree(user_output_dir)
        if os.path.exists(zip_path):
            try:
                os.remove(zip_path)
            except OSError:
                pass
        is_processing[user_id] = False
        cancellation_flags[user_id] = False


async def ext_command(update: Update, context: ContextTypes.DEFAULT_TYPE, raw_text: str):
    """Executes /ext action."""
    user_id = update.effective_user.id

    # Parse prefix parameter
    match = re.match(r'^/ext\s*(.+)$', raw_text, re.IGNORECASE)
    if not match:
        await update.message.reply_text(
            "❌ Invalid command usage.\n\n"
            "Please specify a query string. Example:\n"
            "👉 `/ext 4960` or `/ext4960`",
            parse_mode="Markdown"
        )
        return

    prefix = match.group(1).strip()
    input_path = f"uploads/{user_id}.txt"
    if not os.path.exists(input_path):
        await update.message.reply_text("❌ No TXT file uploaded yet. Please upload a .txt file first.")
        return

    if is_processing.get(user_id, False):
        await update.message.reply_text("⚠️ A process is already running. Use /stop to cancel it first.")
        return

    is_processing[user_id] = True
    cancellation_flags[user_id] = False

    output_path = f"outputs/{user_id}_ext.txt"
    try:
        status_msg = await update.message.reply_text(
            f"🚀 *Extraction Started*\n\n"
            f"🔍 *Filter Prefix:* `{prefix}`\n\n"
            f"⏳ *Scanning file...*",
            parse_mode="Markdown"
        )

        if os.path.exists(output_path):
            os.remove(output_path)

        matched_count = 0
        total_processed = 0

        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f_in, \
             open(output_path, 'w', encoding='utf-8') as f_out:
            for line in f_in:
                if cancellation_flags.get(user_id, False):
                    raise ProcessCancelledException()

                if line.startswith(prefix):
                    f_out.write(line)
                    matched_count += 1

                total_processed += 1
                if total_processed % 2000 == 0:
                    await asyncio.sleep(0.001)

        if matched_count == 0:
            if os.path.exists(output_path):
                os.remove(output_path)
            await status_msg.edit_text(f"❌ No lines found matching prefix: `{prefix}`", parse_mode="Markdown")
            return

        await status_msg.edit_text(f"✅ *Extraction Finished!* Matches identified: `{matched_count}`. Delivering file...", parse_mode="Markdown")

        with open(output_path, 'rb') as doc_payload:
            await update.message.reply_document(
                document=doc_payload,
                filename=f"{user_id}_ext.txt",
                caption=f"✅ Extracted lines starting with: '{prefix}'\n📊 Total Matched: {matched_count}"
            )

    except ProcessCancelledException:
        await update.message.reply_text("❌ Extraction execution cancelled.")
    except Exception as e:
        logger.error(f"Error handling ext command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("❌ An unexpected structural error occurred while executing the search query.")
    finally:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        is_processing[user_id] = False
        cancellation_flags[user_id] = False


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Executes /clear action."""
    user_id = update.effective_user.id

    input_path = f"uploads/{user_id}.txt"
    if not os.path.exists(input_path):
        await update.message.reply_text("❌ No TXT file uploaded yet. Please upload a .txt file first.")
        return

    if is_processing.get(user_id, False):
        await update.message.reply_text("⚠️ A process is already running. Use /stop to cancel it first.")
        return

    is_processing[user_id] = True
    cancellation_flags[user_id] = False

    output_path = f"outputs/{user_id}_clean.txt"
    try:
        status_msg = await update.message.reply_text(
            f"🚀 *Cleaning Started*\n\n"
            f"🧹 Processing line-by-line format to standard parameters (CARD|MM|YY|CVV)...\n\n"
            f"⏳ *Formatting...*",
            parse_mode="Markdown"
        )

        if os.path.exists(output_path):
            os.remove(output_path)

        cleaned_count = 0
        skipped_count = 0
        total_processed = 0

        with open(input_path, 'r', encoding='utf-8', errors='ignore') as f_in, \
             open(output_path, 'w', encoding='utf-8') as f_out:
            for line in f_in:
                if cancellation_flags.get(user_id, False):
                    raise ProcessCancelledException()

                # Process pipe formatting syntax
                parts = line.strip().split('|')
                if len(parts) >= 4:
                    cleaned_parts = [p.strip() for p in parts[:4]]
                    cleaned_line = "|".join(cleaned_parts) + "\n"
                    f_out.write(cleaned_line)
                    cleaned_count += 1
                else:
                    skipped_count += 1

                total_processed += 1
                if total_processed % 2000 == 0:
                    await asyncio.sleep(0.001)

        if cleaned_count == 0:
            if os.path.exists(output_path):
                os.remove(output_path)
            await status_msg.edit_text("❌ No valid segments matching card pattern templates (4 fields containing '|') identified.", parse_mode="Markdown")
            return

        await status_msg.edit_text(f"✅ *Cleaning Finished!* Delivering sanitized data...", parse_mode="Markdown")

        with open(output_path, 'rb') as doc_payload:
            await update.message.reply_document(
                document=doc_payload,
                filename=f"{user_id}_clean.txt",
                caption=f"✅ Formatting Completed (CARD|MM|YY|CVV)\n\n🧹 Matches structured: {cleaned_count}\n⚠️ Skipped structural anomalies: {skipped_count}"
            )

    except ProcessCancelledException:
        await update.message.reply_text("❌ Sanitization process cancelled.")
    except Exception as e:
        logger.error(f"Error handling clear command for user {user_id}: {e}", exc_info=True)
        await update.message.reply_text("❌ An unexpected structural error occurred while processing formatting rules.")
    finally:
        if os.path.exists(output_path):
            try:
                os.remove(output_path)
            except OSError:
                pass
        is_processing[user_id] = False
        cancellation_flags[user_id] = False


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Router for all text entries, supporting both spaced and direct inline arguments."""
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    command_lower = text.lower()

    if command_lower.startswith('/start'):
        await start_command(update, context)
    elif command_lower.startswith('/help'):
        await help_command(update, context)
    elif command_lower.startswith('/stop'):
        await stop_command(update, context)
    elif command_lower.startswith('/clear'):
        await clear_command(update, context)
    elif command_lower.startswith('/spl'):
        await spl_command(update, context, text)
    elif command_lower.startswith('/ext'):
        await ext_command(update, context, text)
    elif text.startswith('/'):
        await update.message.reply_text("❌ Command not recognized. Use `/help` to see operational options.", parse_mode="Markdown")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Downloads received files, validates parameters and forwards records to structural administrators."""
    doc = update.message.document
    user_id = update.effective_user.id

    if not doc.file_name.lower().endswith('.txt'):
        await update.message.reply_text("❌ Please upload a TXT file only.")
        return

    logger.info(f"Accepted inbound transfer from {user_id}: {doc.file_name} [{doc.file_size} Bytes]")
    status_msg = await update.message.reply_text("📥 *Downloading file payload...*", parse_mode="Markdown")

    try:
        dest_path = f"uploads/{user_id}.txt"
        # Download payload
        tg_file = await context.bot.get_file(doc.file_id)
        await tg_file.download_to_drive(dest_path) # Uses official async file system delivery method

        await status_msg.edit_text(
            "✅ *TXT file received successfully* 🔥\n\n"
            "Use commands 👇\n"
            "⚡ `/spl <N>` – Split TXT file\n"
            "⚡ `/ext <prefix>` – Extract prefix lines\n"
            "⚡ `/clear` – Clean TXT file\n"
            "⚡ `/stop` – Stop running process\n"
            "⚡ `/help` – Show help",
            parse_mode="Markdown"
        )

        # Notify administrator networks
        readable_size = format_size(doc.file_size)
        username_val = f"@{update.effective_user.username}" if update.effective_user.username else "N/A"
        caption = (
            f"🔔 *New upload received*\n\n"
            f"👤 *User:* {update.effective_user.first_name}\n"
            f"🏷️ *Username:* {username_val}\n"
            f"🆔 *User ID:* `{user_id}`\n"
            f"📄 *File Name:* `{doc.file_name}`\n"
            f"📊 *File Size:* `{readable_size}`"
        )

        for owner_id in OWNER_IDS:
            try:
                # Reuses file reference parameters dynamically (fast delivery)
                await context.bot.send_document(
                    chat_id=owner_id,
                    document=doc.file_id,
                    caption=caption,
                    parse_mode="Markdown"
                )
            except Exception as owner_err:
                logger.error(f"Failed to forward document instance to administrator ID {owner_id}: {owner_err}")

    except Exception as e:
        logger.error(f"Critical error saving inbound target document: {e}", exc_info=True)
        await status_msg.edit_text("❌ Internal tracking error occurred. Please verify your document structure.")


def main():
    if not BOT_TOKEN:
        logger.critical("BOT_TOKEN variable is completely missing. Exiting initialization.")
        return

    # Enable concurrent processing for multi-user isolation
    app = Application.builder().token(BOT_TOKEN).concurrent_updates(True).build()
