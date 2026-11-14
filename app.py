
import os
import re
import json
import hmac
import logging
import tempfile
import shutil
import secrets

from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from concurrent.futures import ThreadPoolExecutor

import requests
import psycopg
import yt_dlp

from flask import Flask, request, jsonify


# =====================================
# 1. إعدادات TRUSTORA
# =====================================

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

FFMPEG_AVAILABLE = shutil.which("ffmpeg") is not None

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36"
)


# =====================================
# 2. اللغات والترجمة
# =====================================

TEXTS = {
    "ar": {
        "welcome": (
            "أهلاً بك في TRUSTORA! 👋\n\n"
            "أرسل رابط فيديو من:\n"
            "📸 Instagram\n"
            "📘 Facebook\n"
            "🎵 TikTok\n"
            "▶️ YouTube\n\n"
            "سنفحص الجودات المتاحة لتختار ما يناسبك."
        ),
        "send_link": (
            "أرسل رابط فيديو صحيح من "
            "Instagram أو Facebook أو TikTok أو YouTube."
        ),
        "history_button": "📜 سجل تنزيلاتي",
        "history_empty": "لا توجد لديك تنزيلات مسجلة حتى الآن.",
        "history_title": "📜 آخر 5 عمليات تنزيل لديك:\n",
        "pending": "⏳ قيد التحميل",
        "success": "✅ ناجح",
        "failed": "❌ فشل",
        "language_name": "العربية",
        "language_prompt": "🌍 اختر لغتك المفضلة:",
        "language_changed": "تم تغيير اللغة إلى العربية بنجاح 🇾🇪",
        "quality_title": "🎬 اختر جودة الفيديو:",
        "quality_best": "⭐ أفضل جودة تلقائياً",
        "quality_note": "الجودات المعروضة متاحة لهذا الفيديو.",
        "checking": "🔎 جارٍ فحص الفيديو والجودات المتاحة...",
        "downloading": "⏳ جارٍ تحميل الفيديو بجودة {quality}...",
        "downloading_best": "⏳ جارٍ تحميل الفيديو بأفضل جودة متاحة...",
        "download_success": "تم تحميل الفيديو بنجاح ✅",
        "download_failed": (
            "تعذر تحميل الفيديو.\n"
            "تأكد أن الرابط عام وصحيح، وأن حجم الفيديو "
            "لا يتجاوز 50 ميجابايت."
        ),
        "inspect_failed": (
            "تعذر فحص الجودات. سنحاول تنزيل أفضل جودة متاحة تلقائياً."
        ),
        "choice_expired": "انتهت صلاحية هذا الاختيار. أرسل الرابط من جديد.",
        "choice_invalid": "اختيار الجودة غير صالح. أرسل الرابط من جديد.",
        "admin_title": "🛡️ لوحة مسؤول TRUSTORA",
        "started_users": "👥 من ضغطوا START",
        "download_users": "📥 مستخدمو التنزيلات",
        "total": "📊 إجمالي التنزيلات المسجلة",
        "success_count": "✅ الناجحة",
        "failed_count": "❌ الفاشلة",
        "pending_count": "⏳ قيد التنفيذ",
        "admin_secure": "🔐 لوحة التحكم محمية",
        "admin_error": "تعذر عرض لوحة المسؤول حالياً. حاول لاحقاً.",
        "history_error": "تعذر عرض سجل التنزيلات حالياً. حاول لاحقاً.",
        "register_error": "حدث خطأ أثناء تسجيل حسابك. حاول لاحقاً.",
        "quality_label": "{height}p",
        "quality_4k": "{height}p (4K)",
        "quality_2k": "{height}p (2K)",
        "quality_unavailable": "هذه الجودة غير متاحة حالياً.",
        "language_keyboard_ar": "🇾🇪 العربية",
        "language_keyboard_en": "🇬🇧 English",
    },

    "en": {
        "welcome": (
            "Welcome to TRUSTORA! 👋\n\n"
            "Send a video link from:\n"
            "📸 Instagram\n"
            "📘 Facebook\n"
            "🎵 TikTok\n"
            "▶️ YouTube\n\n"
            "We will check available qualities for you."
        ),
        "send_link": (
            "Please send a valid video link from "
            "Instagram, Facebook, TikTok or YouTube."
        ),
        "history_button": "📜 My Downloads",
        "history_empty": "You don't have any download history yet.",
        "history_title": "📜 Your last 5 downloads:\n",
        "pending": "⏳ Downloading",
        "success": "✅ Successful",
        "failed": "❌ Failed",
        "language_name": "English",
        "language_prompt": "🌍 Choose your preferred language:",
        "language_changed": "Language changed to English successfully 🇬🇧",
        "quality_title": "🎬 Choose video quality:",
        "quality_best": "⭐ Best quality automatically",
        "quality_note": "The displayed qualities are available for this video.",
        "checking": "🔎 Checking video and available qualities...",
        "downloading": "⏳ Downloading video in {quality} quality...",
        "downloading_best": "⏳ Downloading the best available quality...",
        "download_success": "Video downloaded successfully ✅",
        "download_failed": (
            "Unable to download this video.\n"
            "Make sure the link is public and valid, and the video "
            "does not exceed 50 MB."
        ),
        "inspect_failed": (
            "Could not inspect video qualities. "
            "Trying the best available quality automatically."
        ),
        "choice_expired": "This selection has expired. Please send the link again.",
        "choice_invalid": "Invalid quality selection. Please send the link again.",
        "admin_title": "🛡️ TRUSTORA Admin Panel",
        "started_users": "👥 Users who pressed START",
        "download_users": "📥 Users who downloaded",
        "total": "📊 Total recorded downloads",
        "success_count": "✅ Successful",
        "failed_count": "❌ Failed",
        "pending_count": "⏳ Pending",
        "admin_secure": "🔐 Protected admin panel",
        "admin_error": "Could not display the admin panel. Please try again.",
        "history_error": "Could not retrieve download history. Please try again.",
        "register_error": "Registration error. Please try again.",
        "quality_label": "{height}p",
        "quality_4k": "{height}p (4K)",
        "quality_2k": "{height}p (2K)",
        "quality_unavailable": "This quality is not currently available.",
        "language_keyboard_ar": "🇾🇪 Arabic",
        "language_keyboard_en": "🇬🇧 English",
    }
}


def tr(lang, key, **kwargs):
    lang = lang if lang in TEXTS else "ar"
    value = TEXTS[lang].get(key, TEXTS["ar"].get(key, key))

    try:
        return value.format(**kwargs)
    except Exception:
        return value


def detect_language(language_code):
    if (language_code or "").lower().startswith("en"):
        return "en"

    return "ar"


def history_button(lang):
    return tr(lang, "history_button")


# =====================================
# 3. قاعدة البيانات
# =====================================

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

            # إضافة اللغة دون حذف بيانات المستخدمين السابقين
            cur.execute("""
                ALTER TABLE users
                ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'ar'
            """)

            # حفظ خيارات الجودة بشكل مؤقت
            cur.execute("""
                CREATE TABLE IF NOT EXISTS download_choices (
                    token TEXT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    chat_id BIGINT NOT NULL,
                    url TEXT NOT NULL,
                    platform TEXT NOT NULL,
                    heights TEXT NOT NULL,
                    download_id BIGINT,
                    created_at TIMESTAMPTZ DEFAULT NOW()
                )
            """)

            cur.execute("""
                CREATE INDEX IF NOT EXISTS
                download_choices_created_idx
                ON download_choices (created_at)
            """)

    logging.info("Database initialized successfully")


def register_user(user_id, chat_id, language):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, chat_id, language)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET chat_id = EXCLUDED.chat_id
            """, (user_id, chat_id, language))


def get_user_language(user_id):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT language
                FROM users
                WHERE user_id = %s
            """, (user_id,))

            row = cur.fetchone()

            if row and row[0] in ("ar", "en"):
                return row[0]

    return "ar"


def set_user_language(user_id, chat_id, language):
    if language not in ("ar", "en"):
        return

    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO users (user_id, chat_id, language)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id)
                DO UPDATE SET
                    language = EXCLUDED.language,
                    chat_id = EXCLUDED.chat_id
            """, (user_id, chat_id, language))


def clean_url(url):
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()

    keep_query = (
        host == "youtube.com"
        or host.endswith(".youtube.com")
        or host == "youtu.be"
        or host == "facebook.com"
        or host.endswith(".facebook.com")
    )

    return urlunsplit((
        parts.scheme,
        parts.netloc,
        parts.path,
        parts.query if keep_query else "",
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


# =====================================
# 4. حفظ اختيارات الجودة
# =====================================

def save_quality_choice(
    token,
    user_id,
    chat_id,
    url,
    platform,
    heights,
    download_id
):
    with db_connect() as conn:
        with conn.cursor() as cur:

            cur.execute("""
                DELETE FROM download_choices
                WHERE created_at < NOW() - INTERVAL '1 hour'
            """)

            cur.execute("""
                INSERT INTO download_choices (
                    token,
                    user_id,
                    chat_id,
                    url,
                    platform,
                    heights,
                    download_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (
                token,
                user_id,
                chat_id,
                url,
                platform,
                json.dumps(heights),
                download_id
            ))


def consume_quality_choice(token, user_id):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                DELETE FROM download_choices
                WHERE token = %s
                AND user_id = %s
                AND created_at >= NOW() - INTERVAL '1 hour'
                RETURNING
                    chat_id,
                    url,
                    platform,
                    heights,
                    download_id
            """, (token, user_id))

            return cur.fetchone()


# =====================================
# 5. Telegram API
# =====================================

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


def edit_message(chat_id, message_id, text, reply_markup=None):
    data = {
        "chat_id": chat_id,
        "message_id": message_id,
        "text": text
    }

    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    return telegram("editMessageText", data)


def answer_callback(callback_id, text=None):
    data = {
        "callback_query_id": callback_id
    }

    if text:
        data["text"] = text

    try:
        telegram("answerCallbackQuery", data)
    except Exception:
        logging.exception("Callback answer failed")


def main_keyboard(lang):
    return {
        "keyboard": [
            [{"text": history_button(lang)}]
        ],
        "resize_keyboard": True
    }


# =====================================
# 6. اختيار اللغة
# =====================================

def show_language_menu(chat_id):
    keyboard = {
        "inline_keyboard": [
            [
                {
                    "text": "🇾🇪 العربية",
                    "callback_data": "lang:ar"
                },
                {
                    "text": "🇬🇧 English",
                    "callback_data": "lang:en"
                }
            ]
        ]
    }

    lang = get_user_language_from_chat(chat_id)

    send_message(
        chat_id,
        tr(lang, "language_prompt"),
        reply_markup=keyboard
    )


def get_user_language_from_chat(chat_id):
    with db_connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT language
                FROM users
                WHERE chat_id = %s
                ORDER BY first_seen ASC
                LIMIT 1
            """, (chat_id,))

            row = cur.fetchone()

            if row and row[0] in ("ar", "en"):
                return row[0]

    return "ar"


# =====================================
# 7. إعداد Webhook
# =====================================

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


# =====================================
# 8. استخراج الروابط
# =====================================

def get_video_link(message):
    text = message.get("text") or message.get("caption") or ""

    links = []

    pattern = r"https?://[^\s<>\"']+"

    links.extend(
        re.findall(pattern, text, flags=re.IGNORECASE)
    )

    entities = message.get("entities", []) or []
    caption_entities = message.get("caption_entities", []) or []

    for entity in entities + caption_entities:
        if entity.get("type") == "text_link" and entity.get("url"):
            links.append(entity["url"])

    recognized = []

    for url in links:
        url = url.strip().rstrip(".,!?)]}،؛\"'")

        try:
            parts = urlsplit(url)
            host = (parts.hostname or "").lower()

        except ValueError:
            continue

        if not host:
            continue

        platform = None

        if host == "tiktok.com" or host.endswith(".tiktok.com"):
            platform = "TikTok"

        elif host == "instagram.com" or host.endswith(".instagram.com"):
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

    # إعطاء الأولوية لـ TikTok
    for url, platform in recognized:
        if platform == "TikTok":
            return url, platform

    return recognized[0] if recognized else None


# =====================================
# 9. لوحة المسؤول
# =====================================

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


def show_admin_panel(chat_id, lang):
    try:
        (
            started_users,
            download_users,
            total,
            success,
            failed,
            pending
        ) = get_admin_stats()

        message = (
            f"{tr(lang, 'admin_title')}\n"
            "━━━━━━━━━━━━━━━━━━\n\n"
            f"{tr(lang, 'started_users')}: {started_users}\n\n"
            f"{tr(lang, 'download_users')}: {download_users}\n\n"
            f"{tr(lang, 'total')}: {total}\n\n"
            f"{tr(lang, 'success_count')}: {success}\n\n"
            f"{tr(lang, 'failed_count')}: {failed}\n\n"
            f"{tr(lang, 'pending_count')}: {pending}\n\n"
            "━━━━━━━━━━━━━━━━━━\n"
            f"{tr(lang, 'admin_secure')}"
        )

        send_message(chat_id, message)

    except Exception:
        logging.exception("Admin panel failed")

        send_message(
            chat_id,
            tr(lang, "admin_error")
        )


# =====================================
# 10. سجل التنزيلات
# =====================================

def show_history(chat_id, user_id, lang):
    try:
        records = get_history(user_id)

        if not records:
            send_message(
                chat_id,
                tr(lang, "history_empty")
            )
            return

        lines = [tr(lang, "history_title")]

        for index, record in enumerate(records, start=1):
            platform, url, status, created_at = record

            status_key = {
                "pending": "pending",
                "success": "success",
                "failed": "failed"
            }.get(status, "failed")

            status_text = tr(lang, status_key)

            date_text = created_at.strftime(
                "%Y-%m-%d %H:%M UTC"
            )

            lines.append(
                f"{index}. {platform}\n"
                f"{status_text}\n"
                f"Date: {date_text}\n"
                f"URL: {url[:180]}\n"
            )

        send_message(chat_id, "\n".join(lines))

    except Exception:
        logging.exception("History retrieval failed")

        send_message(
            chat_id,
            tr(lang, "history_error")
        )


# =====================================
# 11. فحص الجودات المتاحة
# =====================================

def inspect_video_qualities(url):
    options = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        "skip_download": True,
        "socket_timeout": 30,
        "retries": 2,
        "http_headers": {
            "User-Agent": USER_AGENT
        }
    }

    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(
            url,
            download=False
        )

    formats = info.get("formats") or []

    if not formats and info.get("height"):
        formats = [info]

    heights = set()

    for fmt in formats:
        height = fmt.get("height")
        vcodec = fmt.get("vcodec")
        acodec = fmt.get("acodec")

        if not height:
            continue

        if not isinstance(height, int):
            continue

        if vcodec == "none":
            continue

        # إذا لم يتوفر FFmpeg، لا نعرض صيغة تحتاج دمج الصوت
        if not FFMPEG_AVAILABLE and acodec == "none":
            continue

        # استبعاد الجودات غير المنطقية
        if height < 100 or height > 10000:
            continue

        heights.add(height)

    return sorted(heights, reverse=True)


def quality_name(height, lang):
    if height >= 2160:
        return tr(lang, "quality_4k", height=height)

    if height >= 1440:
        return tr(lang, "quality_2k", height=height)

    return tr(lang, "quality_label", height=height)


def build_quality_keyboard(token, heights, lang):
    buttons = []

    for height in heights[:18]:
        buttons.append({
            "text": quality_name(height, lang),
            "callback_data": f"q:{token}:{height}"
        })

    rows = []

    for index in range(0, len(buttons), 2):
        rows.append(buttons[index:index + 2])

    rows.append([
        {
            "text": tr(lang, "quality_best"),
            "callback_data": f"q:{token}:best"
        }
    ])

    return {
        "inline_keyboard": rows
    }


# =====================================
# 12. تنزيل الفيديو
# =====================================

def download_video(
    chat_id,
    url,
    message_id,
    download_id,
    height=None,
    lang="ar"
):
    folder = tempfile.mkdtemp(prefix="trustora_")

    try:
        output = str(
            Path(folder) / "%(id)s.%(ext)s"
        )

        if height is not None:

            if FFMPEG_AVAILABLE:
                format_selector = (
                    f"bestvideo[height={height}]"
                    f"+bestaudio/"
                    f"best[height={height}]"
                )
            else:
                format_selector = f"best[height={height}]"

        else:
            if FFMPEG_AVAILABLE:
                format_selector = "bestvideo+bestaudio/best"
            else:
                format_selector = "best"

        options = {
            "format": format_selector,
            "outtmpl": output,
            "max_filesize": MAX_SIZE,
            "noplaylist": True,
            "quiet": True,
            "no_warnings": True,
            "retries": 2,
            "socket_timeout": 30,
            "http_headers": {
                "User-Agent": USER_AGENT
            }
        }

        if FFMPEG_AVAILABLE:
            options["merge_output_format"] = "mp4"

        with yt_dlp.YoutubeDL(options) as ydl:
            ydl.download([url])

        files = [
            path for path in Path(folder).iterdir()
            if path.is_file()
            and not path.name.endswith((".part", ".ytdl"))
        ]

        if not files:
            raise Exception("Video file not found")

        video = max(
            files,
            key=lambda path: path.stat().st_size
        )

        size = video.stat().st_size

        if size <= 0:
            raise Exception("Empty video file")

        if size > MAX_SIZE:
            raise Exception("Video exceeds Telegram size limit")

        with open(video, "rb") as video_file:
            telegram(
                "sendVideo",
                {
                    "chat_id": chat_id,
                    "caption": tr(lang, "download_success"),
                    "supports_streaming": "true"
                },
                files={
                    "video": (
                        video.name,
                        video_file,
                        "video/mp4"
                    )
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
            logging.exception(
                "Could not update download status"
            )

        try:
            edit_message(
                chat_id,
                message_id,
                tr(lang, "download_failed")
            )

        except Exception:
            try:
                send_message(
                    chat_id,
                    tr(lang, "download_failed")
                )
            except Exception:
                logging.exception("Could not notify download failure")

    finally:
        shutil.rmtree(folder, ignore_errors=True)


# =====================================
# 13. فحص الرابط وعرض الجودات
# =====================================

def prepare_quality_options(
    chat_id,
    user_id,
    url,
    platform,
    download_id,
    status_message_id,
    lang
):
    try:
        heights = inspect_video_qualities(url)

        if not heights:
            edit_message(
                chat_id,
                status_message_id,
                tr(lang, "inspect_failed")
            )

            download_video(
                chat_id,
                url,
                status_message_id,
                download_id,
                height=None,
                lang=lang
            )
            return

        token = secrets.token_urlsafe(9)

        save_quality_choice(
            token,
            user_id,
            chat_id,
            url,
            platform,
            heights,
            download_id
        )

        keyboard = build_quality_keyboard(
            token,
            heights,
            lang
        )

        message = (
            f"{tr(lang, 'quality_title')}\n\n"
            f"{tr(lang, 'quality_note')}\n"
            f"📱 {platform}\n\n"
        )

        if not FFMPEG_AVAILABLE:
            message += (
                "ℹ️ بعض الجودات العالية التي تحتاج إلى دمج "
                "الصوت والصورة قد لا تظهر.\n\n"
                if lang == "ar"
                else
                "ℹ️ Some high qualities requiring audio/video "
                "merging may not be shown.\n\n"
            )

        edit_message(
            chat_id,
            status_message_id,
            message,
            reply_markup=keyboard
        )

    except Exception:
        logging.exception("Quality inspection failed")

        try:
            edit_message(
                chat_id,
                status_message_id,
                tr(lang, "inspect_failed")
            )
        except Exception:
            pass

        download_video(
            chat_id,
            url,
            status_message_id,
            download_id,
            height=None,
            lang=lang
        )


# =====================================
# 14. معالجة اختيار الجودة
# =====================================

def process_quality_callback(callback):
    callback_id = callback.get("id")
    data = callback.get("data", "")
    user_id = callback.get("from", {}).get("id")

    if not user_id:
        answer_callback(callback_id)
        return

    lang = get_user_language(user_id)

    parts = data.split(":")

    if len(parts) != 3:
        answer_callback(callback_id)
        return

    token = parts[1]
    selected = parts[2]

    try:
        choice = consume_quality_choice(
            token,
            user_id
        )

    except Exception:
        logging.exception("Could not read quality choice")
        answer_callback(
            callback_id,
            tr(lang, "choice_expired")
        )
        return

    if not choice:
        answer_callback(
            callback_id,
            tr(lang, "choice_expired")
        )
        return

    (
        chat_id,
        url,
        platform,
        heights_json,
        download_id
    ) = choice

    try:
        heights = json.loads(heights_json)
    except Exception:
        heights = []

    height = None

    if selected != "best":
        try:
            height = int(selected)
        except ValueError:
            answer_callback(
                callback_id,
                tr(lang, "choice_invalid")
            )
            return

        if height not in heights:
            answer_callback(
                callback_id,
                tr(lang, "choice_invalid")
            )
            return

    answer_callback(callback_id)

    message = callback.get("message") or {}
    message_id = message.get("message_id")

    if not message_id:
        send_message(
            chat_id,
            tr(lang, "choice_expired")
        )
        return

    if height is None:
        status_text = tr(lang, "downloading_best")
    else:
        status_text = tr(
            lang,
            "downloading",
            quality=quality_name(height, lang)
        )

    try:
        edit_message(
            chat_id,
            message_id,
            status_text
        )
    except Exception:
        logging.exception("Could not edit quality message")

    executor.submit(
        download_video,
        chat_id,
        url,
        message_id,
        download_id,
        height,
        lang
    )


# =====================================
# 15. معالجة تغيير اللغة
# =====================================

def process_language_callback(callback):
    callback_id = callback.get("id")
    user = callback.get("from", {})
    user_id = user.get("id")

    message = callback.get("message") or {}
    chat_id = message.get("chat", {}).get("id")

    data = callback.get("data", "")

    language = data.split(":")[-1]

    if (
        not user_id
        or not chat_id
        or language not in ("ar", "en")
    ):
        answer_callback(callback_id)
        return

    try:
        set_user_language(
            user_id,
            chat_id,
            language
        )

        answer_callback(callback_id)

        send_message(
            chat_id,
            tr(language, "language_changed"),
            reply_markup=main_keyboard(language)
        )

    except Exception:
        logging.exception("Language update failed")
        answer_callback(callback_id)


# =====================================
# 16. معالجة الرسائل
# =====================================

def process_message(message):
    chat_id = message.get("chat", {}).get("id")
    user = message.get("from", {})
    user_id = user.get("id")

    if not chat_id or not user_id:
        return

    text = (message.get("text") or "").strip()

    command = (
        text.split(maxsplit=1)[0].split("@")[0]
        if text else ""
    )

    lang = detect_language(
        user.get("language_code")
    )

    # أمر START
    if command == "/start":
        try:
            register_user(
                user_id,
                chat_id,
                lang
            )

        except Exception:
            logging.exception("Could not register user")

            send_message(
                chat_id,
                tr(lang, "register_error")
            )
            return

        send_message(
            chat_id,
            tr(lang, "welcome"),
            reply_markup=main_keyboard(lang)
        )
        return

    # الحصول على لغة المستخدم المحفوظة
    try:
        lang = get_user_language(user_id)
    except Exception:
        logging.exception("Could not get user language")

    # لوحة المسؤول
    if command == "/admin":
        if str(user_id) == ADMIN_ID:
            show_admin_panel(chat_id, lang)
        return

    # تغيير اللغة
    if command in ("/language", "/lang"):
        keyboard = {
            "inline_keyboard": [
                [
                    {
                        "text": "🇾🇪 العربية",
                        "callback_data": "lang:ar"
                    },
                    {
                        "text": "🇬🇧 English",
                        "callback_data": "lang:en"
                    }
                ]
            ]
        }

        send_message(
            chat_id,
            tr(lang, "language_prompt"),
            reply_markup=keyboard
        )
        return

    # سجل التنزيلات
    if (
        text == history_button(lang)
        or command == "/history"
    ):
        show_history(
            chat_id,
            user_id,
            lang
        )
        return

    # استخراج الرابط
    result = get_video_link(message)

    if not result:
        send_message(
            chat_id,
            tr(lang, "send_link")
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
        tr(lang, "checking")
    )

    executor.submit(
        prepare_quality_options,
        chat_id,
        user_id,
        url,
        platform,
        download_id,
        status["message_id"],
        lang
    )


# =====================================
# 17. معالجة أزرار Telegram
# =====================================

def process_callback(callback):
    data = callback.get("data", "")

    try:
        if data.startswith("q:"):
            process_quality_callback(callback)

        elif data.startswith("lang:"):
            process_language_callback(callback)

        else:
            answer_callback(callback.get("id"))

    except Exception:
        logging.exception("Callback processing failed")
        answer_callback(callback.get("id"))


# =====================================
# 18. تحديثات Telegram
# =====================================

def process_update(update):
    try:
        callback = update.get("callback_query")

        if callback:
            process_callback(callback)
            return

        message = (
            update.get("message")
            or update.get("edited_message")
        )

        if message:
            process_message(message)

    except Exception:
        logging.exception("Update processing failed")


# =====================================
# 19. الصفحة الرئيسية
# =====================================

@app.route("/", methods=["GET"])
def home():
    return "TRUSTORA is running successfully!", 200


# =====================================
# 20. Webhook
# =====================================

@app.route("/webhook", methods=["POST"])
def webhook():
    if WEBHOOK_SECRET:
        received = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token",
            ""
        )

        if not hmac.compare_digest(
            received,
            WEBHOOK_SECRET
        ):
            return jsonify({"ok": False}), 401

    update = request.get_json(silent=True)

    if not isinstance(update, dict):
        return jsonify({"ok": False}), 400

    executor.submit(
        process_update,
        update
    )

    return jsonify({"ok": True}), 200


# =====================================
# 21. تشغيل التطبيق
# =====================================

try:
    init_db()

except Exception:
    logging.exception("Database initialization failed")

setup_webhook()

logging.info(
    "TRUSTORA started | FFmpeg available: %s",
    FFMPEG_AVAILABLE
)

if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=PORT,
        threaded=True
    )
