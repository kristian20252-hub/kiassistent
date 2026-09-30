import os
import requests
from flask import Flask, request
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from google import genai
from google.genai import types
import replicate

# Flask-App initialisieren
app = Flask(__name__)

# API Tokens aus den Umgebungsvariablen abrufen
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GROQ_API_KEY = os.environ.get("GROQ_API_KEY")
REPLICATE_API_TOKEN = os.environ.get("REPLICATE_API_TOKEN")

# Gemini Client initialisieren
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Telegram Application initialisieren
telegram_app = Application.builder().token(TELEGRAM_TOKEN).build()


# Start-Befehl
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    welcome_text = (
        "Hallo! Ich bin dein KI-Assistent Kai Bot.\n\n"
        "Was ich kann:\n"
        "• Chatten: Schreib mir einfach eine Nachricht!\n"
        "• Bilder analysieren: Sende mir ein Bild mit einer Frage.\n"
        "• Bilder generieren: Nutze den Befehl `/bild <Beschreibung>`."
    )
    await update.message.reply_text(welcome_text)


# Befehl zur Bildgenerierung (/bild <Prompt>)
async def bild_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    prompt = " ".join(context.args)
    if not prompt:
        await update.message.reply_text("Bitte gib eine Beschreibung an. Beispiel:\n`/bild Ein Roboter im Wald`", parse_mode="Markdown")
        return

    msg = await update.message.reply_text(" Generiere Bild mit FLUX...")

    try:
        # Bild über Replicate (FLUX Schnell) generieren
        output = replicate.run(
            "black-forest-labs/flux-schnell",
            input={"prompt": prompt}
        )
        
        if output:
            image_url = output[0] if isinstance(output, list) else output
            await update.message.reply_photo(photo=image_url, caption=f"✨ *{prompt}*", parse_mode="Markdown")
            await msg.delete()
        else:
            await msg.edit_text("Fehler: Es konnte kein Bild generiert werden.")

    except Exception as e:
        await msg.edit_text(f"Fehler bei der Bildgenerierung: {str(e)}")


# Nachrichten verarbeiten (Text und Bilder)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    if not message:
        return

    # 1. Fall: Bild erhalten
    if message.photo:
        caption = message.caption or "Beschreibe dieses Bild im Detail."
        msg = await message.reply_text("🔍 Analysiere Bild...")

        try:
            # Höchste Auflösung des Bildes herunterladen
            photo_file = await message.photo[-1].get_file()
            image_bytes = await photo_file.download_as_bytearray()

            # Analyse über Gemini
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(
                        data=bytes(image_bytes),
                        mime_type="image/jpeg",
                    ),
                    caption,
                ],
            )
            await msg.edit_text(response.text)

        except Exception as e:
            await msg.edit_text(f"Fehler bei der Bildanalyse: {str(e)}")

    # 2. Fall: Reine Textnachricht erhalten
    elif message.text:
        msg = await message.reply_text("🤔 Denke nach...")
        try:
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=message.text,
            )
            await msg.edit_text(response.text)
        except Exception as e:
            await msg.edit_text(f"Fehler bei der Antwort: {str(e)}")


# Webhook-Route für Telegram
@app.route(f"/{TELEGRAM_TOKEN}", methods=["POST"])
def webhook():
    update = Update.de_json(request.get_json(force=True), telegram_app.bot)
    telegram_app.update_queue.put_nowait(update)
    return "OK", 200

@app.route("/")
def index():
    return "Bot läuft!", 200


# Telegram Handlers registrieren
telegram_app.add_handler(CommandHandler("start", start_command))
telegram_app.add_handler(CommandHandler("bild", bild_command))
telegram_app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_message))


if __name__ == "__main__":
    telegram_app.run_polling()

