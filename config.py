import os

BOT_TOKEN = os.getenv("TOKEN")
# Или если бот считывает через config, пропишем заглушки:
PASSWORD = "123"
ADMIN_PASSWORD = "123"
ALLOWED_ADMIN_IDS = os.getenv("ALLOWED_ADMIN_IDS", "")
