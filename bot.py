import os
import logging
import re
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, MessageHandler, CommandHandler, filters
import yt_dlp

# إعداد السجل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# توكن البوت الخاص بك
TOKEN = "8919952774:AAH_VmviFJ-vvQjDy_V4r6YGzAuNzmiiS2A"

# رسالة الترحيب عند الضغط على Start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_text = (
        f"أهلاً بك يا {user_name} !\n"
        "مرحباً بك في بوت تحميل الفيديوهات بسهولة وبدون علامة مائية من:\n"
        "• تيك توك (TikTok)\n"
        "• إنستغرام (Instagram)\n"
        "• فيسبوك (Facebook)\n\n"
        "أرسل رابط الفيديو الذي تريد تحميله 👇"
    )
    await update.message.reply_text(welcome_text)

# وظيفة تحميل الفيديو واستخراج الرابط النظيف تلقائياً
async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message_text = update.message.text
    
    # استخراج الرابط النظيف تلقائياً متجاهلاً أي كلام أو إعلانات زائدة
    url_match = re.search(r'https?://[^\s]+', message_text)
    if url_match:
        url = url_match.group(0)
    else:
        url = message_text

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
            await msg.edit_text("حدث خطأ أثناء التحميل. التأكد من أن الرابط عام وصحيح.")

    except Exception as e:
        logging.error(f"Error: {e}")
        await msg.edit_text("حدث خطأ أثناء تحميل الفيديو. قد يكون الرابط محمي أو غير مدعوم.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download_video))

    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()
