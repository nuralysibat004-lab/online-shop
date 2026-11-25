import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
BOT_TOKEN = TOKEN

ALLOWED_ADMIN_IDS = os.getenv("ALLOWED_ADMIN_IDS", "7461353872")
DATABASE = os.getenv("DATABASE_URL", "sqlite:///bot_db.db")

PASSWORD = os.getenv("ADMIN_PASSWORD", "123")
ADMIN_PASSWORD = PASSWORD

CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN", "").strip()
GRAMIX_API_KEY = os.getenv("GRAMIX_API_KEY", "").strip()
FRAGMENT_API_KEY = os.getenv("FRAGMENT_API_KEY", "").strip()
REVIEW_CHANNEL_ID = os.getenv("REVIEW_CHANNEL_ID", "@GumNyam1").strip()

# Lava.top (Карта РФ МИР от 50 ₽, ~8%)
LAVA_API_KEY = os.getenv("LAVA_API_KEY", "").strip()
LAVA_OFFER_ID = os.getenv("LAVA_OFFER_ID", "").strip()
LAVA_WEBHOOK_KEY = (
    os.getenv("LAVA_WEBHOOK_KEY")
    or os.getenv("LAVA_WEBHOOK_SECRET")
    or LAVA_API_KEY
).strip()

PORT = int(os.getenv("PORT", 8080))
