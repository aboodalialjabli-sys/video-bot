
import os
import re
import json
import hmac
import logging
import tempfile
import shutil

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor

import requests
import psycopg
import yt_dlp

from flask import Flask, request, jsonify


# ==============================
# إعدادات البوت
# ==============================

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
PORT = int(os.environ.get("PORT", 10000))
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
DATABASE_URL = os.environ.get("DATABASE_URL")
ADMIN_ID = os.environ.get("ADMIN_ID", "").strip()

if not TOKEN:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is missing!")

if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is missing!")

if not ADMIN_ID.isdigit():
    raise RuntimeError("ADMIN_ID is missing or invalid!")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

app = Flask(__name__)
executor = ThreadPoolExecutor(max_workers=2)

API = f"https://api.telegram.org/bot{TOKEN}"
MAX_SIZE = 50 * 1024 * 1024

HISTORY_BUTTON = "📜 سجل تنزيلاتي"


# ==============================
# قاعدة البيانات
# ==============================

def db_connect():
    return psycopg.connect(
        DATABASE_URL,
        connect_timeout=10
    )


def init_db():
    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                CREATE TABLE IF NOT EXISTS downloads (
                    id BIGSERIAL PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    url TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS
                downloads_user_date_idx
                ON downloads (user_id, created_at DESC)
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    chat_id BIGINT NOT NULL,
                    first_seen TIMESTAMPTZ DEFAULT NOW()
                )
            """)

    logging.info("Database initialized successfully")


def register_user(user_id, chat_id):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, chat_id)
                VALUES (%s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id, chat_id))


def clean_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()

    # الاحتفاظ بمعاملات YouTube وFacebook
    if (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtu.be"
        or host == "facebook.com"
        or host.endswith(".facebook.com")
    ):
        query = parts.query
    else:
        query = ""

    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        query,
        ""
    ))


def save_download(user_id, chat_id, url, platform):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO downloads
                (user_id, chat_id, url, platform, status)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING id
            """, (
                user_id,
                chat_id,
                clean_url(url),
                platform,
                "pending"
            ))

            download_id = cur.fetchone()[0]

            # الاحتفاظ بآخر 5 عمليات لكل مستخدم
            cur.execute("""
                DELETE FROM downloads
                WHERE user_id = %s
                AND id NOT IN (
                    SELECT id
                    FROM downloads
                    WHERE user_id = %s
                    ORDER BY created_at DESC, id DESC
                    LIMIT 5
                )
            """, (user_id, user_id))

    return download_id


def update_download(download_id, status):
    if not download_id:
        return

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                UPDATE downloads
                SET status = %s
                WHERE id = %s
            """, (status, download_id))


def get_history(user_id):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT platform, url, status, created_at
                FROM downloads
                WHERE user_id = %s
                ORDER BY created_at DESC, id DESC
                LIMIT 5
            """, (user_id,))

            return cur.fetchall()


# ==============================
# لوحة المسؤول
# ==============================

def get_admin_stats():
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    (SELECT COUNT(*) FROM users),
                    COUNT(DISTINCT user_id),
                    COUNT(*),
                    COUNT(*) FILTER (WHERE status = 'success'),
                    COUNT(*) FILTER (WHERE status = 'failed'),
                    COUNT(*) FILTER (WHERE status = 'pending')
                FROM downloads
            """)

            return cur.fetchone()


def show_admin_panel(chat_id):
    try:
        stats = get_admin_stats()

        (
            started_users,
            download_users,
            total,
            success,
            failed,
            pending
        ) = stats

        message = (
            "🛡️ لوحة مسؤول TRUSTORA\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"👥 من ضغطوا START: {started_users}\n\n"
            f"📥 مستخدمو التنزيلات: {download_users}\n\n"
            f"📊 إجمالي التنزيلات المسجلة: {total}\n\n"
            f"✅ الناجحة: {success}\n\n"
            f"❌ الفاشلة: {failed}\n\n"
            f"⏳ قيد التنفيذ: {pending}\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "🔐 لوحة التحكم محمية"
        )

        send_message(chat_id, message)

    except Exception:
        logging.exception("Admin panel failed")

        send_message(
            chat_id,
            "تعذر عرض لوحة المسؤول حالياً. حاول لاحقاً."
        )


# ==============================
# Telegram API
# ==============================

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


def send_message(chat_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "text": text
    }

    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    return telegram("sendMessage", data)


def main_keyboard():
    return {
        "keyboard": [
            [{"text": HISTORY_BUTTON}]
        ],
        "resize_keyboard": True
    }


# ==============================
# إعداد Webhook
# ==============================

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


# ==============================
# استخراج الروابط من الرسالة
# ==============================

def get_video_link(message):
    text = message.get("text") or message.get("caption") or ""

    links = []

    # استخراج الروابط المكتوبة داخل النص
    pattern = (
        r"""(?i)(?:https?://)?"""
        r"""(?:[a-z0-9-]+\.)+[a-z]{2,}"""
        r"""(?::\d+)?(?:/[^\s<>\"']*)?"""
    )

    found_links = re.findall(pattern, text)

    links.extend(found_links)

    # دعم الروابط المخفية القابلة للنقر في Telegram
    entities = (
        message.get("entities", [])
        or message.get("caption_entities", [])
    )

    for entity in entities:
        if entity.get("type") == "text_link":
            entity_url = entity.get("url")

            if entity_url:
                links.append(entity_url)

    # تنظيف الروابط والتحقق من نطاقاتها
    recognized = []

    for url in links:
        url = url.strip()
        url = url.rstrip(".,!?)]}،؛\"'")

        if not url.lower().startswith(("http://", "https://")):
            url = "https://" + url

        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()
        except ValueError:
            continue

        if not host:
            continue

        # منع الروابط التي لا تنتمي للمنصات المدعومة
        platform = None

        if (
            host == "tiktok.com"
            or host.endswith(".tiktok.com")
        ):
            platform = "TikTok"

        elif (
            host == "instagram.com"
            or host.endswith(".instagram.com")
        ):
            platform = "Instagram"

        elif (
            host == "facebook.com"
            or host.endswith(".facebook.com")
            or host == "fb.watch"
            or host.endswith(".fb.watch")
            or host == "fb.me"
            or host.endswith(".fb.me")
        ):
            platform = "Facebook"

        elif (
            host == "youtu.be"
            or host.endswith(".youtu.be")
            or host == "youtube.com"
            or host.endswith(".youtube.com")
            or host == "youtube-nocookie.com"
            or host.endswith(".youtube-nocookie.com")
        ):
            platform = "YouTube"

        if platform:
            recognized.append((url, platform))

    # إعطاء الأولوية لروابط TikTok
    for url, platform in recognized:
        if platform == "TikTok":
            return url, platform

    if recognized:
        return recognized[0]

    return None


# ==============================
# سجل التنزيلات
# ==============================

def show_history(chat_id, user_id):
    try:
        records = get_history(user_id)

        if not records:
            send_message(
                chat_id,
                "لا توجد لديك تنزيلات مسجلة حتى الآن."
            )
            return

        lines = ["📜 آخر 5 عمليات تنزيل لديك:\n"]

        for index, record in enumerate(records, start=1):
            platform, url, status, created_at = record

            status_text = {
                "pending": "⏳ قيد التحميل",
                "success": "✅ ناجح",
                "failed": "❌ فشل"
            }.get(status, status)

            date_text = created_at.strftime(
                "%Y-%m-%d %H:%M UTC"
            )

            lines.append(
                f"{index}. {platform}\n"
                f"الحالة: {status_text}\n"
                f"التاريخ: {date_text}\n"
                f"الرابط: {url[:180]}\n"
            )

        send_message(chat_id, "\n".join(lines))

    except Exception:
        logging.exception("History retrieval failed")

        send_message(
            chat_id,
            "تعذر عرض سجل التنزيلات حالياً. حاول لاحقاً."
        )


# ==============================
# تنزيل الفيديو
# ==============================

def download_video(chat_id, url, message_id, download_id):
    folder = tempfile.mkdtemp(prefix="video_")

    try:
        output = str(Path(folder) / "%(id)s.%(ext)s")
       
options = {
    "format": "best[ext=mp4]/best",
    "user_agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
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

        update_download(download_id, "success")

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
            update_download(download_id, "failed")
        except Exception:
            logging.exception("Could not update download status")

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


# ==============================
# معالجة الرسائل
# ==============================

def process_message(message):
    chat_id = message.get("chat", {}).get("id")
    user_id = message.get("from", {}).get("id")

    if not chat_id or not user_id:
        return

    text = (message.get("text") or "").strip()

    command = (
        text.split(maxsplit=1)[0].split("@")[0]
        if text else ""
    )

    # لوحة المسؤول
    if command == "/admin":
        if str(user_id) == ADMIN_ID:
            show_admin_panel(chat_id)
        return

    # تسجيل مستخدمي START
    if command == "/start":
        try:
            register_user(user_id, chat_id)
        except Exception:
            logging.exception("Could not register user")

            send_message(
                chat_id,
                "حدث خطأ أثناء تسجيل حسابك. حاول لاحقاً."
            )
            return

        send_message(
            chat_id,
            "أهلاً بك في TRUSTORA! 👋\n\n"
            "أرسل رابط فيديو من:\n"
            "📸 Instagram\n"
            "📘 Facebook\n"
            "🎵 TikTok\n"
            "▶️ YouTube\n\n"
            "يمكنك أيضاً عرض آخر تنزيلاتك من الزر بالأسفل.",
            reply_markup=main_keyboard()
        )
        return

    if text == HISTORY_BUTTON or command == "/history":
        show_history(chat_id, user_id)
        return

    result = get_video_link(message)

    if not result:
        send_message(
            chat_id,
            "أرسل رابط فيديو صحيح من Instagram أو Facebook "
            "أو TikTok أو YouTube."
        )
        return

    url, platform = result

    download_id = None

    try:
        download_id = save_download(
            user_id,
            chat_id,
            url,
            platform
        )
    except Exception:
        logging.exception("Could not save download record")

    status = send_message(
        chat_id,
        f"جاري تحميل فيديو {platform}، انتظر قليلاً... ⏳"
    )

    executor.submit(
        download_video,
        chat_id,
        url,
        status["message_id"],
        download_id
    )


# ==============================
# تحديثات Telegram
# ==============================

def process_update(update):
    try:
        message = update.get("message") or update.get("edited_message")

        if message:
            process_message(message)

    except Exception:
        logging.exception("Update processing failed")


# ==============================
# الصفحة الرئيسية
# ==============================

@app.route("/", methods=["GET"])
def home():
    return "TRUSTORA is running successfully!", 200


# ==============================
# Webhook
# ==============================

@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        received = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token", ""
        )

        if not hmac.compare_digest(received, WEBHOOK_SECRET):
            return jsonify({"ok": False}), 401

    update = request.get_json(silent=True)

    if not isinstance(update, dict):
        return jsonify({"ok": False}), 400

    executor.submit(process_update, update)

    return jsonify({"ok": True}), 200


# ==============================
# تشغيل التطبيق
# ==============================

try:
    init_db()
except Exception:
    logging.exception("Database initialization failed")


setup_webhook()


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )
