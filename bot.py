import os
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import Groq

# Groq Client initialisieren
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    
    # Anfrage an Groq senden
    chat_completion = client.chat.completions.create(
        messages=[
            {
                "role": "system",
                "content": "Du bist Heiko, ein hilfsbereiter Schwäbischer, cooler und lockerer KI-Assistent. Antworte immer auf Deutsch und stelle dich bei Bedarf as Heiko vor."
            },
            {
                "role": "user",
                "content": user_message
            }
        ],
        model="qwen/qwen2.5-72b",
    )
    
    # Antwort von der KI extrahieren
    bot_reply = chat_completion.choices[0].message.content
    
    # Antwort an Telegram zurückschicken
    await update.message.reply_text(bot_reply)

if __name__ == "__main__":
    TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Nachricht-Handler hinzufügen
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Bot läuft...")
    app.run_polling()
