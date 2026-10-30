import os
import logging
import html
import re
import random
import string
import csv
import aiofiles
import hashlib

from aiogram import F, Router, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputFile, LabeledPrice, PreCheckoutQuery
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiocryptopay import AioCryptoPay, Networks

from config import PASSWORD, ADMIN_PASSWORD, ALLOWED_ADMIN_IDS, DATABASE
from db import BotDB
from Exceptions import WrongItemException
from States import user_states

logger = logging.getLogger(__name__)

TEST_MODE = False
TEST_BALANCE = 999
MIN_WITHDRAW = 50
REFERRAL_BONUS = 50
REFERRAL_MIN_STARS = 350

ADMIN_IDS = {int(x) for x in ALLOWED_ADMIN_IDS}
ADMIN_ID = 7461353872

cryptopay = AioCryptoPay(token=os.getenv("CRYPTO_BOT_TOKEN"), network=Networks.MAIN_NET)
rt = Router()
bot_db = BotDB(DATABASE)

_test_balances: dict[int, int] = {}

class WithdrawState(StatesGroup):
    waiting_for_amount = State()

class BuySteps(StatesGroup):
    choosing_category = State()
    choosing_recipient = State()
    entering_username = State()
    choosing_product = State()

PRICES = {
    "prod_stars_50": {"amount": 72, "usdt": 0.89, "title": "50 Telegram Stars", "type": "stars", "quantity": 50},
    "prod_stars_100": {"amount": 144, "usdt": 1.78, "title": "100 Telegram Stars", "type": "stars", "quantity": 100},
    "prod_stars_150": {"amount": 216, "usdt": 2.68, "title": "150 Telegram Stars", "type": "stars", "quantity": 150},
    "prod_stars_250": {"amount": 360, "usdt": 4.47, "title": "250 Telegram Stars", "type": "stars", "quantity": 250},
    "prod_stars_500": {"amount": 720, "usdt": 8.94, "title": "500 Telegram Stars", "type": "stars", "quantity": 500},
    "prod_stars_1000": {"amount": 1440, "usdt": 17.89, "title": "1000 Telegram Stars", "type": "stars", "quantity": 1000},
    "prod_stars_2500": {"amount": 3600, "usdt": 44.72, "title": "2500 Telegram Stars", "type": "stars", "quantity": 2500},
    "prod_prem_3": {"amount": 1050, "usdt": 13.03, "title": "Telegram Premium (3 месяца)", "type": "premium", "months": 3},
    "prod_prem_6": {"amount": 1400, "usdt": 17.38, "title": "Telegram Premium (6 месяцев)", "type": "premium", "months": 6},
    "prod_prem_12": {"amount": 2450, "usdt": 30.42, "title": "Telegram Premium (12 месяцев)", "type": "premium", "months": 12},
}

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_balance(user_id: int) -> int:
    user_data = bot_db.get_user(user_id)
    return user_data[0] if user_data and user_data[0] is not None else 0

def set_balance(user_id: int, new_balance: int) -> None:
    bot_db.update_balance(user_id, new_balance)

def add_to_balance(user_id: int, amount: int) -> None:
    bot_db.add_balance(user_id, amount)

def get_referrals_count(user_id: int) -> int:
    try:
        return bot_db.count_referrals(user_id)
    except Exception:
        logger.exception("count_referrals failed (user_id=%s)", user_id)
        return 0

async def safe_edit(callback: CallbackQuery, text: str, reply_markup=None) -> None:
    try:
        await callback.message.edit_text(text, reply_markup=reply_markup, parse_mode="HTML")
    except Exception as e:
        if "message is not modified" not in str(e):
            raise

def get_main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🪙 Купить Криптовалюту", callback_data="crypto")
            ],
            [
                InlineKeyboardButton(text="⭐ Telegram Stars & Premium", callback_data="stars")
            ],
            [
                InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders"),
                InlineKeyboardButton(text="👤 Профиль", callback_data="profile")
            ],
            [
                InlineKeyboardButton(text="💬 Отзывы", url="https://t.me/твоя_ссылка_на_отзывы"),
                InlineKeyboardButton(text="👥 Рефералы", callback_data="ref")
            ],
            [
                InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")
            ]
        ]
    )

def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]
        ]
    )

@rt.message(Command("start"))
async def start_handler(message: Message, state: FSMContext, command: CommandObject = None):
    await state.clear()
    user_id = message.from_user.id
    user_name = html.escape(message.from_user.first_name or "друг")

    referrer_id = None
    args = command.args if command else None
    if args and args.startswith("ref_"):
        try:
            parsed_id = int(args[4:])
            if parsed_id != user_id:
                referrer_id = parsed_id
        except ValueError:
            pass

    is_new = not bot_db.get_user(user_id)
    if is_new:
        if referrer_id:
            bot_db.add_user(referrer_id)
        bot_db.add_user(user_id, referrer_id)
        if user_id in ADMIN_IDS:
            bot_db.update_balance(user_id, 0)
        if referrer_id:
            try:
                await message.bot.send_message(
                    referrer_id,
                    f"👤 По вашей ссылке зарегистрировался новый пользователь: <b>{user_name}</b>!",
                    parse_mode="HTML"
                )
            except Exception:
                logger.exception("Не удалось уведомить реферера %s", referrer_id)

    balance = get_balance(user_id)
    bot_username = (await message.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    text = (
        f"👋 Салам алейкум, <b>{user_name}</b>! Ты попал в <b>GumStars</b> — лучший бот по покупке криптовалюты и цифровых товаров ⭐\n\n"
        f"💎 Быстро, безопасно и по выгодному курсу.\n\n"
        f"💰 Твой баланс звезд: <b>{balance}</b> ⭐\n"
        f"🔗 Реферальная система:\n"
        f"• Приглашай друзей по своей ссылке: <code>{ref_link}</code>\n"
        f"• Когда твой друг купит товар на сумму от 500 ₽, тебе на баланс автоматически зачислится <b>{REFERRAL_BONUS}</b> ⭐!\n\n"
        f"Выберите нужный раздел в меню ниже 👇"
    )
    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode="HTML")

@rt.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_name = html.escape(callback.from_user.first_name or "друг")
    text = (
        f"👋 Салам алейкум, <b>{user_name}</b>! Ты попал в <b>GumStars</b> — лучший бот по покупке криптовалюты и цифровых товаров ⭐\n\n"
        f"💎 Быстро, безопасно и по выгодному курсу.\n\n"
        f"Выберите нужный раздел в меню ниже 👇"
    )
    await safe_edit(callback, text, get_main_keyboard())
    await callback.answer()

@rt.callback_query(F.data == "crypto")
async def crypto_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🪙 TON — 125.10 ₽", callback_data="buy_ton"),
                InlineKeyboardButton(text="₿ BTC — 8 155 097.50 ₽", callback_data="buy_btc")
            ],
            [
                InlineKeyboardButton(text="💵 USDT — 100.57 ₽", callback_data="buy_usdt"),
                InlineKeyboardButton(text="🟣 SOL — 10 268.02 ₽", callback_data="buy_sol")
            ],
            [
                InlineKeyboardButton(text="🔍 Указать свою монету", callback_data="custom_crypto")
            ],
            [
                InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")
            ]
        ]
    )
    text = "🪙 <b>Криптовалюта</b>\n\nОплата в рублях (₽). Выберите монету для покупки:"
    await safe_edit(callback, text, keyboard)
    await callback.answer()

# --- МАГАЗИН STARS & PREMIUM ---
@rt.callback_query(F.data == "stars")
async def stars_menu_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Купить Telegram Stars", callback_data="cat_stars")],
        [InlineKeyboardButton(text="💎 Купить Telegram Premium", callback_data="cat_premium")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
    ])
    await safe_edit(callback, "✨ <b>Магазин Telegram Stars & Premium</b>\n\nВыберите категорию товара:", kb)
    await callback.answer()

@rt.callback_query(F.data.in_({"cat_stars", "cat_premium"}))
async def process_category(callback: CallbackQuery, state: FSMContext):
    category = "stars" if callback.data == "cat_stars" else "premium"
    await state.update_data(category=category)
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👤 Себе", callback_data="recipient_self")],
        [InlineKeyboardButton(text="👥 Другу (по @username)", callback_data="recipient_friend")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="stars")]
    ])
    await safe_edit(callback, "🎯 <b>Кому отправляем заказ?</b>", kb)
    await state.set_state(BuySteps.choosing_recipient)
    await callback.answer()

@rt.callback_query(BuySteps.choosing_recipient, F.data == "recipient_self")
async def recipient_self(callback: CallbackQuery, state: FSMContext):
    user_target = callback.from_user.username or str(callback.from_user.id)
    if not user_target.startswith("@") and not user_target.isdigit():
        user_target = f"@{user_target}"
    await state.update_data(target_user=user_target)
    await show_products(callback.message, state)
    await callback.answer()

@rt.callback_query(BuySteps.choosing_recipient, F.data == "recipient_friend")
async def recipient_friend(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="cat_stars")]])
    await callback.message.edit_text("✏️ Отправьте в чат <b>@username</b> получателя (например, <code>@durov</code>):", reply_markup=kb, parse_mode="HTML")
    await state.set_state(BuySteps.entering_username)
    await callback.answer()

@rt.message(BuySteps.entering_username)
async def process_username_input(message: Message, state: FSMContext):
    username = message.text.strip()
    if not username.startswith("@"):
        username = f"@{username}"
        
    if len(username) < 4:
        await message.answer("⚠️ Неверный формат юзернейма. Попробуйте ещё раз:")
        return
        
    await state.update_data(target_user=username)
    await message.answer(f"✅ Получатель сохранен: <b>{username}</b>", parse_mode="HTML")
    await show_products(message, state)

async def show_products(message: Message, state: FSMContext):
    data = await state.get_data()
    category = data.get("category")
    
    if category == "stars":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 50 звезд — 72 ₽", callback_data="prod_stars_50")],
            [InlineKeyboardButton(text="⭐ 100 звезд — 144 ₽", callback_data="prod_stars_100")],
            [InlineKeyboardButton(text="⭐ 150 звезд — 216 ₽", callback_data="prod_stars_150")],
            [InlineKeyboardButton(text="⭐ 250 звезд — 360 ₽", callback_data="prod_stars_250")],
            [InlineKeyboardButton(text="⭐ 500 звезд — 720 ₽", callback_data="prod_stars_500")],
            [InlineKeyboardButton(text="⭐ 1000 звезд — 1440 ₽", callback_data="prod_stars_1000")],
            [InlineKeyboardButton(text="⭐ 2500 звезд — 3600 ₽", callback_data="prod_stars_2500")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="stars")]
        ])
        text = "📦 <b>Выберите необходимый пакет звёзд:</b>"
    else:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 3 месяца — 1 050 ₽", callback_data="prod_prem_3")],
            [InlineKeyboardButton(text="💎 6 месяцев — 1 400 ₽", callback_data="prod_prem_6")],
            [InlineKeyboardButton(text="💎 12 месяцев — 2 450 ₽", callback_data="prod_prem_12")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="stars")]
        ])
        text = "📦 <b>Выберите срок подписки TG Premium:</b>"

    await state.set_state(BuySteps.choosing_product)
    if isinstance(message, CallbackQuery):
        await safe_edit(message, text, kb)
    else:
        await message.answer(text, reply_markup=kb, parse_mode="HTML")

@rt.callback_query(BuySteps.choosing_product, F.data.startswith("prod_"))
async def create_crypto_invoice(callback: CallbackQuery, state: FSMContext):
    product_key = callback.data
    product_info = PRICES.get(product_key)
    
    if not product_info:
        await callback.answer("❌ Ошибка товара!", show_alert=True)
        return

    data = await state.get_data()
    target_user = data.get("target_user", f"@{callback.from_user.username}")
    
    rub_price = product_info["amount"]
    usdt_amount = product_info["usdt"]

    try:
        invoice = await cryptopay.create_invoice(
            asset='USDT',
            amount=usdt_amount,
            description=f"Покупка {product_info['title']} для {target_user} (Эквивалент: {rub_price} ₽)",
            payload=f"{product_key}:{target_user}"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить счет", url=invoice.bot_invoice_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"check_{invoice.invoice_id}")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
        ])
        
        await safe_edit(
            callback,
            f"🛒 <b>Заказ успешно сформирован!</b>\n\n"
            f"📦 Товар: <b>{product_info['title']}</b>\n"
            f"👤 Получатель: <code>{target_user}</code>\n"
            f"💰 Цена: <b>{rub_price} ₽</b> (оплата: <b>{usdt_amount} USDT</b>)\n\n"
            f"Нажмите кнопку ниже для безопасной оплаты через CryptoBot:",
            kb
        )
    except Exception as e:
        logger.error(f"Ошибка создания счета CryptoBot: {e}")
        await callback.message.answer("⚠️ Произошла ошибка при создании счета на оплату. Попробуйте позже.")

    await state.clear()
    await callback.answer()
# --- КОНЕЦ МАГАЗИНА ---

@rt.callback_query(F.data == "profile")
async def profile_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_name = html.escape(callback.from_user.first_name or "друг")
    text = (
        f"👤 <b>ЛИЧНЫЙ КАБИНЕТ</b>\n\n"
        f"• Имя: <b>{user_name}</b>\n"
        f"• ID: <code>{user_id}</code>\n"
        f"• Баланс звезд: <b>{get_balance(user_id)}</b> ⭐\n"
        f"• Активных заказов: <b>0</b>\n"
        f"• Сумма покупок: <b>0.00 ₽</b>\n"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Реферальная система", callback_data="ref")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
        ]
    )
    await safe_edit(callback, text, keyboard)
    await callback.answer()

@rt.callback_query(F.data == "my_orders")
async def orders_menu(callback: CallbackQuery):
    text = "📦 <b>Мои заказы</b>\n\nУ вас пока нет активных или завершённых заказов."
    await safe_edit(callback, text, back_keyboard())
    await callback.answer()

@rt.callback_query(F.data == "ref")
async def ref_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    balance = get_balance(user_id)
    referrals = get_referrals_count(user_id)
    
    bot_username = (await callback.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    text = (
        f"👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
        f"Приглашайте друзей и получайте <b>{REFERRAL_BONUS}</b> ⭐ за каждого, кто купит товар на сумму от 500 ₽.\n\n"
        f"🔗 Ваша реферальная ссылка:\n<code>{ref_link}</code>\n\n"
        f"👥 Приглашено друзей: <b>{referrals}</b>\n"
        f"⭐ Доступно на балансе: <b>{balance}</b> ⭐\n"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Вывести звёзды", callback_data="withdraw_stars")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
        ]
    )
    await safe_edit(callback, text, keyboard)
    await callback.answer()

@rt.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery, state: FSMContext):
    await safe_edit(
        callback,
        "🆘 <b>Служба поддержки</b>\n\nНапишите вашу проблему или вопрос — мы постараемся ответить максимально быстро.",
        back_keyboard()
    )
    await state.set_state(user_states.waiting_for_support)
    await callback.answer()

@rt.message(user_states.waiting_for_support)
async def process_support_message(message: Message, state: FSMContext, bot):
    user_id = message.from_user.id
    user_name = html.escape(message.from_user.first_name or "")
    username = f"@{message.from_user.username}" if message.from_user.username else "нет никнейма"
    body = html.escape(message.text or message.caption or "[вложение]")

    admin_text = (
        f"📩 <b>Новое обращение в поддержку!</b>\n"
        f"👤 От: {user_name} ({username})\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"💬 Сообщение:\n{body}"
    )
    try:
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
        if not message.text:
            await message.copy_to(ADMIN_ID)
    except Exception:
        logger.exception("Не удалось отправить обращение в поддержку админу")

    await message.answer("✅ Ваше сообщение успешно отправлено в поддержку! Ожидайте ответа.")
    await state.clear()

@rt.callback_query(F.data == "withdraw_stars")
async def withdraw_stars_callback(callback: CallbackQuery, state: FSMContext):
    balance = get_balance(callback.from_user.id)
    await state.set_state(WithdrawState.waiting_for_amount)

    text = (
        f"📤 <b>ВЫВОД ЗВЁЗД</b>\n\n"
        f"💰 На вашем балансе: <b>{balance}</b> ⭐\n"
        f"📌 Минимум для вывода: <b>{MIN_WITHDRAW}</b> ⭐\n\n"
        f"✍️ Напишите в чат число — сколько звезд вы хотите вывести:"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]]
    )
    await safe_edit(callback, text, keyboard)
    await callback.answer()

@rt.message(WithdrawState.waiting_for_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
    user = message.from_user
    user_id = user.id
    raw = message.text.strip()

    if not re.fullmatch(r"[0-9]+", raw):
        await message.answer("❌ Введите целое число цифрами, например: 100")
        return

    amount = int(raw)
    balance = get_balance(user_id)

    if amount < MIN_WITHDRAW:
        await message.answer(f"❌ Минимальная сумма для вывода: {MIN_WITHDRAW} ⭐. Введите сумму побольше:")
        return
    if amount > balance:
        await message.answer(f"❌ Недостаточно звезд. Доступно: {balance} ⭐. Введите меньшую сумму:")
        return

    new_balance = balance - amount
    set_balance(user_id, new_balance)
    await state.clear()

    await message.answer(
        f"✅ <b>Запрос на вывод {amount} ⭐ успешно создан!</b>\n\n"
        f"⏳ Ожидайте зачисления звезд. Оставшийся баланс: <b>{new_balance}</b> ⭐",
        parse_mode="HTML"
    )

    user_label = f"@{user.username}" if user.username else html.escape(user.first_name or "без имени")
    try:
        await message.bot.send_message(
            ADMIN_ID,
            f"🔔 <b>Новая заявка на вывод звезд!</b>\n"
            f"👤 Пользователь: {user_label} (ID: <code>{user_id}</code>)\n"
            f"⭐ Сумма к выводу: <b>{amount}</b> ⭐",
            parse_mode="HTML"
        )
    except Exception:
        logger.exception("Не удалось отправить уведомление админу (ID-%s)", ADMIN_ID)
