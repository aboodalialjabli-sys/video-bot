import os
import re
import logging
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, CommandHandler, ContextTypes, filters
import yt_dlp

# إعداد السجل
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# توكن البوت الخاص بك
TOKEN = "8919952774:AAH_VmviFJ-vvQjDy_V4r6YGzAuNzmiiS2A"

# رسالة الترحيب عند الضغط على Start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_name = update.effective_user.first_name
    welcome_text = (
        f"أهلاً بك يا {user_name} في بوت تحميل الفيديوهات! 🤖\n\n"
        "يمكنك من خلالي تحميل الفيديوهات بسهولة وبدون علامة مائية من:\n"
        "• تيك توك (TikTok)\n"
        "• إنستغرام (Instagram)\n"
        "• فيسبوك (Facebook)\n\n"
        "أرسل رابط الفيديو الذي تريد تحميله 👇"
    )
    await update.message.reply_text(welcome_text)

# وظيفة تحميل وإرسال الفيديو
async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    
    if not url.startswith("http"):
        await update.message.reply_text("عذراً، يرجى إرسال رابط صحيح يبدأ بـ http أو https.")
        return

    msg = await update.message.reply_text("⏳ جاري تحميل الفيديو، يرجى الانتظار...")

    ydl_opts = {
        'format': 'best',
        'outtmpl': 'video.mp4',
        'max_filesize': 50 * 1024 * 1024,
    }

    try:
            url_match = re.search(r'https?://[^\s]+', update.message.text)
    if url_match:
        url = url_match.group(0)
    else:
        url = update.message.text

        if os.path.exists("video.mp4"):
            os.remove("video.mp4")

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])

        if os.path.exists("video.mp4"):
            await update.message.reply_video(video=open("video.mp4", 'rb'), caption="تم التحميل بواسطة البوت بنجاح ✅")
            await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg.message_id)
            os.remove("video.mp4")
        else:
            await msg.edit_text("عذراً، لم أتمكن من تحميل الفيديو. تأكد من أن الرابط عام وصحيح.")

    except Exception as e:
        logging.error(f"Error: {e}")
        await msg.edit_text("حدث خطأ أثناء تحميل الفيديو. قد يكون الرابط محمي أو غير مدعوم.")

def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), download_video))

    print("البوت يعمل الآن أونلاين...")
    app.run_polling()

if __name__ == '__main__':
    main()
