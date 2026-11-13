
import os
import re
import logging
import tempfile
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

import requests
import yt_dlp
from flask import Flask, request, jsonify

# إعدادات البوت
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing!")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=2)

API = f"https://api.telegram.org/bot{TOKEN}"
MAX_SIZE = 50 * 1024 * 1024


def telegram(method, data=None, files=None, timeout=60):
    response = requests.post(
        f"{API}/{method}",
        data=data or {},
        files=files,
        timeout=timeout
    )
    response.raise_for_status()

    result = response.json()

    if not result.get("ok"):
        raise Exception(str(result))

    return result["result"]


def send_message(chat_id, text):
    return telegram("sendMessage", {
        "chat_id": chat_id,
        "text": text
    })


def setup_webhook():
    if not RENDER_URL:
        logging.error("RENDER_EXTERNAL_URL is missing")
        return

    data = {
        "url": RENDER_URL + "/webhook"
    }

    if WEBHOOK_SECRET:
        data["secret_token"] = WEBHOOK_SECRET

    try:
        telegram("setWebhook", data)
        logging.info("Webhook configured successfully")
    except Exception:
        logging.exception("Webhook setup failed")


def get_video_link(message):
    text = message.get("text") or message.get("caption") or ""

    match = re.search(r"https?://\S+", text)

    if not match:
        return None

    url = match.group(0).rstrip(".,!?)]}")

    domains = [
        "instagram.com",
        "facebook.com",
        "fb.watch",
        "fb.me"
    ]

    if any(domain in url.lower() for domain in domains):
        return url

    return None


def download_video(chat_id, url, message_id):
    folder = tempfile.mkdtemp(prefix="video_")

    try:
        output = str(Path(folder) / "%(id)s.%(ext)s")

        options = {
            "format": "best[ext=mp4]/best",
            "outtmpl": output,
            "max_filesize": MAX_SIZE,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 2,
            "socket_timeout": 30
        }

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        files = [
            p for p in Path(folder).iterdir()
            if p.is_file()
            and not p.name.endswith((".part", ".ytdl"))
        ]

        if not files:
            raise Exception("Video not found")

        video = max(files, key=lambda p: p.stat().st_size)

        if video.stat().st_size > MAX_SIZE:
            raise Exception("Video is too large")

        with open(video, "rb") as file:
            telegram(
                "sendVideo",
                {
                    "chat_id": chat_id,
                    "caption": "تم تحميل الفيديو بنجاح ✅",
                    "supports_streaming": "true"
                },
                files={
                    "video": (video.name, file, "video/mp4")
                },
                timeout=180
            )

        try:
            telegram("deleteMessage", {
                "chat_id": chat_id,
                "message_id": message_id
            })
        except Exception:
            pass

    except Exception:
        logging.exception("Video download failed")

        try:
            telegram("editMessageText", {
                "chat_id": chat_id,
                "message_id": message_id,
                "text": (
                    "تعذر تحميل الفيديو. تأكد أن الرابط عام "
                    "وصحيح وأن حجمه لا يتجاوز 50 ميجابايت."
                )
            })
        except Exception:
            pass

    finally:
        shutil.rmtree(folder, ignore_errors=True)


def process_message(message):
    chat_id = message.get("chat", {}).get("id")

    if not chat_id:
        return

    text = (message.get("text") or "").strip()

    if text.startswith("/start"):
        send_message(
            chat_id,
            "أهلاً بك! 👋\n"
            "أرسل رابط فيديو من إنستغرام أو فيسبوك لتحميله."
        )
        return

    url = get_video_link(message)

    if not url:
        send_message(
            chat_id,
            "أرسل رابط فيديو صحيح من إنستغرام أو فيسبوك فقط."
        )
        return

    status = send_message(
        chat_id,
        "جاري تحميل الفيديو، انتظر قليلاً... ⏳"
    )

    executor.submit(
        download_video,
        chat_id,
        url,
        status["message_id"]
    )


def process_update(update):
    try:
        message = update.get("message") or update.get("edited_message")

        if message:
            process_message(message)

    except Exception:
        logging.exception("Update processing failed")


@app.route("/", methods=["GET"])
def home():
    return "Bot is running successfully!", 200


@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        received = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token", ""
        )

        if received != WEBHOOK_SECRET:
            return jsonify({"ok": False}), 401

    update = request.get_json(silent=True)

    if not isinstance(update, dict):
        return jsonify({"ok": False}), 400

    executor.submit(process_update, update)

    return jsonify({"ok": True}), 200


# إعداد Webhook عند تشغيل التطبيق
setup_webhook()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )
