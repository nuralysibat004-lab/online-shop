import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from handlers import rt
from config import TOKEN

# --- ВЕБ-ЗАГЛУШКА ДЛЯ RENDER (чтобы не было тайм-аута по портам) ---
async def handle(request):
    return web.Response(text="Bot is running!")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
# -----------------------------------------------------------------

async def main():
    # Сначала запускаем веб-сервер для Render
    await start_web_server()
    
    # Твой запуск бота
    bot = Bot(token=TOKEN)
    dp = Dispatcher()
    dp.include_router(rt)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types(), drop_pending_updates=True)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Завершение работы")
        
