import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from handlers import rt
from config import TOKEN, PORT

# Настройка логирования
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER + UPTIMEROBOT 24/7 ---
async def health_check(request):
    """Эндпоинт для UptimeRobot, чтобы Render не засыпал каждые 15 минут"""
    return web.Response(text="Bot is Alive 24/7!", status=200)

async def urlpay_webhook_handler(request):
    """Вебхук от URLPay для автоматического зачисления оплаты по СБП"""
    from services.urlpay import handle_urlpay_webhook
    return await handle_urlpay_webhook(request)

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    app.router.add_post("/api/webhook/urlpay", urlpay_webhook_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health & Webhook server running on port {PORT}")

async def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN (или TOKEN) не задан в переменных окружения!")

    # 1. Запускаем параллельный веб-сервер для UptimeRobot пингов
    await start_web_server()

    # 2. Инициализируем бота и диспетчер
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(rt)

    # 3. Сбрасываем старые апдейты и запускаем polling
    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Telegram Bot polling started successfully!")
    await dp.start_polling(bot, drop_pending_updates=True)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Бот остановлен пользователем.")
