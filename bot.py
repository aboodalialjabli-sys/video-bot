import os
import logging
import asyncio
import urllib.request
from flask import Flask, request
from telegram import Bot
import yt_dlp

# إعداد السجل
logging.basicConfig(format='%(asctime)s - %(levelname)s - %(message)s', level=logging.INFO)

TOKEN = "9263521777:AAH4SMf96rRxghm8vNRLosueiNZoWtqg1-Y"
PORT = int(os.environ.get('PORT', 8080))
RENDER_EXTERNAL_URL = os.environ.get('RENDER_EXTERNAL_URL')

app = Flask(__name__)
bot = Bot(token=TOKEN)

@app.route('/')
def home():
    return "Bot is running perfectly!"

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    try:
        data = request.get_json(force=True)
        if 'message' in data:
            message = data['message']
            chat_id = message['chat']['id']
            text = message.get('text', '').strip()
            
            async def handle_message():
                if text.startswith('/start'):
                    await bot.send_message(
                        chat_id=chat_id,
                        text="أهلاً بك! أرسل رابط فيديو من إنستغرام أو فيسبوك لتحميله فوراً 👇"
                    )
                elif "instagram.com" in text or "facebook.com" in text or "fb.watch" in text or "fb.me" in text:
                    sent_msg = await bot.send_message(chat_id=chat_id, text="جاري تحميل الفيديو، لطفاً انتظر قليلاً...")
                    
                    ydl_opts = {
                        'format': 'best',
                        'outtmpl': 'video.mp4',
                        'max_filesize': 50 * 1024 * 1024,
                    }
                    try:
                        if os.path.exists("video.mp4"):
                            os.path.remove("video.mp4")

                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            ydl.download([text])

                        if os.path.exists("video.mp4"):
                            with open("video.mp4", "rb") as vid_file:
                                await bot.send_video(chat_id=chat_id, video=vid_file, caption="تم التحميل بواسطة البوت بنجاح ✅")
                            await bot.delete_message(chat_id=chat_id, message_id=sent_msg.message_id)
                            os.remove("video.mp4")
                        else:
                            await bot.edit_message_text(chat_id=chat_id, message_id=sent_msg.message_id, text="حدث خطأ أثناء التحميل. تأكد من أن الرابط عام وصحيح.")
                    except Exception as e:
                        logging.error(f"Download error: {e}")
                        try:
                            await bot.edit_message_text(chat_id=chat_id, message_id=sent_msg.message_id, text="حدث خطأ أثناء تحميل الفيديو. قد يكون الرابط محمي أو غير مدعوم.")
                        except:
                            pass
                else:
                    await bot.send_message(
                        chat_id=chat_id,
                        text="عذراً، أرسل رابط فيديو صالح من إنستغرام أو فيسبوك فقط!"
                    )

            asyncio.run(handle_message())
            
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        
    return 'OK', 200

def set_webhook():
    if RENDER_EXTERNAL_URL:
        webhook_url = f"{RENDER_EXTERNAL_URL}/{TOKEN}"
        try:
            url = f"https://api.telegram.org/bot{TOKEN}/setWebhook?url={webhook_url}"
            urllib.request.urlopen(url)
            logging.info(f"Webhook set to {webhook_url}")
        except Exception as e:
            logging.error(f"Failed to set webhook: {e}")

if __name__ == '__main__':
    set_webhook()
    app.run(host='0.0.0.0', port=PORT)
