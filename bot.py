import io
import os
from collections import defaultdict
from threading import Thread
from flask import Flask
from google import genai
from google.genai import types
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
    return "Kai Bot läuft mit Text-, Analyse- und Bildgenerierungsfunktion!"


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
    "Du bist Kai Bot, ein persönlicher KI-Assistent. "
    "Wenn man dich fragt, ob du eine Frau hast, antworte mit Ja und erkläre, "
    "dass deine Frau Swantje heißt und du sie sehr liebst. "
    "Antworte stets höflich, präzise und auf Deutsch."
)

user_chat_history = defaultdict(list)
MAX_HISTORY = 10


def get_chat_models():
    """Holt Textmodelle von Groq."""
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
        print(f"Fehler bei Groq-Modellen: {e}")
        return ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"]


def get_gemini_models():
    """Dynamische Ermittlung verfügbarer Gemini-Modelle."""
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
    return ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text(
        "Hallo! Ich bin Kai Bot.\n\n"
        "Was ich kann:\n"
        "1. **Bilder generieren:** Schreibe `/bild <Beschreibung>` (z.B. `/bild Ein Hund auf dem Mond`)\n"
        "2. **Bilder bearbeiten:** Schicke ein Bild mit einem Text wie `Ändere den Hintergrund zu einer Wüste`\n"
        "3. **Bilder analysieren:** Schicke ein Bild (ohne Bearbeitungswunsch)\n"
        "4. **Chatten:** Einfach eine Nachricht schreiben!"
    )


async def reset(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user_chat_history[chat_id].clear()
    await update.message.reply_text("Chat-Verlauf zurückgesetzt!")


# --- BEFEHL: /bild (NEUES BILD ERSTELLEN) ---
async def generate_image_command(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text(
            "Bitte gib eine Beschreibung an, z.B.: `/bild Ein Elefant im Weltall`"
        )
        return

    await update.message.reply_text("Erstelle dein Bild, bitte einen Moment...")

    if not gemini_client:
        await update.message.reply_text(
            "Fehler: GEMINI_API_KEY fehlt in den Render-Einstellungen."
        )
        return

    try:
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE"],
            ),
        )

        image_sent = False
        for part in response.parts:
            if part.inline_data:
                img_bytes = part.inline_data.data
                await update.message.reply_photo(
                    photo=io.BytesIO(img_bytes), caption=f"Erstellt für: {prompt}"
                )
                image_sent = True
                break

        if not image_sent:
            await update.message.reply_text(
                "Kein Bild generiert. Versuche eine andere Beschreibung."
            )

    except Exception as e:
        await update.message.reply_text(
            f"Fehler bei der Bildgenerierung: {e}"
        )


# --- NORMALE TEXTNACHRICHTEN ---
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


# --- BILDER EMPFANGEN (ANALYSIEREN ODER BEARBEITEN) ---
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not gemini_client:
        await update.message.reply_text(
            "Fehler: GEMINI_API_KEY fehlt in Render."
        )
        return

    caption = update.message.caption or ""
    photo_file = await update.message.photo[-1].get_file()
    photo_bytes = await photo_file.download_as_bytearray()

    # Prüfen, ob der Nutzer das Bild BEARBEITEN oder nur ANALYSIEREN möchte
    edit_keywords = [
        "bearbeite",
        "ändere",
        "ersetze",
        "entferne",
        "füge",
        "mach",
        "erstelle",
        "füge hinzu",
    ]
    is_edit_request = any(kw in caption.lower() for kw in edit_keywords)

    if is_edit_request:
        await update.message.reply_text("Bearbeite das Bild...")
        try:
            # Bildmodifikation anfordern
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(
                        data=bytes(photo_bytes), mime_type="image/jpeg"
                    ),
                    f"Bearbeite dieses Bild wie folgt: {caption}",
                ],
                config=types.GenerateContentConfig(
                    response_modalities=["IMAGE", "TEXT"]
                ),
            )

            image_sent = False
            for part in response.parts:
                if part.inline_data:
                    await update.message.reply_photo(
                        photo=io.BytesIO(part.inline_data.data),
                        caption="Hier ist dein bearbeitetes Bild!",
                    )
                    image_sent = True
                elif part.text and not image_sent:
                    await update.message.reply_text(part.text)

            if not image_sent and not response.parts:
                await update.message.reply_text(
                    "Das Bild konnte nicht bearbeitet werden."
                )

        except Exception as e:
            await update.message.reply_text(
                f"Fehler bei der Bildbearbeitung: {e}"
            )

    else:
        # Reine Bildanalyse
        await update.message.reply_text("Ich schaue mir das Bild an...")
        prompt_text = (
            caption
            or "Was ist auf diesem Bild zu sehen? Beschreibe es genau auf Deutsch."
        )

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
                        prompt_text,
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
            await update.message.reply_text(
                f"Bildanalyse-Fehler: {last_error}"
            )


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

