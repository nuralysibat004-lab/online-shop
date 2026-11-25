import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from handlers import rt, handle_lava_webhook
from config import TOKEN, PORT

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def handle(_request):
    return web.Response(text="Bot is running!")


async def start_web_server(bot: Bot):
    app = web.Application()
    app.router.add_get("/", handle)
    app.router.add_get("/health", handle)

    async def lava_webhook(request: web.Request):
        try:
            body = await request.json()
        except Exception:
            body = {}
        status_code, resp_json = await handle_lava_webhook(bot, body, dict(request.headers))
        return web.json_response(resp_json, status=status_code)

    app.router.add_post("/lava/webhook", lava_webhook)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()
    logger.info(f"Health & Lava.top webhook server running on port {PORT}")


async def main():
    if not TOKEN:
        raise ValueError("BOT_TOKEN (или TOKEN) не задан в переменных окружения Render!")

    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    await start_web_server(bot)

    dp = Dispatcher()
    dp.include_router(rt)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("Bot polling started successfully!")
    await dp.start_polling(bot, drop_pending_updates=True)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Завершение работы")
