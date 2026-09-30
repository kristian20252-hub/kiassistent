import os
import time
from threading import Thread
from flask import Flask
from google import genai
from google.genai import types
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- 1. WEBSERVER FÜR RENDER ---
flask_app = Flask("")


@flask_app.route("/")
def home():
    return "Kai Bot läuft!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


# --- 2. TELEGRAM & GEMINI BOT LOGIK ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# Gemini Client initialisieren
ai_client = genai.Client(api_key=GEMINI_API_KEY)

# Identität für den Bot festlegen
SYSTEM_PROMPT = (
    "Du bist Kai Bot. Wenn man dich nach deinem Namen oder wer du bist fragt, "
    "antworte exakt: 'Mein Name ist Kai Bot und ich bin dein persönlicher KI-Assistent.' "
    "Antworte immer höflich, präzise und in korrektem Hochdeutsch."
)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Mein Name ist Kai Bot und ich bin dein persönlicher KI-Assistent."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_text = update.message.text

    models = ["gemini-2.5-flash", "gemini-1.5-flash"]

    for model_name in models:
        for attempt in range(3):
            try:
                response = ai_client.models.generate_content(
                    model=model_name,
                    contents=user_text,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                    ),
                )
                if response and response.text:
                    await update.message.reply_text(response.text)
                    return
            except Exception as e:
                error_str = str(e)
                if (
                    "503" in error_str
                    or "429" in error_str
                    or "RESOURCE_EXHAUSTED" in error_str
                ):
                    time.sleep(1.5 * (attempt + 1))
                    continue
                else:
                    break

    await update.message.reply_text(
        "Die Server von Google sind derzeit leider stark ausgelastet. Bitte versuche es in einem kurzen Moment erneut."
    )


# --- 3. BOT STARTEN ---
if __name__ == "__main__":
    keep_alive()

    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )

    print("Kai Bot wird gestartet...")
    bot_app.run_polling()
