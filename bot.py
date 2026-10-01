import os
import logging
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import Groq

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")

client = Groq(api_key=GROQ_API_KEY)

# Speichert, wann in welchem Chat das letzte Mal aktiv geredet wurde {chat_id: timestamp}
active_chats = {}
TIMEOUT_SECONDS = 300  # 5 Minuten Inaktivität beendet das Gespräch automatisch

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat = update.effective_chat
    chat_id = chat.id
    chat_type = chat.type
    message_text = update.message.text
    text_lower = message_text.lower()
    current_time = time.time()

    is_named = "kai" in text_lower
    
    # Prüfen, ob ein aktives Gespräch läuft (nur in Gruppen relevant)
    is_active = False
    if chat_type in ["group", "supergroup"]:
        if chat_id in active_chats:
            # Prüfen, ob das Zeitlimit überschritten wurde
            if current_time - active_chats[chat_id] < TIMEOUT_SECONDS:
                is_active = True
            else:
                del active_chats[chat_id] # Zeit abgelaufen, Gespräch beendet

        # Wenn er genannt wird, wird das Gespräch aktiviert oder verlängert
        if is_named:
            active_chats[chat_id] = current_time
            is_active = True

        # Wenn weder genannt noch im aktiven Gespräch -> ignorieren
        if not is_active:
            return
    else:
        # Im Privatchat immer antworten
        pass

    # KI-Antwort generieren
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "Du bist Kai, ein hilfsbereiter KI-Assistent."},
                {"role": "user", "content": message_text}
            ],
            temperature=0.7,
        )
        reply = completion.choices[0].message.content
        
        # Bei einer Antwort den Zeitstempel für das aktive Gespräch aktualisieren
        if chat_type in ["group", "supergroup"]:
            active_chats[chat_id] = time.time()
            
        await update.message.reply_text(reply)
    except Exception as e:
        logging.error(f"Fehler bei Groq: {e}")
        await update.message.reply_text("Entschuldigung, da gab es einen kleinen Fehler.")

def main():
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    print("Kai Bot läuft mit Konversations-Gedächtnis...")
    app.run_polling()

if __name__ == "__main__":
    main()
