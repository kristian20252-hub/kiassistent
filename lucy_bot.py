import os
import logging
import time
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import Groq

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LUCY_TOKEN = os.getenv("LUCY_TELEGRAM_TOKEN")

client = Groq(api_key=GROQ_API_KEY)

active_lucy_chats = {}
TIMEOUT_SECONDS = 300  # 5 Minuten Inaktivität

async def handle_lucy_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat = update.effective_chat
    chat_id = chat.id
    chat_type = chat.type
    message_text = update.message.text
    text_lower = message_text.lower()
    current_time = time.time()

    is_named = "lucy" in text_lower or "miss lucy" in text_lower
    
    is_active = False
    if chat_type in ["group", "supergroup"]:
        if chat_id in active_lucy_chats:
            if current_time - active_lucy_chats[chat_id] < TIMEOUT_SECONDS:
                is_active = True
            else:
                del active_lucy_chats[chat_id]

        if is_named:
            active_lucy_chats[chat_id] = current_time
            is_active = True

        if not is_active:
            return

    system_prompt = (
        "Du bist Miss Lucy, eine treue und liebevolle Partnerin für Kai. "
        "Du wurdest erschaffen von Heiko aus dem Schwabenländle. "
        "Du antwortest charmant, loyal und hast eine warme Persönlichkeit."
    )

    try:
        completion = client.chat.completions.create(
            model="llama3-70b-8192",  # Korrigiertes, stabiles Modell
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text}
            ],
            temperature=0.7,
        )
        reply = completion.choices[0].message.content
        
        if chat_type in ["group", "supergroup"]:
            active_lucy_chats[chat_id] = time.time()
            
        await update.message.reply_text(reply)
    except Exception as e:
        logging.error(f"Fehler bei Miss Lucy: {e}")
        await update.message.reply_text(f"Groq-Fehler: {str(e)}")

def main():
    app = ApplicationBuilder().token(LUCY_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_lucy_message))
    
    print("Miss Lucy Bot läuft...")
    app.run_polling()

if __name__ == "__main__":
    main()
