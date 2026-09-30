import base64
from telegram.ext import MessageHandler, filters


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Empfängt ein Foto von Telegram und analysiert es mit Groq Vision."""
    chat_id = update.effective_chat.id

    # Das Foto in höchster Auflösung holen
    photo_file = await update.message.photo[-1].get_file()

    # Bild herunterladen und in Base64 umwandeln
    photo_bytes = await photo_file.download_as_bytearray()
    base64_image = base64.b64encode(photo_bytes).decode("utf-8")

    # Bild-Beschreibung / Prompt vom Nutzer (falls ein Text mitgeschickt wurde)
    caption = (
        update.message.caption
        or "Beschreibe dieses Bild und was darauf zu sehen ist."
    )

    # Nachricht für das Vision-Modell aufbauen
    messages_payload = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": caption},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    },
                },
            ],
        },
    ]

    try:
        # Ein Vision-fähiges Modell bei Groq verwenden
        response = groq_client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            messages=messages_payload,
            temperature=0.7,
        )
        reply = response.choices[0].message.content
        await update.message.reply_text(reply)
    except Exception as e:
        await update.message.reply_text(
            f"Fehler bei der Bildverarbeitung: {e}"
        )


# In main() unter den anderen Handlern hinzufügen:
# bot_app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

