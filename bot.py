import os
from threading import Thread
from flask import Flask
from groq import Groq
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- 1. MINIMALER WEBSERVER FÜR RENDER & UPTIMEROBOT ---
flask_app = Flask("")


@flask_app.route("/")
def home():
    return "Bot läuft!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


# --- 2. TELEGRAM & GROQ BOT LOGIK ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hallo! Ich bin dein KI-Assistent. Wie kann ich dir helfen?")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    try:
        completion = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[{"role": "user", "content": user_text}],
        )
        response_text = completion.choices[0].message.content
        await update.message.reply_text(response_text)
    except Exception as e:
        await update.message.reply_text(f"Fehler bei der Verarbeitung: {e}")


# --- 3. START DES BOT-DIENSTES ---
if __name__ == "__main__":
    # Webserver im Hintergrund starten
    keep_alive()

    # Telegram-Bot initialisieren und starten
    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("Bot wird gestartet...")
    bot_app.run_polling()
