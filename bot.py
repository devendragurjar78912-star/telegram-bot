import os
import re
import logging
import asyncio
import shutil
import math
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, Document
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# --------------------------------------------------------
# 1. DIRECTORY SETUP & LOGGING CONFIGURATION
# --------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent
LOGS_DIR = BASE_DIR / "logs"
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR = BASE_DIR / "outputs"

for folder in [LOGS_DIR, UPLOADS_DIR, OUTPUTS_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

log_formatter = logging.Formatter(
    "%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s"
)

console_handler = logging.StreamHandler()
console_handler.setFormatter(log_formatter)
console_handler.setLevel(logging.INFO)

bot_log_handler = logging.FileHandler(LOGS_DIR / "bot.log", encoding="utf-8")
bot_log_handler.setFormatter(log_formatter)
bot_log_handler.setLevel(logging.INFO)

error_log_handler = logging.FileHandler(LOGS_DIR / "errors.log", encoding="utf-8")
error_log_handler.setFormatter(log_formatter)
error_log_handler.setLevel(logging.ERROR)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(console_handler)
logger.addHandler(bot_log_handler)
logger.addHandler(error_log_handler)

# --------------------------------------------------------
# 2. ENVIRONMENT CONFIGURATION
# --------------------------------------------------------
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
OWNER_IDS_RAW = os.getenv("OWNER_IDS", "")

if not BOT_TOKEN:
    logger.critical("CRITICAL: BOT_TOKEN is missing in the environment variables!")
    raise ValueError("BOT_TOKEN environment variable is required.")

OWNER_IDS = []
for idx in OWNER_IDS_RAW.split(","):
    clean_id = idx.strip()
    if clean_id.isdigit():
        OWNER_IDS.append(int(clean_id))

if not OWNER_IDS:
    logger.warning("WARNING: OWNER_IDS contains no valid Telegram User IDs.")

# Global active task tracker for cancellation purposes
ACTIVE_TASKS = {}

# --------------------------------------------------------
# 3. HIGH-PERFORMANCE SYNCHRONOUS STREAM WORKERS
# --------------------------------------------------------
def sync_clear_worker(input_path: str, out_path: str):
    """Processes clean formats line-by-line via optimized memory-efficient stream layers."""
    input_lines = 0
    output_lines = 0
    with open(input_path, mode="r", encoding="utf-8", errors="ignore") as infile, \
         open(out_path, mode="w", encoding="utf-8", buffering=64*1024) as outfile:
        for line in infile:
            input_lines += 1
            stripped_line = line.strip()
            if not stripped_line:
                continue
                
            segments = [seg.strip() for seg in stripped_line.split("|")]
            card, mm, yy, cvv = None, None, None, None
            
            if len(segments) >= 3 and "/" in segments[1]:
                date_parts = segments[1].split("/")
                if len(date_parts) == 2:
                    card = segments[0]
                    mm = date_parts[0].strip()
                    yy = date_parts[1].strip()
                    cvv = segments[2]
                    
            elif len(segments) >= 4:
                card = segments[0]
                mm = segments[1]
                yy = segments[2]
                cvv = segments[3]
                
            if card and mm and yy and cvv:
                if card.isdigit() and len(card) == 16:
                    if mm.isdigit() and len(mm) == 2 and 1 <= int(mm) <= 12:
                        if yy.isdigit() and len(yy) in [2, 4]:
                            if cvv.isdigit() and len(cvv) == 3:
                                outfile.write(f"{card}|{mm}|{yy}|{cvv}\n")
                                output_lines += 1
    return input_lines, output_lines

def sync_fbin_worker(input_path: str, out_path: str, prefix_str: str):
    """Scans and extracts target prefixes reliably until EOF without loading file into RAM."""
    input_lines = 0
    output_lines = 0
    with open(input_path, mode="r", encoding="utf-8", errors="ignore") as infile, \
         open(out_path, mode="w", encoding="utf-8", buffering=64*1024) as outfile:
        for line in infile:
            input_lines += 1
            stripped_line = line.strip()
            if stripped_line.startswith(prefix_str):
                outfile.write(stripped_line + "\n")
                output_lines += 1
    return input_lines, output_lines

def sync_split_worker(input_path: str, user_outputs_dir: Path, chunk_size: int):
    """Splits target file line-by-line opening target descriptors sequentially."""
    input_lines = 0
    part_index = 1
    current_lines_written = 0
    current_out_file = None
    paths_created = []
    
    try:
        with open(input_path, mode="r", encoding="utf-8", errors="ignore") as infile:
            for line in infile:
                input_lines += 1
                if current_out_file is None:
                    part_filename = f"part {part_index}.txt"
                    part_path = user_outputs_dir / part_filename
                    current_out_file = open(part_path, mode="w", encoding="utf-8", buffering=64*1024)
                    paths_created.append(part_path)
                
                current_out_file.write(line)
                current_lines_written += 1
                
                if current_lines_written >= chunk_size:
                    current_out_file.close()
                    current_out_file = None
                    current_lines_written = 0
                    part_index += 1
    finally:
        if current_out_file is not None:
            current_out_file.close()
            
    return input_lines, paths_created

# --------------------------------------------------------
# 4. HELPER UTILITIES
# --------------------------------------------------------
async def send_to_owners(context: ContextTypes.DEFAULT_TYPE, caption: str, file_source=None):
    """Safely relays messages and file streams to all verified owner IDs without .read() calls."""
    for owner_id in OWNER_IDS:
        try:
            if file_source:
                if isinstance(file_source, str) and os.path.exists(file_source):
                    with open(file_source, "rb") as f:
                        await context.bot.send_document(
                            chat_id=owner_id,
                            document=f,
                            filename=os.path.basename(file_source),
                            caption=caption
                        )
                else:
                    await context.bot.send_document(
                        chat_id=owner_id,
                        document=file_source,
                        caption=caption
                    )
            else:
                await context.bot.send_message(chat_id=owner_id, text=caption)
        except Exception as e:
            logger.error(f"Failed to forward updates to owner ID {owner_id}: {e}")

async def validate_reply_to_txt(update: Update) -> Document | None:
    """Validates that the user is explicitly replying to a .txt file."""
    reply = update.message.reply_to_message
    if not reply or not reply.document or not reply.document.file_name.lower().endswith('.txt'):
        await update.message.reply_text("❌ Please reply to a TXT file with the command.")
        return None
    return reply.document

# --------------------------------------------------------
# 5. BOT INTERFACE COMMAND & FILE HANDLERS
# --------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds to /start by sending a plain text greeting with no keyboards."""
    user = update.effective_user
    greeting = f"Hello @{user.username}!" if user.username else f"Hello {user.first_name}!"
    welcome_text = f"{greeting}\n\nPlease upload a file in .txt format 📂"
    await update.message.reply_text(welcome_text)

async def document_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles standard file uploads and returns text-only instructions."""
    user = update.effective_user
    document = update.message.document

    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ **File Rejected:** This bot accepts only standard plain-text `.txt` files.")
        return

    username_str = f"@{user.username}" if user.username else "None"
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    
    owner_notification_text = (
        "📥 NEW FILE RECEIVED\n\n"
        f"👤 Name: {user.first_name}\n"
        f"📛 Username: {username_str}\n"
        f"🆔 User ID: {user.id}\n"
        f"📄 File Name: {document.file_name}\n"
        f"🕒 Timestamp: {current_time_str}"
    )
    
    asyncio.create_task(send_to_owners(context, caption=owner_notification_text, file_source=None))
    asyncio.create_task(send_to_owners(context, caption=f"📄 Original File Copy: {document.file_name}", file_source=document.file_id))

    success_msg = (
        "✅ TXT file received successfully 🔥\n\n"
        "Use commands 👇\n\n"
        "/spl <N> – Split TXT file\n"
        "/fbin <prefix> – Extract prefix lines\n"
        "/clear – Clean TXT file\n"
        "/stop – Stop running process"
    )
    await update.message.reply_text(success_msg)

async def rejected_files_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ **File Rejected:** Unsupported payload formatting. Provide valid `.txt` extensions only.")

# --------------------------------------------------------
# 6. COMMAND PIPELINE TRIGGERS
# --------------------------------------------------------
async def clear_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = await validate_reply_to_txt(update)
    if not document: return
    await run_processing_task(update, context, document, "clear", None)

async def fbin_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = await validate_reply_to_txt(update)
    if not document: return
    
    text = update.message.text.strip()
    match = re.match(r"^/fbin\s*(\d+)\s*$", text, re.IGNORECASE)
    
    if not match:
        await update.message.reply_text("❌ **Invalid Parameter:** Please supply a numeric prefix. Example: `/fbin4891` or `/fbin 489120`")
        return
        
    prefix_val = match.group(1)
    await run_processing_task(update, context, document, "extract", prefix_val)

async def spl_command_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = await validate_reply_to_txt(update)
    if not document: return
    
    text = update.message.text.strip()
    match = re.match(r"^/spl\s*(\d+)\s*$", text, re.IGNORECASE)
    
    if not match:
        await update.message.reply_text("❌ **Invalid Parameter:** Please define a positive integer. Example: `/spl100`")
        return
        
    lines_count = int(match.group(1))
    if lines_count <= 0:
        await update.message.reply_text("❌ **Invalid Parameter:** The number of lines must be greater than 0.")
        return
        
    await run_processing_task(update, context, document, "split", lines_count)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ACTIVE_TASKS:
        task = ACTIVE_TASKS[user_id]
        task.cancel()
        await update.message.reply_text("🛑 **Cancellation signal transmitted.** Terminating operations now...")
    else:
        await update.message.reply_text("ℹ️ You have no active file streams running right now.")

# --------------------------------------------------------
# 7. PROCESSING TASK MANAGER
# --------------------------------------------------------
async def run_processing_task(update: Update, context: ContextTypes.DEFAULT_TYPE, document: Document, mode: str, param=None):
    """Encapsulates execution handles bridging processing triggers with descriptive error extraction outputs."""
    user = update.effective_user
    user_id = user.id

    if user_id in ACTIVE_TASKS:
        await update.message.reply_text("⏳ **Process Blocked:** You currently have an active parsing run. Wait for completion or send `/stop` before continuing.")
        return

    message_id = update.message.reply_to_message.message_id
    task_dir_name = f"{user_id}_{message_id}"
    
    input_dir = UPLOADS_DIR / task_dir_name
    input_dir.mkdir(parents=True, exist_ok=True)
    input_path = input_dir / "input.txt"
    
    user_outputs_path = OUTPUTS_DIR / task_dir_name
    user_outputs_path.mkdir(parents=True, exist_ok=True)

    async def task_wrapper():
        try:
            status_msg = await update.message.reply_text("📥 **Downloading document file...** Please hold on.")
            tg_file = await context.bot.get_file(document.file_id)
            await tg_file.download_to_drive(custom_path=input_path)
            await status_msg.delete()
            
            await process_file_stream(update, context, str(input_path), user_outputs_path, mode, param)
        except asyncio.CancelledError:
            logger.info(f"User {user_id} cancelled ongoing execution pipeline processing.")
            await update.message.reply_text("❌ **Operation Halted:** Processing loop explicitly broken by user command.")
        except Exception as e:
            logger.exception(e)
            await update.message.reply_text(
                f"❌ {type(e).__name__}: {e}"
            )
        finally:
            if user_id in ACTIVE_TASKS:
                del ACTIVE_TASKS[user_id]
            shutil.rmtree(input_dir, ignore_errors=True)
            shutil.rmtree(user_outputs_path, ignore_errors=True)

    task = asyncio.create_task(task_wrapper())
    ACTIVE_TASKS[user_id] = task

# --------------------------------------------------------
# 8. STREAM PIPELINE RUNTIME ENGINE
# --------------------------------------------------------
async def process_file_stream(update: Update, context: ContextTypes.DEFAULT_TYPE, input_path: str, user_outputs_dir: Path, mode: str, param):
    """Orchestrates threaded single-pass stream loops passing active file references directly without RAM load."""
    sent_files_tracker = []

    if mode == "split":
        await update.message.reply_text(f"🚀 Processing Started... Splitting into blocks of {param} lines.")
    elif mode == "clear":
        await update.message.reply_text("🚀 Cleaning & Validating Started...")
    elif mode == "extract":
        await update.message.reply_text(f"🚀 Extracting BIN {param}...")

    # ----------------- MODE: CLEAR PIPELINE -----------------
    if mode == "clear":
        out_filename = "[@levisplitter_bot] cleaned.txt"
        out_path = user_outputs_dir / out_filename
        
        total_lines, output_lines_count = await asyncio.to_thread(sync_clear_worker, input_path, str(out_path))
        
        if total_lines == 0:
            await update.message.reply_text("⚠️ **Processing Aborted:** The uploaded file contains no data rows.")
            return
            
        sent_files_tracker.append(out_path)
        
        completion_msg = (
            "✅ Cleaning & Validation Completed\n\n"
            f"📄 Total Input Lines: {total_lines}\n"
            f"📄 Valid Output Lines: {output_lines_count}\n"
            f"🗑️ Invalid Lines Dropped: {total_lines - output_lines_count}"
        )
        await update.message.reply_text(completion_msg)

    # ----------------- MODE: FBIN PIPELINE -----------------
    elif mode == "extract":
        prefix_str = str(param)
        out_filename = f"[@levisplitter_bot] {prefix_str}.txt"
        out_path = user_outputs_dir / out_filename
        
        total_lines, output_lines_count = await asyncio.to_thread(sync_fbin_worker, input_path, str(out_path), prefix_str)
        
        if total_lines == 0:
            await update.message.reply_text("⚠️ **Processing Aborted:** The uploaded file contains no data rows.")
            return

        if output_lines_count > 0:
            sent_files_tracker.append(out_path)
        else:
            if out_path.exists():
                os.remove(out_path)
            await update.message.reply_text("❌ No matching BIN found.")
            return

    # ------------------ MODE: SPLIT PIPELINE ------------------
    elif mode == "split":
        chunk_size = int(param)
        
        total_lines, paths_created = await asyncio.to_thread(sync_split_worker, input_path, user_outputs_dir, chunk_size)
        
        if total_lines == 0:
            await update.message.reply_text("⚠️ **Processing Aborted:** The uploaded file contains no data rows.")
            return
            
        sent_files_tracker.extend(paths_created)

    # Stream output document components directly via file descriptors (Zero RAM load)
    files_sent = False
    for output_file in sent_files_tracker:
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            with open(output_file, "rb") as f:
                await update.message.reply_document(
                    document=f,
                    filename=output_file.name
                )
            files_sent = True
            await asyncio.sleep(0.2)

    if files_sent:
        await update.message.reply_text("✅ Work done 💯")

# --------------------------------------------------------
# 9. BOT APPLICATION BOOTSTRAP INITIALIZER
# --------------------------------------------------------
def main():
    logger.info("Initializing Application Framework Components...")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Core text-only commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("stop", stop_command))

    # Text message regex routers for processing file replies
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^/clear$"), clear_command_handler))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^/spl\s*\d+\s*$"), spl_command_handler))
    app.add_handler(MessageHandler(filters.Regex(r"(?i)^/fbin\s*\d+\s*$"), fbin_command_handler))

    # Catch-all file validation streams
    app.add_handler(MessageHandler(filters.Document.TXT, document_upload_handler))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.Document.TXT, rejected_files_handler))

    logger.info("Application context fully updated. Starting standard long-polling worker thread loop...")
    app.run_polling()

if __name__ == "__main__":
    main()
