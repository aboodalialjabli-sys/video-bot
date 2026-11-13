import os
import logging
import asyncio
import urllib.request
from flask import Flask, request
import nest_asyncio
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import yt_dlp

# تطبيق حل تعارض حلقة الأحداث نهائياً
nest_asyncio.apply()

# إعداد السجل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# توكن البوت الخاص بك
TOKEN = "9263521777:AAH4SMf96rRxghm8vNRLosueiNZoWtqg1-Y"
PORT = int(os.environ.get('PORT', 8080))
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL')

app = Flask(__name__)

# بناء تطبيق التيليجرام
telegram_app = ApplicationBuilder().token(TOKEN).concurrent_updates(True).build()

async def initialize_bot():
    await telegram_app.initialize()

# تهيئة البوت عند البدء
loop = asyncio.get_event_loop()
loop.run_until_complete(initialize_bot())

# رسالة الترحيب
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_text = (
        f"أهلاً بك يا {user_name} !\n"
        "مرحباً بك في بوت تحميل الفيديوهات من:\n"
        "• إنستغرام (Instagram)\n"
        "• فيسبوك (Facebook)\n\n"
        "أرسل رابط الفيديو من إنستا أو الفيس وسأقوم بتحميله فوراً 👇"
    )
    await update.message.reply_text(welcome_text)

# وظيفة تحميل الفيديو
async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    if not ("instagram.com" in url or "facebook.com" in url or "fb.watch" in url or "fb.me" in url):
        await update.message.reply_text("عذراً، هذا البوت مخصص لتحميل فيديوهات إنستغرام وفيسبوك فقط!")
        return

    msg = await update.message.reply_text("جاري تحميل الفيديو، لطفاً انتظر قليلاً...")

    ydl_opts = {
        'format': 'best',
        'outtmpl': 'video.mp4',
        'max_filesize': 50 * 1024 * 1024,
    }

    try:
        if os.path.exists("video.mp4"):
            os.remove("video.mp4")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists("video.mp4"):
            await update.message.reply_video(video=open("video.mp4", "rb"), caption="تم التحميل بواسطة البوت بنجاح ✅")
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
            os.remove("video.mp4")
        else:
            await msg.edit_text("حدث خطأ أثناء التحميل. تأكد من أن الرابط عام وصحيح.")

    except Exception as e:
        logging.error(f"Error: {e}")
        await msg.edit_text("حدث خطأ أثناء تحميل الفيديو. قد يكون الرابط محمي أو غير مدعوم.")

# ربط الأوامر والرسائل
telegram_app.add_handler(CommandHandler("start", start))
telegram_app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download_video))

@app.route('/')
def home():
    return "Bot is running active via Webhook with nest_asyncio!"

# استقبال الـ Webhook بشكل آمن ودون أي أخطاء في الـ Event Loop
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    try:
        json_data = request.get_json(force=True)
        update = Update.de_json(json_data, telegram_app.bot)
        
        async def process():
            await telegram_app.process_update(update)
            
        current_loop = asyncio.get_event_loop()
        current_loop.run_until_complete(process())
    except Exception as e:
        logging.error(f"Webhook error: {e}")
    return 'OK', 200

def set_telegram_webhook():
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/{TOKEN}"
        api_url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_url}"
        try:
            urllib.request.urlopen(api_url)
            logging.info(f"Webhook successfully registered to: {webhook_url}")
        except Exception as e:
            logging.error(f"Failed to set webhook: {e}")

if __name__ == '__main__':
    set_telegram_webhook()
    app.run(host='0.0.0.0', port=PORT)
