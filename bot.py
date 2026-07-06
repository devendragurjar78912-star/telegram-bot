import os
import logging
import asyncio
import shutil
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

# Configure logging to console, bot.log, and errors.log
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

# Safely parse multiple owner IDs split by comma
OWNER_IDS = []
for idx in OWNER_IDS_RAW.split(","):
    clean_id = idx.strip()
    if clean_id.isdigit():
        OWNER_IDS.append(int(clean_id))

if not OWNER_IDS:
    logger.warning("WARNING: OWNER_IDS contains no valid Telegram User IDs.")

# Global state tracking dictionary for cooperative task cancellation
# Format: { user_id: asyncio.Task }
ACTIVE_TASKS = {}

# --------------------------------------------------------
# 3. HELPER UTILITIES
# --------------------------------------------------------
async def send_to_owners(context: ContextTypes.DEFAULT_TYPE, caption: str, file_source=None):
    """Safely relays messages and files to all verified owner IDs."""
    for owner_id in OWNER_IDS:
        try:
            if file_source:
                if isinstance(file_source, str) and os.path.exists(file_source):
                    # It's a local file path string
                    async with aiofiles.open(file_source, "rb") as f:
                        file_bytes = await f.read()
                    await context.bot.send_document(
                        chat_id=owner_id,
                        document=file_bytes,
                        filename=os.path.basename(file_source),
                        caption=caption
                    )
                else:
                    # It's a Telegram file unique identification token string
                    await context.bot.send_document(
                        chat_id=owner_id,
                        document=file_source,
                        caption=caption
                    )
            else:
                await context.bot.send_message(chat_id=owner_id, text=caption)
        except Exception as e:
            logger.error(f"Failed to forward updates to owner ID {owner_id}: {e}")

def get_metadata_caption(user, filename: str, status_title: str) -> str:
    """Builds a standardized string block containing user and file context details."""
    username = f"@{user.username}" if user.username else "None"
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f"📋 *{status_title}*\n"
        f"👤 **Name:** {user.full_name}\n"
        f"🏷 **Username:** {username}\n"
        f"🆔 **User ID:** `{user.id}`\n"
        f"📄 **File Name:** {filename}\n"
        f"⏰ **Timestamp:** {current_time}"
    )

# --------------------------------------------------------
# 4. BOT COMMAND HANDLERS
# --------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds to /start by resetting parameters and displaying a welcome page."""
    context.user_data.clear()
    welcome_text = (
        "👋 **Welcome to the Production TXT Processing Bot!**\n\n"
        "I am fully optimized for non-blocking, multi-user file manipulation.\n\n"
        "⚡ **Get started by choosing a configuration mode:**\n"
        "🔸 `/spl<number>` — Split text files by lines (e.g., `/spl1000`)\n"
        "🔸 `/ext<prefix>` — Filter rows matching a specific prefix (e.g., `/ext6390`)\n"
        "🔸 `/clear` — Keep only the first 4 fields separated by vertical pipes (`|`)\n"
        "🔸 `/stop` — Abort any running file execution instantly\n\n"
        "💡 *Configure a mode first, then upload your target text file.*"
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays user guides, execution rules, and processing operational modes."""
    help_text = (
        "📖 **Operational Guide & Bot Commands**\n\n"
        "1️⃣ **Split Files:** `/spl1000` sets your profile to divide incoming text files into sections containing up to 1000 lines each.\n\n"
        "2️⃣ **Extract Lines:** `/ext54` sets your profile to extract lines that explicitly match the prefix `54` at the very start.\n\n"
        "3️⃣ **Clear Rows:** `/clear` sets your profile to slice data rows. It scans every line containing pipe characters (`|`) and completely drops everything beyond the 4th field. Unmatched rows are left unaltered.\n\n"
        "4️⃣ **Stop Stream:** `/stop` forcefully cancels execution loops assigned to your user account instantly."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def spl_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses dynamic arguments derived from custom split pattern triggers."""
    text = update.message.text.strip()
    try:
        lines_count = int(text[4:])
        if lines_count <= 0:
            raise ValueError()
        context.user_data["mode"] = "split"
        context.user_data["param"] = lines_count
        await update.message.reply_text(f"✅ **Configuration Active:** File Split Mode (`{lines_count}` lines per file). Please upload your `.txt` document.")
    except Exception:
        await update.message.reply_text("❌ **Invalid Parameter:** Please define a positive integer. Example: `/spl1000`")

async def ext_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configures prefix text match filters based on the incoming text command suffix."""
    text = update.message.text.strip()
    prefix_val = text[4:]
    if not prefix_val:
        await update.message.reply_text("❌ **Invalid Parameter:** Please supply an explicit prefix sequence. Example: `/ext6390`")
        return
    context.user_data["mode"] = "extract"
    context.user_data["param"] = prefix_val
    await update.message.reply_text(f"✅ **Configuration Active:** Extraction Mode (Prefix: `{prefix_val}`). Please upload your `.txt` document.")

async def clear_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets user active pipeline parsing parameters to strict 4-field column validation rules."""
    context.user_data["mode"] = "clear"
    context.user_data["param"] = None
    await update.message.reply_text("✅ **Configuration Active:** Pipe Cleaning Mode (Keeps the first 4 fields only). Please upload your `.txt` document.")

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Locates any currently running user job and executes a cooperative task cancel loop."""
    user_id = update.effective_user.id
    if user_id in ACTIVE_TASKS:
        task = ACTIVE_TASKS[user_id]
        task.cancel()
        await update.message.reply_text("🛑 **Cancellation signal transmitted.** Terminating operations now...")
    else:
        await update.message.reply_text("ℹ️ You have no active file streams running right now.")

# --------------------------------------------------------
# 5. STREAM PIPELINE COMPONENT DESIGN
# --------------------------------------------------------
async def process_file_stream(update: Update, context: ContextTypes.DEFAULT_TYPE, input_path: str, user_outputs_dir: Path, original_name: str, mode: str, param):
    """Core text processing logic. Executes line-by-line using low-memory asynchronous handles."""
    user = update.effective_user
    sent_files_tracker = []
    line_counter = 0

    # ----------------- MODE: CLEAR PIPELINE -----------------
    if mode == "clear":
        out_filename = f"cleared_{original_name}"
        out_path = user_outputs_dir / out_filename
        
        async with aiofiles.open(input_path, mode="r", encoding="utf-8", errors="ignore") as infile, \
                   aiofiles.open(out_path, mode="w", encoding="utf-8") as outfile:
            async for line in infile:
                line_counter += 1
                stripped_line = line.rstrip("\r\n")
                segments = stripped_line.split("|")
                if len(segments) >= 4:
                    cleaned_output = "|".join(segments[:4]) + "\n"
                    await outfile.write(cleaned_output)
                else:
                    await outfile.write(line)
                
                # Prevent thread-starvation on large files
                if line_counter % 2000 == 0:
                    await asyncio.sleep(0)

        sent_files_tracker.append(out_path)

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

    # ------------------ RESPOND TO USER & DISPATCH TO OWNERS ------------------
    if not sent_files_tracker or (mode in ["clear", "extract", "split"] and line_counter == 0):
        await update.message.reply_text("⚠️ **Processing completed:** No data lines were written or processed.")
        return

    await update.message.reply_text(f"📦 **Job Completed Successfully!** Total scanned rows: `{line_counter}`. Uploading results...")

    for output_file in sent_files_tracker:
        if os.path.exists(output_file) and os.path.getsize(output_file) > 0:
            # Deliver to User
            async with aiofiles.open(output_file, "rb") as f:
                output_bytes = await f.read()
            await update.message.reply_document(
                document=output_bytes,
                filename=os.path.basename(output_file)
            )
            
            # Forward copy to system owners with metadata caption logs
            owner_caption = get_metadata_caption(user, os.path.basename(output_file), "PROCESSED OUTPUT LOG")
            await send_to_owners(context, owner_caption, file_source=str(output_file))
            await asyncio.sleep(0.5) # Rate-limiting compliance guard
        else:
            await update.message.reply_text(f"⚠️ Resulting file `{os.path.basename(output_file)}` contains no data matching your parameters.")

# --------------------------------------------------------
# 6. INCOMING FILE DISPATCH HANDLER
# --------------------------------------------------------
async def document_upload_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Validates document payloads, verifies configurations, and boots task execution environments."""
    user = update.effective_user
    user_id = user.id
    document = update.message.document

    # Reject non-TXT documents strictly by checking extensions
    if not document.file_name.lower().endswith(".txt"):
        await update.message.reply_text("❌ **File Rejected:** This bot accepts only standard plain-text `.txt` files.")
        return

    # Enforce prior setup mode activation
    mode_type = context.user_data.get("mode")
    mode_param = context.user_data.get("param")
    if not mode_type:
        await update.message.reply_text("⚠️ **Configuration Required:** Set an action using `/spl`, `/ext`, or `/clear` before transmitting your text files.")
        return

    # Block recursive concurrent calls per user ID account
    if user_id in ACTIVE_TASKS:
        await update.message.reply_text("⏳ **Process Blocked:** You currently have an active parsing run. Wait for completion or send `/stop` before continuing.")
        return

    # Define clean operational scopes per processing routine
    user_uploads_path = UPLOADS_DIR / str(user_id)
    user_outputs_path = OUTPUTS_DIR / str(user_id)
    user_uploads_path.mkdir(parents=True, exist_ok=True)
    user_outputs_path.mkdir(parents=True, exist_ok=True)

    local_input_file = user_uploads_path / f"{document.file_id}.txt"
    status_msg = await update.message.reply_text("📥 **Downloading document file...** Please hold on.")

    try:
        # Fetch file data directly from telegram cloud attachment nodes
        tg_file = await context.bot.get_file(document.file_id)
        await tg_file.download_to_drive(custom_path=local_input_file)

        # Notify active admin/owner groups immediately with incoming file contexts
        incoming_caption = get_metadata_caption(user, document.file_name, "INCOMING FILE UPLOAD")
        await send_to_owners(context, incoming_caption, file_source=document.file_id)

        await status_msg.edit_text("⚙️ **Engine Running:** Running line-by-line streaming pipelines...")

        # Form dynamic asynchronous wrapper routines
        worker_routine = process_file_stream(
            update, context, str(local_input_file), user_outputs_path, document.file_name, mode_type, mode_param
        )
        task = asyncio.create_task(worker_routine)
        ACTIVE_TASKS[user_id] = task

        await task

    except asyncio.CancelledError:
        logger.info(f"User {user_id} cancelled ongoing execution pipeline processing.")
        await update.message.reply_text("❌ **Operation Halted:** Processing loop explicitly broken by user command.")
    except Exception as err:
        logger.error(f"Execution tracking crash on user input {user_id}: {err}", exc_info=True)
        await update.message.reply_text("⚠️ **System Error:** Failed to process your document. Ensure formatting rules match standard conventions.")
    finally:
        # Drop reference hooks dynamically from execution tables
        if user_id in ACTIVE_TASKS:
            del ACTIVE_TASKS[user_id]

        # Clean status messages
        try:
            await status_msg.delete()
        except Exception:
            pass

        # Clear file workspaces to prevent storage accumulation on ephemeral infrastructure
        if local_input_file.exists():
            os.remove(local_input_file)
        if user_outputs_path.exists():
            shutil.rmtree(user_outputs_path, ignore_errors=True)

async def rejected_files_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Informs users about incompatible document media variants transmitted across queues."""
    await update.message.reply_text("❌ **File Rejected:** Unsupported payload formatting. Provide valid configuration-compatible `.txt` extensions only.")

# --------------------------------------------------------
# 7. BOT APPLICATION BOOTSTRAP INITIALIZER
# --------------------------------------------------------
def main():
    """Initializes execution threads and registers active operational message routing states."""
    logger.info("Initializing Application Framework Components...")
    
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Route Core Commands
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_config_handler))
    app.add_handler(CommandHandler("stop", stop_command))

    # Handle RegEx variations matching functional configurations
    app.add_handler(MessageHandler(filters.Regex(r"^/spl\d+$"), spl_config_handler))
    app.add_handler(MessageHandler(filters.Regex(r"^/ext.+$"), ext_config_handler))

    # Handle incoming document payloads
    app.add_handler(MessageHandler(filters.Document.TXT, document_upload_handler))
    app.add_handler(MessageHandler(filters.Document.ALL & ~filters.Document.TXT, rejected_files_handler))

    logger.info("Application context fully updated. Starting standard long-polling worker thread loop...")
    app.run_polling()

if __name__ == "__main__":
    main()
