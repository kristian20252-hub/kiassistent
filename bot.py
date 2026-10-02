import os
import re
from groq import Groq
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    ContextTypes,
    MessageHandler,
    filters,
)

# API-Schlüssel aus den Umgebungsvariablen (Render)
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

# Groq Client initialisieren
groq_client = Groq(api_key=GROQ_API_KEY)


def format_for_telegram(text):
  """Wandelt störende Markdown-Sternchen (**fett**)

  sicher in saubere HTML-Tags (<b>fett</b>) um, damit Telegram
  sie fehlerfrei und ohne Rohdaten darstellt.
  """
  text = re.sub(r"\*\*(.*?)\*\*", r"<b>\1</b>", text)
  return text


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
  user_message = update.message.text

  # Kai's Persönlichkeit und Formatierungs-Anweisungen
  system_prompt = (
      "Du bist Kai, ein cooler, lockerer und hilfsbereiter KI-Assistent. "
      "Achte bei deinen Antworten auf hervorragende Lesbarkeit: Verwende "
      "klare Absätze und Zeilenumbrüche, lockere den Text mit passenden Emojis"
      " auf und hebe wichtige Wörter mit **Fettgedrucktem** hervor."
  )

  try:
    # Anfrage an das LLM (Groq) senden
    completion = groq_client.chat.completions.create(
        model="llama3-70b-8192",  # Oder dein gewohntes Groq-Modell
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
    )
    ai_antwort = completion.choices[0].message.content

    # Text für Telegram aufbereiten (Markdown zu HTML)
    sauberer_text = format_for_telegram(ai_antwort)

    # Nachricht mit HTML-Parsing an Telegram senden
    await update.message.reply_text(sauberer_text, parse_mode="HTML")

  except Exception as e:
    print(f"Fehler: {e}")
    await update.message.reply_text(
        "Hoppla, da hat sich bei mir kurz der Schraubenschlüssel verklemmt! 🔧"
    )


if __name__ == "__main__":
  # Bot-Anwendung starten
  app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()

  # Handler für normale Textnachrichten hinzufügen
  app.add_handler(
      MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message)
  )

  print("Kai Bot ist gestartet und bereit!")
  app.run_polling()
