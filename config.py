import os
from dotenv import load_dotenv

load_dotenv()

# Токен бота (поддержка обеих переменных: BOT_TOKEN и TOKEN)
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
BOT_TOKEN = TOKEN

# Список ID администраторов (разделенных запятой, например "7461353872,12345678")
ALLOWED_ADMIN_IDS = os.getenv("ALLOWED_ADMIN_IDS", "7461353872")

# База данных: если задан DATABASE_URL (например Postgres на Neon), берем его, иначе SQLite
DATABASE = os.getenv("DATABASE_URL", "sqlite:///bot_db.db")

# Пароли для админ-панели (если используются)
PASSWORD = os.getenv("ADMIN_PASSWORD", "123")
ADMIN_PASSWORD = PASSWORD

# CryptoBot токен
CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")

# URLPay API ключи для СБП (рубли РФ)
URLPAY_API_KEY = os.getenv("URLPAY_API_KEY")
URLPAY_SECRET = os.getenv("URLPAY_SECRET")
URLPAY_SHOP_ID = os.getenv("URLPAY_SHOP_ID")

# Порт веб-сервера для Render (автоматически передается Render)
PORT = int(os.getenv("PORT", 8080))
