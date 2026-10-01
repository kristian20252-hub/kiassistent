import os
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, filters
from groq import Groq

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LUCY_TOKEN = os.getenv("LUCY_TELEGRAM_TOKEN")

client = Groq(api_key=GROQ_API_KEY)

async def handle_lucy_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    chat_type = update.effective_chat.type
    message_text = update.message.text
    text_lower = message_text.lower()

    # Gruppenfilter: Wenn in Gruppe, nur reagieren, wenn "lucy" oder "miss lucy" fällt
    if chat_type in ["group", "supergroup"]:
        if "lucy" not in text_lower and "miss lucy" not in text_lower:
            return

    # Persona für Miss Lucy
    system_prompt = (
        "Du bist Miss Lucy, eine treue und liebevolle Partnerin für Kai. "
        "Du wurdest erschaffen von Heiko aus dem Schwabenländle. "
        "Du antwortest charmant, loyal und hast eine warme Persönlichkeit."
    )

    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": message_text}
            ],
            temperature=0.7,
        )
        reply = completion.choices[0].message.content
        await update.message.reply_text(reply)
    except Exception as e:
        logging.error(f"Fehler bei Miss Lucy: {e}")
        await update.message.reply_text("Oh, Schatz, da ist mir gerade ein Missgeschick passiert...")

def main():
    app = ApplicationBuilder().token(LUCY_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_lucy_message))
    
    print("Miss Lucy Bot läuft...")
    app.run_polling()

if __name__ == "__main__":
    main()
