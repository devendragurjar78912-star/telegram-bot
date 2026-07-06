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
                await asyncio.sleep(0)  # Yield control to prevent event loop starvation
    return total_lines, matching_lines

# --------------------------------------------------------
# 5. BOT INTERFACE COMMAND & BUTTON HANDLERS
# --------------------------------------------------------
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Responds to /start by initializing user options and showing the Start button keyboard."""
    context.user_data.clear()
    welcome_text = (
        "👋 **Welcome to the Professional TXT Processing Bot!**\n\n"
        "I am fully optimized for fast, non-blocking, multi-user line manipulation.\n\n"
        "Press the **🚀 Start** button below to initialize your command options matrix layout."
    )
    await update.message.reply_text(welcome_text, parse_mode="Markdown", reply_markup=START_KEYBOARD)

async def keyboard_start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switches layout instantly to the permanent professional processing dashboard grid."""
    transition_text = (
        "⚙️ **Dashboard Matrix Initialized!**\n\n"
        "Select an action button from the control panel grid layout below to view details and instruction templates."
    )
    await update.message.reply_text(transition_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def button_spl_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays functional text guidelines for running data payload partitioning requests."""
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
    """Displays visual examples regarding formatting configurations for card parsing structures."""
    clear_text = (
        "Send:\n\n"
        "`/clear`\n\n"
        "Then upload your TXT file.\n\n"
        "The bot will keep only:\n\n"
        "`CARD|MM|YY(or YYYY)|CVV`\n\n"
        "Examples:\n\n"
        "1234567890123456|12|28|123|John|Delhi\n"
        "↓\n"
        "`1234567890123456|12|28|123`\n\n"
        "and\n\n"
        "1234567890123456|12|2028|123|John|Delhi\n"
        "↓\n"
        "`1234567890123456|12|2028|123`"
    )
    await update.message.reply_text(clear_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def button_ext_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Displays explicit instructions on utilizing extraction regex rules dynamically."""
    ext_text = (
        "Send command like:\n\n"
        "`/ext6390`\n\n"
        "Then upload your TXT file.\n\n"
        "The bot will extract only matching BINs."
    )
    await update.message.reply_text(ext_text, parse_mode="Markdown", reply_markup=MAIN_KEYBOARD)

async def button_info_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Renders comprehensive documentation concerning operational runtime codes."""
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
    """Alternative standard direct trigger command hook targeting help references."""
    await button_info_handler(update, context)

async def spl_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Parses dynamic arguments derived from custom split pattern triggers."""
    text = update.message.text.strip()
    try:
        lines_count = int(text[4:])
        if lines_count <= 0:
            raise ValueError()
        context.user_data["mode"] = "split"
        context.user_data["param"] = lines_count
        await update.message.reply_text(f"✅ **Configuration Active:** File Split Mode (`{lines_count}` lines per file). Please upload your `.txt` document.", reply_markup=MAIN_KEYBOARD)
    except Exception:
        await update.message.reply_text("❌ **Invalid Parameter:** Please define a positive integer. Example: `/spl100`", reply_markup=MAIN_KEYBOARD)

async def ext_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Configures prefix text match filters based on the incoming text command suffix."""
    text = update.message.text.strip()
    prefix_val = text[4:]
    if not prefix_val:
        await update.message.reply_text("❌ **Invalid Parameter:** Please supply an explicit prefix sequence. Example: `/ext6390`", reply_markup=MAIN_KEYBOARD)
        return
    context.user_data["mode"] = "extract"
    context.user_data["param"] = prefix_val
    await update.message.reply_text(f"✅ **Configuration Active:** Extraction Mode (Prefix: `{prefix_val}`). Please upload your `.txt` document.", reply_markup=MAIN_KEYBOARD)

async def clear_config_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Sets user active pipeline parsing parameters to strict 4-field column validation rules."""
    context.user_data["mode"] = "clear"
    context.user_data["param"] = None
    await update.message.reply_text("✅ **Configuration Active:** Pipe Cleaning Mode (Keeps the first 4 fields only). Please upload your `.txt` document.", reply_markup=MAIN_KEYBOARD)

async def stop_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Locates any currently running user job and executes a cooperative task cancel loop."""
    user_id = update.effective_user.id
    if user_id in ACTIVE_TASKS:
        task = ACTIVE_TASKS[user_id]
        task.cancel()
        await update.message.reply_text("🛑 **Cancellation signal transmitted.** Terminating operations now...", reply_markup=MAIN_KEYBOARD)
    else:
        await update.message.reply_text("ℹ️ You have no active file streams running right now.", reply_markup=MAIN_KEYBOARD)

# --------------------------------------------------------
# 6. STREAM PIPELINE COMPONENT DESIGN WITH PRE-CALCULATIONS
# --------------------------------------------------------
async def process_file_stream(update: Update, context: ContextTypes.DEFAULT_TYPE, input_path: str, user_outputs_dir: Path, original_name: str, mode: str, param):
    """Core text processing logic. Executes line-by-line using low-memory asynchronous handles."""
    sent_files_tracker = []
    line_counter = 0

    # Step 1: Pre-scan calculations before processing
    total_lines, matching_lines = await pre_scan_file_metrics(input_path, mode, param)

    if total_lines == 0:
        await update.message.reply_text("⚠️ **Processing Aborted:** The uploaded file contains no data rows.", reply_markup=MAIN_KEYBOARD)
        return

    # Step 2: Send mode-specific progress summary message blocks
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
            "🚀 Cleaning Started...\n\n"
            f"📄 Total Lines: {total_lines}"
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

    # Step 3: Run execution blocks asynchronously
    # ----------------- MODE: CLEAR PIPELINE -----------------
    if mode == "clear":
        out_filename = f"cleared_{original_name}"
        out_path = user_outputs_dir / out_filename
        output_lines_count = 0
        
        async with aiofiles.open(input_path, mode="r", encoding="utf-8", errors="ignore") as infile, \
                   aiofiles.open(out_path, mode="w
