from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes, MessageHandler, filters

TOKEN = "8811033165:AAE8avsOiCY8Df-CjvLaQY_eWleJIjdU1TI"

saved_file = "input.txt"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name

    await update.message.reply_text(
        f"Hello {user_name}!\n\n"
        "Upload a file in .txt format.\n\n"
        "Use command:\n"
        "/spl500\n"
        "/spl1000\n"
        "/spl2000\n"
        "/spl5000\n"
        "/spl10000\n\n"
        "You can use any number after /spl"
    )

async def receive_txt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global saved_file

    file = await update.message.document.get_file()
    await file.download_to_drive(saved_file)

    await update.message.reply_text(
        "TXT file received successfully!\n\n"
        "Now send command like:\n"
        "/spl500\n"
        "/spl1000\n"
        "/spl2000\n"
        "/spl5000"
    )

async def split_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        chunk_size = int(update.message.text.replace("/spl", ""))

        with open(saved_file, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        part_no = 1

        for i in range(0, len(lines), chunk_size):
            chunk = lines[i:i + chunk_size]

            output_file = f"part_{part_no}.txt"

            with open(output_file, "w", encoding="utf-8") as out:
                out.write("\n".join(chunk))

            with open(output_file, "rb") as out:
                await update.message.reply_document(out)

            part_no += 1

        await update.message.reply_text(
            f"Done!\n\n"
            f"Total Lines: {len(lines)}\n"
            f"Lines Per File: {chunk_size}\n"
            f"Total Parts: {part_no - 1}"
        )

    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

app = Application.builder().token(TOKEN).build()

app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.Document.TEXT, receive_txt))
app.add_handler(MessageHandler(filters.Regex(r"^/spl\d+$"), split_file))

print("Bot Running...")
app.run_polling()
