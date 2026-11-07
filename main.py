import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from aiogram.exceptions import TelegramConflictError
from handlers import rt
from config import TOKEN, PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

async def handle(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/health", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health server running on port {PORT}")

async def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN не задан в переменных окружения Render!")

    await start_web_server()

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(rt)

    # Даем серверу полностью стабилизироваться
    await asyncio.sleep(3)
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("Webhooks cleared successfully.")
    except Exception as e:
        logger.warning(f"Could not clear webhook: {e}")

    logger.info("Bot polling starting with conflict auto-recovery...")
    
    while True:
        try:
            await dp.start_polling(bot, drop_pending_updates=True)
        except TelegramConflictError:
            logger.error("Конфликт сессий Telegram! Переподключение через 5 секунд...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Ошибка в поллинге: {e}. Перезапуск через 5 секунд...")
            await asyncio.sleep(5)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Завершение работы")
