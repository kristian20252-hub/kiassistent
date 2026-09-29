import os
from threading import Thread
from flask import Flask

# 1. Minimalen Webserver erstellen
app = Flask(__name__)


@app.route("/")
def home():
    return "Bot läuft!"


def run():
    # Render weist automatisch einen PORT über die Umgebungsvariable zu
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)


def keep_alive():
    t = Thread(target=run)
    t.daemon = True
    t.start()


# 2. Den Webserver ganz am Anfang aufrufen
if __name__ == "__main__":
    keep_alive()

    # Hier steht dein bisheriger Telegram-Bot-Code (z. B. app.run_polling())
