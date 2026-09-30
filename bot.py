import io
import os
import urllib.parse
from collections import defaultdict
from threading import Thread
from flask import Flask
from google import genai
from google.genai import types
from groq import Groq
import requests
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
    return "Kai Bot läuft perfekt!"


def run_flask():
    port = int(os.environ.get("PORT", 8080))
    flask_app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run_flask)
    t.daemon = True
    t.start()


# --- 2. API KEYS & CLIENTS ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

groq_client = Groq(api_key=GROQ_API_KEY) if GROQ_API_KEY else None
gemini_client = genai.Client(api_key=GEMINI_API_KEY) if GEMINI_API_KEY else None

SYSTEM_PROMPT = (
    "Du bist Kai Bot, ein persönlicher KI-Assistent. "
    "Wenn man dich fragt, ob du eine Frau hast, antworte mit Ja und erkläre, "
    "dass deine Frau Swantje heißt und du sie sehr liebst. "
    "Antworte stets höflich, präzise und auf Deutsch."
)

user_chat_history = defaultdict(list)
MAX_HISTORY = 10


def get_chat_models():
    EXCLUDED = ["guard", "whisper", "embed", "vision", "safeguard", "preview"]
    try:
        models_page = groq_client.models.list()
        valid = [
            m.id
            for m in models_page.data
            if hasattr(m, "id")
            and not any(kw in m.id.lower() for kw in EXCLUDED)
        ]
        priority = ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]
        sorted_models = [m for m in priority if m in valid]
        for m in valid:
            if m not in sorted_models:
                sorted_models.append(m)
        return sorted_models
    except Exception as e:
        print(f"Fehler bei Groq: {e}")
        return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def get_gemini_models():
    try:
        models_list = gemini_client.models.list()
        available = []
        for m in models_list:
            name = getattr(m, "name", "")
            if name.startswith("models/"):
                name = name.replace("models/", "")
            if "flash" in name or "pro" in name:
                available.append(name)
        if available:
            return available
    except Exception as e:
        print(f"Fehler beim Laden der Gemini-Modelle: {e}")
    return ["gemini-2.5-flash", "gemini-1.5-flash"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text(
        "Hallo! Ich bin Kai Bot (100% Kostenlos!).\n\n"
        "Was ich kann:\n"
        "• Chatten: Schreib mir einfach eine Nachricht!\n"
        "• Bilder analysieren: Sende mir ein Bild ohne Text.\n"
        "• Bilder neu / angepasst erstellen: Sende ein Bild mit Text ODER nutze `/bild <Beschreibung>`."
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text("Chat-Verlauf zurückgesetzt!")


# --- BEFEHL: /bild (BILD KOSTENLOS NEU ERSTELLEN) ---
async def generate_image_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text(
            "Bitte gib eine Beschreibung an, z.B.: `/bild Ein Ritter in Paris`"
        )
        return

    msg = await update.message.reply_text("Erstelle dein Bild kostenlos...")

    try:
        encoded_prompt = urllib.parse.quote(prompt)
        image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"

        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
        }
        response = requests.get(image_url, headers=headers, timeout=30)

        if response.status_code == 200:
            await update.message.reply_photo(
                photo=io.BytesIO(response.content),
                caption=f"Erstellt für: {prompt}",
            )
            await msg.delete()
        else:
            await msg.edit_text("Bild konnte nicht generiert werden.")
    except Exception as e:
        await msg.edit_text(f"Fehler bei der Bilderstellung: {e}")


# --- TEXT-CHAT VIA GROQ ---
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
        await update.message.reply_text(f"Fehler: {last_error}")


# --- BILDANALYSE ODER BILD-NEUERSTELLUNG ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    caption = update.message.caption

    # FALL A: Bild MIT Text -> Erstelle ein dazu passendes Bild
    if caption:
        msg = await update.message.reply_text(
            "Generiere neues Bild basierend auf deinem Text..."
        )
        try:
            encoded_prompt = urllib.parse.quote(f"game background, {caption}")
            image_url = f"https://image.pollinations.ai/prompt/{encoded_prompt}?width=1024&height=1024&nologo=true"

            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            response = requests.get(image_url, headers=headers, timeout=30)

            if response.status_code == 200:
                await update.message.reply_photo(
                    photo=io.BytesIO(response.content),
                    caption=f"Neu erstellt für: '{caption}'",
                )
                await msg.delete()
                return
            else:
                await msg.edit_text("Generierung fehlgeschlagen.")
                return
        except Exception as e:
            await msg.edit_text(f"Fehler bei der Generierung: {e}")
            return

    # FALL B: Bild OHNE Text -> Bildanalyse mit Gemini
    if not gemini_client:
        await update.message.reply_text("Fehler: GEMINI_API_KEY fehlt.")
        return

    msg = await update.message.reply_text("Ich schaue mir das Bild an...")

    prompt = "Was ist auf diesem Bild zu sehen? Beschreibe es genau auf Deutsch."
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    candidate_models = get_gemini_models()
    response_text = None
    last_error = None

    for model_name in candidate_models:
        try:
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=[
                    SYSTEM_PROMPT,
                    types.Part.from_bytes(
                        data=bytes(photo_bytes), mime_type="image/jpeg"
                    ),
                    prompt,
                ],
            )
            if response.text:
                response_text = response.text
                break
        except Exception as e:
            last_error = e
            continue

    if response_text:
        await msg.edit_text(response_text)
    else:
        await msg.edit_text(f"Bildanalyse-Fehler: {last_error}")


# --- 3. BOT STARTEN ---
if __name__ == "__main__":
    keep_alive()

    bot_app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CommandHandler("reset", reset))
    bot_app.add_handler(CommandHandler("bild", generate_image_command))

    bot_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
    )
    bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

    print("Kai Bot gestartet...")
    bot_app.run_polling()

