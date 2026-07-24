from telegram.ext import Application, ContextTypes, MessageHandler, filters

async def get_chat_id(update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(f"Group Chat ID: `{chat_id}`", parse_mode="Markdown")

def main():
    app = Application.builder().token(TELEGRAM_TOKEN).build()
    
    # Temporary handler to get the chat ID
    app.add_handler(MessageHandler(filters.ALL, get_chat_id))
    
    print("Bot iniciado - waiting for any message to get chat ID")
    app.run_polling()