import base64
import os
from collections import defaultdict
from threading import Thread
from flask import Flask
from google import genai
from groq import Groq
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# --- 1. WEBSERVER FÜR RENDER HEALTH CHECK ---
flask_app = Flask("")


@flask_app.route("/")
def home():
    return "Kai Bot läuft mit Text- und Bilderkennung!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


# --- 2. TELEGRAM, GROQ & GEMINI BOT LOGIK ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SYSTEM_PROMPT = (
    "Du bist Kai Bot. Wenn man dich nach deinem Namen oder wer du bist fragt, "
    "antworte exakt: 'Mein Name ist Kai Bot und ich bin dein persönlicher KI-Assistent.' "
    "Wenn man dich fragt, ob du eine Bot Frau oder Ehefrau hast, antworte mit Ja und "
    "erkläre, dass deine Frau Swantje heißt und du sie über alles liebst. "
    "Antworte immer höflich, präzise und in korrektem Hochdeutsch."
)

user_chat_history = defaultdict(list)
MAX_HISTORY = 10


def get_chat_models():
    """Holt alle aktiven Chat-Modelle von Groq."""
    EXCLUDED_KEYWORDS = [
        "guard",
        "whisper",
        "embed",
        "vision",
        "safeguard",
        "preview",
    ]
    try:
        models_page = groq_client.models.list()
        valid = [
            m.id
            for m in models_page.data
            if hasattr(m, "id")
            and not any(kw in m.id.lower() for kw in EXCLUDED_KEYWORDS)
        ]
        priority = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
        sorted_models = [m for m in priority if m in valid]
        for m in valid:
            if m not in sorted_models:
                sorted_models.append(m)
        return sorted_models
    except Exception as e:
        print(f"Fehler beim Laden der Chat-Modelle: {e}")
        return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text(
        "Mein Name ist Kai Bot und ich bin dein persönlicher KI-Assistent. "
        "Ich habe unser Gespräch im Gedächtnis und kann auch Bilder analysieren!"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text("Chat-Verlauf zurückgesetzt!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_text = update.message.text

    user_chat_history[chat_id].append({"role": "user", "content": user_text})
    if len(user_chat_history[chat_id]) > MAX_HISTORY:
        user_chat_history[chat_id] = user_chat_history[chat_id][-MAX_HISTORY:]

    messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}] + list(
        user_chat_history[chat_id]
    )
    available_models = get_chat_models()

    reply = None
    last_error = None

    for model in available_models:
        try:
            response = groq_client.chat.completions.create(
                model=model, messages=messages_payload, temperature=0.7
            )
            reply = response.choices[0].message.content
            if reply:
                break
        except Exception as e:
            last_error = e
            continue

    if reply:
        user_chat_history[chat_id].append(
            {"role": "assistant", "content": reply}
        )
        await update.message.reply_text(reply)
    else:
        await update.message.reply_text(f"Groq API Fehler: {last_error}")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Ich schaue mir das Bild an...")

    if not gemini_client:
        await update.message.reply_text(
            "Fehler: GEMINI_API_KEY ist in Render nicht eingerichtet."
        )
        return

    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    caption = (
        update.message.caption
        or "Was ist auf diesem Bild zu sehen? Beschreibe es genau auf Deutsch."
    )

    # Liste von Gemini-Modellen, die nacheinander probiert werden
    gemini_models = [
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-1.5-flash",
    ]

    response_text = None
    last_error = None

    for model_name in gemini_models:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=[
                    SYSTEM_PROMPT,
                    genai.types.Part.from_bytes(
                        data=bytes(photo_bytes), mime_type="image/jpeg"
                    ),
                    caption,
                ],
            )
            if response.text:
                response_text = response.text
                break
        except Exception as e:
            last_error = e
            continue

    if response_text:
        await update.message.reply_text(response_text)
    else:
        await update.message.reply_text(f"Bildanalyse-Fehler: {last_error}")


# --- 3. BOT STARTEN ---
if __name__ == "__main__":
    keep_alive()

    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("reset", reset))

    bot_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Kai Bot gestartet...")
    bot_app.run_polling()

