# GumStars — Telegram Bot (Stars, Premium, Crypto)

Очищенная и обновлённая версия бота **GumStars** на `aiogram 3` + `PostgreSQL` (Neon/Render) + `aiohttp` для вебхука и UptimeRobot.

## Платёжные системы
- **Lava.top** — оплата картой РФ (МИР) от 50 ₽ (`/lava/webhook`)
- **CryptoBot** — моментальная оплата в USDT и авто-выдача чеков
- **Telegram Stars (XTR)** — обмен звёзд на USDT
- **Gramix API** — автовыдача Telegram Stars после оплаты

## Админ-команды
- `/banners` — статус баннеров всех разделов
- `/banner <раздел>` — установить новый баннер (прикрепите фото или ответьте на фото)
- `/broadcast <текст>` — рассылка всем пользователям
- `/refund <ID>` — возврат Telegram Stars
- `/setbalance <ID> <число>` — изменить реферальный баланс звёзд
- `/complete <order_id>` — перевести заказ в «Выполненные»
- `/test_add_order`, `/test_progress`, `/test_cancel`, `/debug_db` — тесты истории заказов и диагностика БД
