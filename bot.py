import os
import logging
import threading
from flask import Flask
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import yt_dlp

# إعداد السجل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# توكن البوت الجديد الخاص بك
TOKEN = "9263521777:AAH4SMf96rRxghm8vNRLosueiNZoWtqg1-Y"

# إنشاء سيرفر ويب وهمي لمنع رندر من إيقاف البوت وضمان عمله 24/7
app_web = Flask('')

@app_web.route('/')
def home():
    return "Bot is active and running 24/7!"

def run_web():
    app_web.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    t = threading.Thread(target=run_web)
    t.start()

# رسالة الترحيب عند الضغط على Start
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

# وظيفة تحميل الفيديو لروابط انستا وفيس
async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()

    # التحقق من أن الرابط يتبع لانستا أو فيسبوك
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

def main():
    # تشغيل سيرفر الحفاظ على البوت نشطاً على مدار الساعة
    keep_alive()

    # إعداد بوت تيليجرام
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download_video))

    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
