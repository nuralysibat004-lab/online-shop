import os
import logging
import html
import re
import random
import string
import csv
import aiofiles
import hashlib
import uuid
import aiohttp
from datetime import datetime

from aiogram import Bot, F, Router, types
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, 
    ReplyKeyboardMarkup, KeyboardButton, InputFile, LabeledPrice, PreCheckoutQuery
)
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
FRAGMENT_API_URL = "https://v1.fragmentapi.com/api/v1/partner"
FRAGMENT_API_KEY = os.getenv("FRAGMENT_API_KEY", "")
REVIEW_CHANNEL_ID = os.getenv("REVIEW_CHANNEL_ID", "@your_reviews_channel")

admin_bot = Bot(token=os.getenv("ADMIN_BOT_TOKEN", "")) if os.getenv("ADMIN_BOT_TOKEN") else None

rt = Router()
bot_db = BotDB(DATABASE)

class WithdrawState(StatesGroup):
    waiting_for_amount = State()

class BuySteps(StatesGroup):
    choosing_category = State()
    choosing_recipient = State()
    entering_username = State()
    choosing_product = State()

class BuyCryptoSteps(StatesGroup):
    choosing_network = State()
    entering_address = State()
    entering_custom_amount = State()

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
    
    # GRAM (TON)
    "crypto_ton_1": {"amount": 110, "usdt": 1.36, "title": "1 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 1},
    "crypto_ton_3": {"amount": 330, "usdt": 4.09, "title": "3 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 3},
    "crypto_ton_5": {"amount": 550, "usdt": 6.82, "title": "5 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 5},
    "crypto_ton_7": {"amount": 770, "usdt": 9.55, "title": "7 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 7},
    "crypto_ton_10": {"amount": 1100, "usdt": 13.64, "title": "10 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 10},

    # USDT (покупка за звезды)
    "crypto_usdt_1": {"amount": 81, "stars": 56, "title": "1 USDT (56 Stars)", "type": "crypto_stars", "coin": "USDT", "qty": 1},
    "crypto_usdt_3": {"amount": 243, "stars": 169, "title": "3 USDT (169 Stars)", "type": "crypto_stars", "coin": "USDT", "qty": 3},
    "crypto_usdt_5": {"amount": 404, "stars": 281, "title": "5 USDT (281 Stars)", "type": "crypto_stars", "coin": "USDT", "qty": 5},
    "crypto_usdt_7": {"amount": 566, "stars": 393, "title": "7 USDT (393 Stars)", "type": "crypto_stars", "coin": "USDT", "qty": 7},
    "crypto_usdt_10": {"amount": 809, "stars": 562, "title": "10 USDT (562 Stars)", "type": "crypto_stars", "coin": "USDT", "qty": 10},

    # USDC
    "crypto_usdc_1": {"amount": 81, "stars": 56, "title": "1 USDC (56 Stars)", "type": "crypto_stars", "coin": "USDC", "qty": 1},
    "crypto_usdc_3": {"amount": 243, "stars": 169, "title": "3 USDC (169 Stars)", "type": "crypto_stars", "coin": "USDC", "qty": 3},
    "crypto_usdc_5": {"amount": 404, "stars": 281, "title": "5 USDC (281 Stars)", "type": "crypto_stars", "coin": "USDC", "qty": 5},
    "crypto_usdc_7": {"amount": 566, "stars": 393, "title": "7 USDC (393 Stars)", "type": "crypto_stars", "coin": "USDC", "qty": 7},
    "crypto_usdc_10": {"amount": 809, "stars": 562, "title": "10 USDC (562 Stars)", "type": "crypto_stars", "coin": "USDC", "qty": 10},
}

def get_balance(user_id: int) -> int:
    user_data = bot_db.get_user(user_id)
    return user_data[0] if user_data and user_data[0] is not None else 0

def set_balance(user_id: int, new_balance: int) -> None:
    bot_db.update_balance(user_id, new_balance)

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

def get_main_reply_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🪙 Криптовалюта"), KeyboardButton(text="⭐ Купить звёзды")],
            [KeyboardButton(text="📦 История заказов"), KeyboardButton(text="👤 Профиль")],
            [KeyboardButton(text="💬 Отзывы"), KeyboardButton(text="👥 Рефералы")],
            [KeyboardButton(text="🆘 Поддержка")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите пункт меню 👇"
    )

def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]
        ]
    )

async def publish_to_reviews_channel(order_id, product_title, buyer, target_user, amount_rub):
    if not admin_bot:
        return
    now = datetime.now().strftime("%d.%m.%Y %H:%M")
    buyer_label = f"@{buyer.username}" if buyer.username else html.escape(buyer.first_name or "без имени")
    text = (
        f"📦 <b>ЗАКАЗ №{order_id}</b>\n\n"
        f"❌ Статус: ✅ <b>Выполнен</b>\n"
        f"👤 Покупатель: {buyer_label} (id: <code>{buyer.id}</code>)\n"
        f"🛒 Товар: <b>{product_title}</b>\n"
        f"💰 Сумма: <b>{amount_rub} ₽</b>\n"
        f"🛍 Получатель: <code>{target_user}</code>\n"
        f"🕒 Дата: {now}"
    )
    try:
        await admin_bot.send_message(REVIEW_CHANNEL_ID, text, parse_mode="HTML")
    except Exception as e:
        logger.error(f"Не удалось отправить отчет в канал отзывов через admin_bot: {e}")

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
        f"💞 Добро пожаловать, <b>{user_name}</b>! Ты попал в <b>GumStars</b> — лучший бот по покупке криптовалюты и цифровых товаров ⭐\n\n"
        f"💎 Быстро, безопасно и по выгодному курсу.\n\n"
        f"💰 Твой баланс звезд: <b>{balance}</b> ⭐\n"
        f"🔗 Реферальная система:\n"
        f"• Приглашай друзей по своей ссылке: <code>{ref_link}</code>\n"
        f"• Когда твой друг купит товар на сумму от 500 ₽, тебе на баланс автоматически зачислится <b>{REFERRAL_BONUS}</b> ⭐!\n\n"
        f"Выберите нужный раздел в меню ниже 👇"
    )
    await message.answer(text, reply_markup=get_main_reply_keyboard(), parse_mode="HTML")

@rt.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_name = html.escape(callback.from_user.first_name or "друг")
    text = (
        f"💞 Добро пожаловать, <b>{user_name}</b>! Ты попал в <b>GumStars</b> — лучший бот по покупке криптовалюты и цифровых товаров ⭐\n\n"
        f"💎 Быстро, безопасно и по выгодному курсу.\n\n"
        f"Выберите нужный раздел в меню ниже 👇"
    )
    try:
        await callback.message.delete()
    except Exception:
        pass
    await callback.message.answer(text, reply_markup=get_main_reply_keyboard(), parse_mode="HTML")
    await callback.answer()

@rt.message(F.text == "💬 Отзывы")
async def text_reviews(message: Message, state: FSMContext):
    await state.clear()
    channel_url = f"https://t.me/{REVIEW_CHANNEL_ID.lstrip('@')}" if not REVIEW_CHANNEL_ID.startswith("http") else REVIEW_CHANNEL_ID
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Перейти в канал с отзывами", url=channel_url)],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
    ])
    await message.answer("💬 <b>Отзывы и выполненные заказы</b>\n\nЗдесь вы можете ознакомиться с реальными отзывами наших клиентов и списком выполненных заказов 👇", reply_markup=kb, parse_mode="HTML")

@rt.message(F.text == "🪙 Криптовалюта")
async def text_crypto_main(message: Message, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💵 USDT", callback_data="crypto_coin_USDT")],
            [InlineKeyboardButton(text="💶 USDC", callback_data="crypto_coin_USDC")],
            [InlineKeyboardButton(text="💎 GRAM (TON)", callback_data="crypto_coin_TON")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
        ]
    )
    await message.answer("🪙 <b>Покупка криптовалюты</b>\n\nВыберите нужную монету:", reply_markup=keyboard, parse_mode="HTML")

@rt.message(F.text == "⭐ Купить звёзды")
async def text_stars(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐ Купить Telegram Stars", callback_data="cat_stars")],
        [InlineKeyboardButton(text="💎 Купить Telegram Premium", callback_data="cat_premium")],
        [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
    ])
    await message.answer("✨ <b>Магазин Telegram Stars & Premium</b>\n\nВыберите категорию товара:", reply_markup=kb, parse_mode="HTML")

@rt.message(F.text == "📦 История заказов")
async def text_orders(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("📦 <b>История заказов</b>\n\nУ вас пока нет активных или завершённых заказов.", parse_mode="HTML")

@rt.message(F.text == "👤 Профиль")
async def text_profile(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    user_name = html.escape(message.from_user.first_name or "друг")
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
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@rt.message(F.text == "👥 Рефералы")
async def text_ref(message: Message, state: FSMContext):
    await state.clear()
    user_id = message.from_user.id
    balance = get_balance(user_id)
    referrals = get_referrals_count(user_id)
    
    bot_username = (await message.bot.get_me()).username
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
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

@rt.message(F.text == "🆘 Поддержка")
async def text_support(message: Message, state: FSMContext):
    await state.set_state(user_states.waiting_for_support)
    await message.answer("🆘 <b>Служба поддержки</b>\n\nНапишите вашу проблему или вопрос — мы постараемся ответить максимально быстро.", parse_mode="HTML")
# --- ПОКУПКА КРИПТОВАЛЮТЫ И ОБМЕН ---
@rt.callback_query(F.data.startswith("crypto_coin_"))
async def select_crypto_coin(callback: CallbackQuery, state: FSMContext):
    coin = callback.data.split("_")[2]
    await state.update_data(crypto_coin=coin)
    
    if coin == "USDT":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="TON Network", callback_data="net_TON")],
            [InlineKeyboardButton(text="TRC20 Network", callback_data="net_TRC20")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]
        ])
    elif coin == "USDC":
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="TON Network", callback_data="net_TON")],
            [InlineKeyboardButton(text="Ethereum (ERC20)", callback_data="net_ERC20")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]
        ])
    else: # TON
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="TON Network", callback_data="net_TON")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]
        ])
        
    await safe_edit(callback, f"🌐 <b>Выберите сеть для {coin}:</b>", kb)
    await callback.answer()

@rt.callback_query(F.data == "crypto_back")
async def crypto_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💵 USDT", callback_data="crypto_coin_USDT")],
            [InlineKeyboardButton(text="💶 USDC", callback_data="crypto_coin_USDC")],
            [InlineKeyboardButton(text="💎 GRAM (TON)", callback_data="crypto_coin_TON")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
        ]
    )
    await safe_edit(callback, "🪙 <b>Покупка криптовалюты</b>\n\nВыберите нужную монету:", keyboard)
    await callback.answer()

@rt.callback_query(F.data.startswith("net_"))
async def select_crypto_network(callback: CallbackQuery, state: FSMContext):
    network = callback.data.split("_")[1]
    await state.update_data(crypto_net=network)
    
    data = await state.get_data()
    coin = data.get("crypto_coin", "USDT")
    
    if coin == "TON":
        # В GRAM кнопка обмена полностью убрана
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 GRAM — 110 ₽ (1.36 USDT)", callback_data="prod_crypto_ton_1")],
            [InlineKeyboardButton(text="3 GRAM — 330 ₽ (4.09 USDT)", callback_data="prod_crypto_ton_3")],
            [InlineKeyboardButton(text="5 GRAM — 550 ₽ (6.82 USDT)", callback_data="prod_crypto_ton_5")],
            [InlineKeyboardButton(text="7 GRAM — 770 ₽ (9.55 USDT)", callback_data="prod_crypto_ton_7")],
            [InlineKeyboardButton(text="10 GRAM — 1100 ₽ (13.64 USDT)", callback_data="prod_crypto_ton_10")],
            [InlineKeyboardButton(text="✍️ Указать своё количество", callback_data="custom_crypto_amount")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]
        ])
    elif coin == "USDC":
        # В USDC добавлена кнопка обмена GRAM на USDT/USDC
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 USDC — 56 ⭐", callback_data="prod_crypto_usdc_1")],
            [InlineKeyboardButton(text="3 USDC — 169 ⭐", callback_data="prod_crypto_usdc_3")],
            [InlineKeyboardButton(text="5 USDC — 281 ⭐", callback_data="prod_crypto_usdc_5")],
            [InlineKeyboardButton(text="7 USDC — 393 ⭐", callback_data="prod_crypto_usdc_7")],
            [InlineKeyboardButton(text="10 USDC — 562 ⭐", callback_data="prod_crypto_usdc_10")],
            [InlineKeyboardButton(text="✍️ Указать своё количество", callback_data="custom_crypto_amount")],
            [InlineKeyboardButton(text="💱 Обменять GRAM на USDT/USDC", callback_data="exchange_gram_to_stable")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]
        ])
    else:
        # В USDT добавлена кнопка обмена GRAM на USDT/USDC
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="1 USDT — 56 ⭐", callback_data="prod_crypto_usdt_1")],
            [InlineKeyboardButton(text="3 USDT — 169 ⭐", callback_data="prod_crypto_usdt_3")],
            [InlineKeyboardButton(text="5 USDT — 281 ⭐", callback_data="prod_crypto_usdt_5")],
            [InlineKeyboardButton(text="7 USDT — 393 ⭐", callback_data="prod_crypto_usdt_7")],
            [InlineKeyboardButton(text="10 USDT — 562 ⭐", callback_data="prod_crypto_usdt_10")],
            [InlineKeyboardButton(text="✍️ Указать своё количество", callback_data="custom_crypto_amount")],
            [InlineKeyboardButton(text="💱 Обменять GRAM на USDT/USDC", callback_data="exchange_gram_to_stable")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]
        ])
        
    await safe_edit(callback, f"📦 <b>Выберите количество {coin} (Сеть: {network}):</b>", kb)
    await callback.answer()

@rt.callback_query(F.data == "custom_crypto_amount")
async def custom_crypto_amount(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]])
    await safe_edit(callback, "✍️ Введите в чат нужное вам количество монеты цифрой (например: <code>15</code> или <code>2.5</code>):", kb)
    await state.set_state(BuyCryptoSteps.entering_custom_amount)
    await callback.answer()

@rt.callback_query(F.data == "exchange_gram_to_stable")
async def exchange_gram_mode(callback: CallbackQuery, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]])
    await safe_edit(callback, "💱 <b>Обмен GRAM на USDT/USDC (Полуавтоматический режим)</b>\n\nНапишите в чат детальный запрос (например: <i>Хочу обменять 10 GRAM на USDT</i>):", kb)
    await state.set_state(BuyCryptoSteps.entering_custom_amount)
    await callback.answer()

@rt.message(BuyCryptoSteps.entering_custom_amount)
async def process_custom_crypto(message: Message, state: FSMContext):
    text_val = message.text.strip()
    data = await state.get_data()
    coin = data.get("crypto_coin", "TON")
    network = data.get("crypto_net", "TON")

    await state.clear()
    
    await message.answer(
        f"✅ <b>Заявка принята в обработку (Полуавтоматический режим)!</b>\n\n"
        f"📌 Запрос: <code>{text_val}</code>\n"
        f"🌐 Сеть: <b>{network}</b>\n\n"
        f"Администратор уже получил уведомление и свяжется с вами для проведения сделки!",
        reply_markup=get_main_reply_keyboard(), parse_mode="HTML"
    )
    
    buyer = message.from_user
    buyer_label = f"@{buyer.username}" if buyer.username else html.escape(buyer.first_name or "без имени")
    admin_text = (
        f"🟡 <b>ЗАЯВКА НА ОБМЕН / СВОЕ КОЛИЧЕСТВО!</b>\n\n"
        f"👤 Покупатель: {buyer_label} (ID: <code>{buyer.id}</code>)\n"
        f"🪙 Монета/Сеть: <b>{coin} ({network})</b>\n"
        f"💬 Детали от клиента:\n<code>{text_val}</code>"
    )
    try:
        await message.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    except Exception:
        logger.exception("Не удалось отправить уведомление админу")

@rt.callback_query(F.data.startswith("prod_crypto_"))
async def ask_crypto_recipient(callback: CallbackQuery, state: FSMContext):
    prod_key = callback.data.replace("prod_", "")
    product_info = PRICES.get(prod_key, {})
    
    if product_info.get("type") == "crypto_stars":
        required_stars = product_info.get("stars", 0)
        user_balance = get_balance(callback.from_user.id)
        if user_balance < required_stars:
            await callback.answer(f"❌ Недостаточно звёзд! Нужно: {required_stars} ⭐, у вас: {user_balance} ⭐", show_alert=True)
            return

    await state.update_data(crypto_product=prod_key)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]])
    await safe_edit(callback, "✏️ Отправьте в чат ваш <b>адрес кошелька</b> или <b>@username</b> для получения криптовалюты:", kb)
    await state.set_state(BuyCryptoSteps.entering_address)
    await callback.answer()

@rt.message(BuyCryptoSteps.entering_address)
async def process_crypto_address(message: Message, state: FSMContext):
    address = message.text.strip()
    if len(address) < 4:
        await message.answer("⚠️ Неверный адрес или юзернейм. Попробуйте еще раз:")
        return
        
    await state.update_data(crypto_address=address)
    data = await state.get_data()
    prod_key = data.get("crypto_product")
    product_info = PRICES.get(prod_key)
    
    if not product_info:
        await message.answer("❌ Ошибка товара.", reply_markup=get_main_reply_keyboard())
        await state.clear()
        return
        
    network = data.get("crypto_net", "TON")
    prod_type = product_info.get("type")
    
    # Покупка USDT/USDC за ЗВЕЗДЫ со списанием с баланса
    if prod_type == "crypto_stars":
        required_stars = product_info.get("stars", 0)
        user_id = message.from_user.id
        current_balance = get_balance(user_id)
        
        if current_balance < required_stars:
            await message.answer(f"❌ Ошибка: недостаточно звезд на балансе ({current_balance} из {required_stars} ⭐).", reply_markup=get_main_reply_keyboard())
            await state.clear()
            return
            
        set_balance(user_id, current_balance - required_stars)
        await state.clear()
        
        await message.answer(
            f"✅ <b>Покупка успешно завершена за звёзды!</b>\n\n"
            f"🪙 Товар: <b>{product_info['title']}</b>\n"
            f"🌐 Сеть: <b>{network}</b>\n"
            f"📥 Получатель: <code>{address}</code>\n"
            f"⭐ Списано с баланса: <b>{required_stars} ⭐</b>\n\n"
            f"Криптовалюта отправляется на ваш адрес!",
            reply_markup=get_main_reply_keyboard(), parse_mode="HTML"
        )
        
        buyer = message.from_user
        await publish_to_reviews_channel(
            order_id=random.randint(1000, 9999), 
            product_title=product_info['title'], 
            buyer=buyer, 
            target_user=address, 
            amount_rub=product_info['amount']
        )
        
        buyer_label = f"@{buyer.username}" if buyer.username else html.escape(buyer.first_name or "без имени")
        admin_text = (
            f"🔥 <b>ПОКУПКА КРИПТЫ ЗА ЗВЕЗДЫ!</b>\n\n"
            f"🪙 Товар: <b>{product_info['title']} ({network})</b>\n"
            f"👤 Покупатель: {buyer_label} (ID: <code>{buyer.id}</code>)\n"
            f"📥 Получатель: <code>{address}</code>\n"
            f"⭐ Оплачено звёздами: <b>{required_stars} ⭐</b>"
        )
        try:
            await message.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
        except Exception:
            logger.exception("Не удалось отправить уведомление админу")
        return

    # Покупка GRAM (TON) через CryptoBot в USDT
    rub_price = product_info["amount"]
    usdt_amount = product_info["usdt"]

    try:
        invoice = await cryptopay.create_invoice(
            asset='USDT',
            amount=usdt_amount,
            description=f"Покупка {product_info['title']} ({network}) для {address} ({rub_price} ₽)",
            payload=f"crypto:{prod_key}:{address}:{network}"
        )
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить счет", url=invoice.bot_invoice_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"checkcrypto_{invoice.invoice_id}")],
            [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
        ])
        
        await message.answer(
            f"🛒 <b>Заказ крипты успешно сформирован!</b>\n\n"
            f"🪙 Товар: <b>{product_info['title']}</b>\n"
            f"🌐 Сеть: <b>{network}</b>\n"
            f"📥 Получатель: <code>{address}</code>\n"
            f"💰 Цена: <b>{rub_price} ₽</b> (оплата: <b>{usdt_amount} USDT</b>)\n\n"
            f"Нажмите кнопку ниже для безопасной оплаты через CryptoBot:",
            reply_markup=kb, parse_mode="HTML"
        )
    except Exception as e:
        logger.error(f"Ошибка создания счета CryptoBot (крипта): {e}")
        await message.answer("⚠️ Произошла ошибка при создании счета. Попробуйте позже.")

    await state.clear()

@rt.callback_query(F.data.startswith("checkcrypto_"))
async def check_crypto_payment(callback: CallbackQuery):
    try:
        invoice_id = int(callback.data.split("_")[1])
    except (IndexError, ValueError):
        await callback.answer("❌ Неверный ID счета.", show_alert=True)
        return

    try:
        invoices = await cryptopay.get_invoices(invoice_ids=invoice_id)
        if not invoices:
            await callback.answer("❌ Счет не найден в системе.", show_alert=True)
            return
            
        invoice = invoices[0]
        
        if invoice.status == 'paid':
            payload = invoice.payload or ""
            parts = payload.split(":", 3)
            prod_key = parts[1] if len(parts) > 1 else "unknown"
            address = parts[2] if len(parts) > 2 else "unknown"
            network = parts[3] if len(parts) > 3 else "TON"
            
            product_info = PRICES.get(prod_key, {"title": "Криптовалюта", "amount": 0})
            
            await safe_edit(
                callback,
                f"✅ <b>Оплата получена, криптовалюта отправлена!</b>\n\n"
                f"🪙 Товар: <b>{product_info['title']}</b>\n"
                f"🌐 Сеть: <b>{network}</b>\n"
                f"📥 Получатель: <code>{address}</code>\n\n"
                f"Средства успешно доставлены.",
                InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 В главное меню", callback_data="back_to_menu")]
                ])
            )
            
            buyer = callback.from_user
            await publish_to_reviews_channel(
                order_id=invoice_id, 
                product_title=product_info['title'], 
                buyer=buyer, 
                target_user=address, 
                amount_rub=product_info['amount']
            )
            
            buyer_label = f"@{buyer.username}" if buyer.username else html.escape(buyer.first_name or "без имени")
            admin_text = (
                f"🔥 <b>УСПЕШНАЯ ПОКУПКА КРИПТЫ!</b>\n\n"
                f"🪙 Товар: <b>{product_info['title']} ({network})</b>\n"
                f"👤 Покупатель: {buyer_label} (ID: <code>{buyer.id}</code>)\n"
                f"📥 Получатель: <code>{address}</code>\n"
                f"💰 Сумма: <b>{invoice.amount} {invoice.asset}</b>\n"
                f"🆔 ID счета: <code>{invoice_id}</code>"
            )
            try:
                await callback.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
            except Exception:
                logger.exception("Не удалось отправить уведомление админу")
                
        else:
            await callback.answer("⏳ Счет еще не оплачен. Оплатите счет и нажмите кнопку снова.", show_alert=True)
            
    except Exception as e:
        logger.error(f"Ошибка проверки счета крипты: {e}")
        await callback.answer("⚠️ Произошла ошибка при проверке счета.", show_alert=True)
# --- КОНЕЦ КРИПТЫ ---

# --- ДОПОЛНИТЕЛЬНЫЕ РОУТЕРЫ ДЛЯ МАГАЗИНА СТАРС И ПРЕМИУМ ---
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
