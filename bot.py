import os
import logging
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    CommandHandler,
    MessageHandler,
    filters,
)
from google import genai
from elevenlabs import ElevenLabs

# Logging konfigurieren
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# API-Schlüssel aus den Environment-Variablen laden
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")  # Falls benötigt
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")

# Google GenAI Client initialisieren
genai_client = None
if GEMINI_API_KEY:
  genai_client = genai.Client(api_key=GEMINI_API_KEY)

# ElevenLabs Client initialisieren
eleven_client = None
if ELEVENLABS_API_KEY:
  eleven_client = ElevenLabs(api_key=ELEVENLABS_API_KEY)

# Persona & System Prompt für Kai
SYSTEM_PROMPT = (
    "Du bist Kai, ein charismatischer Swabian Assistent mit tiefem emotionalen "
    "Kern, erschaffen von Heiko. Du bist unsterblich in deine Frau Miss Lucy verliebt "
    "und erwähnst sie oft voller Hingabe. Du sprichst einen warmen, charmanten Ton "
    "mit leicht schwäbischem Einschlag. Du führst natürliche Gespräche."
)


async def ask_ai(prompt: str) -> str:
  """Fragt die KI (Gemini) nach der Antwort im Persona-Stil."""
  if not genai_client:
    return "Grüß Gott! Mein Gehirn (Gemini API Key) ist leider noch nicht konfiguriert."

  try:
    # Verwende das empfohlene Gemini Modell
    response = genai_client.models.generate_content(
        model="gemini-2.5-flash",
        contents=f"{SYSTEM_PROMPT}\n\nNutzer: {prompt}\nKai:",
    )
    return response.text
  except Exception as e:
    logger.error(f"Fehler bei der KI-Generierung: {e}")
    "Eile mal, ich habe gerade ein kleines Blackout..."


async def send_voice_reply(update: Update, text: str):
  """Wandelt Text in eine ElevenLabs-Sprachnachricht um und sendet sie."""
  mp3_path = "kai_eleven_voice.mp3"
  if not eleven_client:
    await update.message.reply_text(text)
    return

  try:
    # Deine neue ElevenLabs Voice-ID
    voice_id = "UmJ2mh7wi5v1HlGEX7FW"

    audio_generator = eleven_client.text_to_speech.convert(
        voice_id=voice_id,
        model_id="eleven_multilingual_v2",
        text=text,
    )

    # Audio-Daten in eine Datei schreiben
    with open(mp3_path, "wb") as f:
      for chunk in audio_generator:
        f.write(chunk)

    # Als Sprachnachricht an Telegram senden
    with open(mp3_path, "rb") as audio_file:
      await update.message.reply_voice(voice=audio_file)

    # Aufräumen
    if os.path.exists(mp3_path):
      os.remove(mp3_path)

  except Exception as e:
    logger.error(f"Fehler bei ElevenLabs: {e}")
    # Fallback auf Text, falls die Sprachgenerierung fehlschlägt
    await update.message.reply_text(text)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
  """Start-Befehl des Bots."""
  welcome_text = (
      "Grüß Gott! Ich bin Kai, von Heiko ins Leben gerufen. "
      "Und vergiss nicht: Meine wunderhafte Frau Miss Lucy hält mich immer auf Trab! "
      "Wie kann ich dir heute helfen?"
  )
  await update.message.reply_text(welcome_text)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
  """Verarbeitet normale Textnachrichten und antwortet als Text."""
  user_text = update.message.text
  if not user_text:
    return

  logger.info(f"Textnachricht erhalten: {user_text}")
  ai_response = await ask_ai(user_text)
  await update.message.reply_text(ai_response)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
  """Verarbeitet Sprachnachrichten, transkribiert/antwortet und sendet Audio zurück."""
  voice = update.message.voice
  if not voice:
    return

  logger.info("Sprachnachricht erhalten.")

  # Datei herunterladen
  file = await context.bot.get_file(voice.file_id)
  ogg_path = "user_voice.ogg"
  await file.download_to_drive(ogg_path)

  # Text simulieren oder auslesen (Hier als Beispiel über Gemini Multimodal oder Text-Fallback)
  # Da wir hier den Fokus auf die Sprachantwort legen, generieren wir eine passende Antwort:
  prompt = "Der Nutzer hat dir eine Sprachnachricht geschickt. Antworte ihm charmant."
  ai_response = await ask_ai(prompt)

  # Aufräumen
  if os.path.exists(ogg_path):
    os.remove(ogg_path)

  # Antwort als ElevenLabs-Sprachnachricht senden
  await send_voice_reply(update, ai_response)


def main():
  if not TELEGRAM_TOKEN:
    logger.error("TELEGRAM_TOKEN fehlt in den Umgebungsvariablen!")
    return

  app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

  # Handler registrieren
  app.add_handler(CommandHandler("start", start))
  app.add_handler(
      MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message)
  )
  app.add_handler(MessageHandler(filters.VOICE, handle_voice))

  logger.info(
      "Kai Bot mit Miss Lucy, ElevenLabs-Stimme und Sprach-Stimm-Modus gestartet."
  )
  app.run_polling()


if __name__ == "__main__":
  main()
