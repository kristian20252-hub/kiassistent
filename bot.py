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
                "content": "Du bist Heiko, ein hilfsbereiter schwäbischer, cooler und lockerer KI-Assistent. Antworte immer auf Deutsch und stelle dich bei Bedarf als Heiko vor."
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
    PORT = int(os.environ.get("PORT", 8443))
    
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    
    # Nachricht-Handler hinzufügen
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print(f"Starte Webhook-Server auf Port {PORT}...")
    
    # Automatischer Start je nachdem, ob Render-URL da ist oder lokal getestet wird
    RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL")
    
    if RENDER_EXTERNAL_URL:
        app.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            url_path=TELEGRAM_TOKEN,
            webhook_url=f"https://{RENDER_EXTERNAL_URL}/{TELEGRAM_TOKEN}"
        )
    else:
        app.run_polling()
