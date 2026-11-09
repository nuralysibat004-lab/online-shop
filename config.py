import os
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TOKEN")
BOT_TOKEN = TOKEN

ALLOWED_ADMIN_IDS = os.getenv("ALLOWED_ADMIN_IDS", "7461353872")
DATABASE = os.getenv("DATABASE_URL", "sqlite:///bot_db.db")

PASSWORD = os.getenv("ADMIN_PASSWORD", "123")
ADMIN_PASSWORD = PASSWORD

CRYPTO_BOT_TOKEN = os.getenv("CRYPTO_BOT_TOKEN")
FRAGMENT_API_KEY = os.getenv("FRAGMENT_API_KEY", "")
REVIEW_CHANNEL_ID = os.getenv("REVIEW_CHANNEL_ID", "@GumNyam1")

# PaySync / CrystalPAY (СБП & Карты РФ)
PAYSYNC_LOGIN = os.getenv("PAYSYNC_LOGIN") or os.getenv("CRYSTAL_LOGIN") or os.getenv("CRYSTALPAY_LOGIN", "gumstarsshop")
PAYSYNC_SECRET = os.getenv("PAYSYNC_SECRET") or os.getenv("PAYSYNC_SECRET_KEY") or os.getenv("CRYSTAL_SECRET") or os.getenv("CRYSTALPAY_SECRET", "")

CRYSTAL_LOGIN = PAYSYNC_LOGIN
CRYSTAL_SECRET = PAYSYNC_SECRET

PORT = int(os.getenv("PORT", 8080))
