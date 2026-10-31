import csv
import hashlib
import html
import logging
import os
import random
import re
import string
import uuid
from datetime import datetime

from aiocryptopay import AioCryptoPay, Networks
from aiogram import Bot, F, Router, types
from aiogram.filters import Command, CommandObject, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
)

from config import ALLOWED_ADMIN_IDS, DATABASE, ADMIN_PASSWORD, PASSWORD
from db import BotDb
from exceptions import WrongItemException
from states import user_states

logger = logging.getLogger(__name__)

TEST_MODE = False
TEST_BALANCE = 999
MIN_WITHDRAW = 50
REFERRAL_BONUS = 50
REFERRAL_MIN_STARS = 350

ADMIN_IDS = [int(x) for x in ALLOWED_ADMIN_IDS]
ADMIN_ID = 7461353872

cryptopay = AioCryptoPay(token=os.getenv("CRYPTO_BOT_TOKEN"), network=Networks.MAIN_NET)
FRAGMENT_API_URL = "https://v1.fragmentapi.com/api/v1/partner"
FRAGMENT_API_KEY = os.getenv("FRAGMENT_API_KEY", "")
REVIEW_CHANNEL_ID = os.getenv("REVIEW_CHANNEL_ID", "@your_reviews_channel")

admin_bot = (
    Bot(token=os.getenv("ADMIN_BOT_TOKEN", ""))
    if os.getenv("ADMIN_BOT_TOKEN")
    else None
)

rt = Router()
bot_db = BotDb(DATABASE)


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
    "prod_stars_50": {
        "amount": 72,
        "usdt": 0.89,
        "title": "50 Telegram Stars",
        "type": "stars",
        "quantity": 50,
    },
    "prod_stars_100": {
        "amount": 144,
        "usdt": 1.78,
        "title": "100 Telegram Stars",
        "type": "stars",
        "quantity": 100,
    },
    "prod_stars_150": {
        "amount": 216,
        "usdt": 2.68,
        "title": "150 Telegram Stars",
        "type": "stars",
        "quantity": 150,
    },
    "prod_stars_250": {
        "amount": 360,
        "usdt": 4.47,
        "title": "250 Telegram Stars",
        "type": "stars",
        "quantity": 250,
    },
    "prod_stars_500": {
        "amount": 720,
        "usdt": 8.94,
        "title": "500 Telegram Stars",
        "type": "stars",
        "quantity": 500,
    },
    "prod_stars_1000": {
        "amount": 1440,
        "usdt": 17.89,
        "title": "1000 Telegram Stars",
        "type": "stars",
        "quantity": 1000,
    },
    "prod_stars_2500": {
        "amount": 3600,
        "usdt": 44.72,
        "title": "2500 Telegram Stars",
        "type": "stars",
        "quantity": 2500,
    },
    "prod_prem_3": {
        "amount": 1050,
        "usdt": 13.03,
        "title": "Telegram Premium (3 месяца)",
        "type": "premium",
        "months": 3,
    },
    "prod_prem_6": {
        "amount": 1400,
        "usdt": 17.38,
        "title": "Telegram Premium (6 месяцев)",
        "type": "premium",
        "months": 6,
    },
    "prod_prem_12": {
        "amount": 2450,
        "usdt": 30.42,
        "title": "Telegram Premium (12 месяцев)",
        "type": "premium",
        "months": 12,
    },
    "prod_crypto_ton_1": {
        "amount": 110,
        "usdt": 1.35,
        "title": "1 GRAM (TON)",
        "type": "crypto",
        "coin": "TON",
        "qty": 1,
    },
    "prod_crypto_ton_3": {
        "amount": 330,
        "usdt": 4.09,
        "title": "3 GRAM (TON)",
        "type": "crypto",
        "coin": "TON",
        "qty": 3,
    },
    "prod_crypto_ton_5": {
        "amount": 550,
        "usdt": 6.82,
        "title": "5 GRAM (TON)",
        "type": "crypto",
        "coin": "TON",
        "qty": 5,
    },
    "prod_crypto_ton_7": {
        "amount": 770,
        "usdt": 9.55,
        "title": "7 GRAM (TON)",
        "type": "crypto",
        "coin": "TON",
        "qty": 7,
    },
    "prod_crypto_ton_10": {
        "amount": 1100,
        "usdt": 13.64,
        "title": "10 GRAM (TON)",
        "type": "crypto",
        "coin": "TON",
        "qty": 10,
    },
    "prod_crypto_usdt_1": {
        "amount": 45,
        "usdt": 1,
        "stars": 56,
        "title": "1 USDT",
        "type": "crypto_native_stars",
        "coin": "USDT",
        "qty": 1,
    },
    "prod_crypto_usdt_3": {
        "amount": 135,
        "usdt": 3,
        "stars": 169,
        "title": "3 USDT",
        "type": "crypto_native_stars",
        "coin": "USDT",
        "qty": 3,
    },
    "prod_crypto_usdt_5": {
        "amount": 225,
        "usdt": 5,
        "stars": 281,
        "title": "5 USDT",
        "type": "crypto_native_stars",
        "coin": "USDT",
        "qty": 5,
    },
    "prod_crypto_usdt_7": {
        "amount": 315,
        "usdt": 7,
        "stars": 393,
        "title": "7 USDT",
        "type": "crypto_native_stars",
        "coin": "USDT",
        "qty": 7,
    },
    "prod_crypto_usdt_10": {
        "amount": 450,
        "usdt": 10,
        "stars": 562,
        "title": "10 USDT",
        "type": "crypto_native_stars",
        "coin": "USDT",
        "qty": 10,
    },
    "prod_crypto_usdc_1": {
        "amount": 45,
        "usdt": 1,
        "stars": 56,
        "title": "1 USDC",
        "type": "crypto_native_stars",
        "coin": "USDC",
        "qty": 1,
    },
    "prod_crypto_usdc_3": {
        "amount": 135,
        "usdt": 3,
        "stars": 169,
        "title": "3 USDC",
        "type": "crypto_native_stars",
        "coin": "USDC",
        "qty": 3,
    },
    "prod_crypto_usdc_5": {
        "amount": 225,
        "usdt": 5,
        "stars": 281,
        "title": "5 USDC",
        "type": "crypto_native_stars",
        "coin": "USDC",
        "qty": 5,
    },
    "prod_crypto_usdc_7": {
        "amount": 315,
        "usdt": 7,
        "stars": 393,
        "title": "7 USDC",
        "type": "crypto_native_stars",
        "coin": "USDC",
        "qty": 7,
    },
    "prod_crypto_usdc_10": {
        "amount": 450,
        "usdt": 10,
        "stars": 562,
        "title": "10 USDC",
        "type": "crypto_native_stars",
        "coin": "USDC",
        "qty": 10,
    },
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


async def safe_edit(
    callback: CallbackQuery, text: str, reply_markup=None
) -> None:
  try:
    await callback.message.edit_text(
        text, reply_markup=reply_markup, parse_mode="HTML"
    )
  except Exception as e:
    if "message is not modified" not in str(e):
      raise


def get_main_reply_keyboard():
  return ReplyKeyboardMarkup(
      keyboard=[
          [
              KeyboardButton(text="🪙 Криптовалюта"),
              KeyboardButton(text="⭐ Купить звёзды"),
          ],
          [
              KeyboardButton(text="📦 История заказов"),
              KeyboardButton(text="👤 Профиль"),
          ],
          [KeyboardButton(text="💬 Отзывы"), KeyboardButton(text="👥 Рефералы")],
          [KeyboardButton(text="🛟 Поддержка")],
      ],
      resize_keyboard=True,
      input_field_placeholder="Выберите пункт меню 👇",
  )


def back_keyboard():
  return InlineKeyboardMarkup(
      inline_keyboard=[[InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]]
  )


async def publish_to_reviews_channel(
    order_id, product_title, buyer, target_user, amount_rub
):
  if not admin_bot:
    return
  now = datetime.now().strftime("%d.%m.%Y %H:%M")
  buyer_label = (
      f"@{buyer.username}"
      if buyer.username
      else html.escape(buyer.first_name or "Без имени")
  )
  text = (
      f"<b>📦 ЗАКАЗ #{order_id}</b>\n"
      f"<b>❌ Статус:</b> ✅ Выполнен\n"
      f"<b>👤 Покупатель:</b> {buyer_label} (ID: <code>{buyer.id}</code>)\n"
      f"<b>🛍 Товар:</b> {product_title}\n"
      f"<b>💰 Сумма:</b> <b>{amount_rub} ₽</b>\n"
      f"<b>🇺🇦 Получатель:</b> <code>{target_user}</code>\n"
      f"<b>📅 Дата:</b> {now}"
  )
  try:
    raw_ch = REVIEW_CHANNEL_ID.strip()
    ch = (
        int(raw_ch)
        if raw_ch.startswith("-") or raw_ch.isdigit()
        else raw_ch
    )
    await admin_bot.send_message(ch, text, parse_mode="HTML")
  except Exception as e:
    logger.error(f"Не удалось отправить отчет в канал отзывов через admin_bot: {e}")


@rt.message(Command("start"))
async def start_handler(
    message: Message, state: FSMContext, command: CommandObject = None
):
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
      if referrer_id in ADMIN_IDS:
        bot_db.update_balance(user_id, 0)
      if referrer_id:
        try:
          await message.bot.send_message(
              referrer_id,
              f"🎉 По вашей ссылке зарегистрировался новый пользователь: <b>{user_name}</b>!",
              parse_mode="HTML",
          )
        except Exception:
          logger.exception("Не удалось уведомить реферера %s", referrer_id)
    else:
      bot_db.add_user(user_id)

  balance = get_balance(user_id)
  bot_username = (await message.bot.get_me()).username
  ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

  text = (
      f"<b>Добро пожаловать, {user_name}! Ты попал в GumStars — лучший бот по покупке криптовалюты и цифровых товаров ⭐</b>\n\n"
      f"🪙 Твой баланс звезд: <b>{balance}</b> ⭐\n"
      f"💎 Реферальная система:\n"
      f"• Приглашай друзей по своей ссылке: <code>{ref_link}</code>\n"
      f"• Когда твой друг купит товар на сумму от 500 ₽, тебе на баланс автоматически зачислится <b>{REFERRAL_BONUS}</b> ⭐!\n\n"
      f"Выберите нужный раздел в меню ниже 👇"
  )
  await message.answer(text, reply_markup=get_main_reply_keyboard(), parse_mode="HTML")


@rt.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext):
  await state.clear()
  user_name = html.escape(callback.from_user.first_name or "друг")
  balance = get_balance(callback.from_user.id)
  text = (
      f"<b>Добро пожаловать, {user_name}! Ты попал в GumStars — лучший бот по покупке криптовалюты и цифровых товаров ⭐</b>\n\n"
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
  raw_ch = REVIEW_CHANNEL_ID.strip()
  channel_url = (
      f"https://t.me/{raw_ch.lstrip('@')}"
      if not raw_ch.startswith("-")
      else "https://t.me/"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="⭐ Перейти в канал с отзывами", url=channel_url)],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await message.answer(
      "<b>💬 Отзывы и выполненные заказы!</b>\n\nЗдесь вы можете ознакомиться с реальными отзывами наших клиентов и списком выполненных заказов ✨",
      reply_markup=kb,
      parse_mode="HTML",
  )


@rt.message(F.text == "🪙 Криптовалюта")
async def text_crypto_main(message: Message, state: FSMContext):
  await state.clear()
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="🪙 USDT", callback_data="crypto_coin_USDT")],
          [InlineKeyboardButton(text="💲 USDC", callback_data="crypto_coin_USDC")],
          [InlineKeyboardButton(text="💎 GRAM (TON)", callback_data="crypto_coin_TON")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await message.answer("<b>🪙 Покупка криптовалюты</b>\n\nВыберите нужную монету:", reply_markup=keyboard, parse_mode="HTML")


@rt.message(F.text == "⭐ Купить звёзды")
async def text_stars(message: Message, state: FSMContext):
  await state.clear()
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="⭐ Купить Telegram Stars", callback_data="cat_stars")],
          [InlineKeyboardButton(text="💎 Купить Telegram Premium", callback_data="cat_premium")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await message.answer("<b>⭐ Магазин Telegram Stars & Premium</b>\n\nВыберите категорию товара:", reply_markup=kb, parse_mode="HTML")


@rt.message(F.text == "📦 История заказов")
async def text_orders(message: Message, state: FSMContext):
  await state.clear()
  await message.answer("<b>📦 История заказов</b>\n\nУ вас пока нет активных или завершенных заказов.", parse_mode="HTML")


@rt.message(F.text == "👤 Профиль")
async def text_profile(message: Message, state: FSMContext):
  await state.clear()
  user_id = message.from_user.id
  user_name = html.escape(message.from_user.first_name or "друг")
  text = (
      f"<b>👤 ЛИЧНЫЙ КАБИНЕТ</b>\n\n"
      f"• Имя: <b>{user_name}</b>\n"
      f"• ID: <code>{user_id}</code>\n"
      f"• Баланс звезд: <b>{get_balance(user_id)}</b> ⭐\n"
      f"• Активных заказов: <b>0</b>\n"
      f"• Сумма покупок: <b>0.00 ₽</b>"
  )
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="👥 Реферальная система", callback_data="ref")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
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
      f"<b>👥 РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
      f"Приглашай друзей и получай <b>{REFERRAL_BONUS}</b> ⭐ за каждого, кто купит товар на сумму от 500 ₽.\n\n"
      f"🔗 Ваша реферальная ссылка: <code>{ref_link}</code>\n"
      f"👥 Приглашено друзей: <b>{referrals}</b>\n"
      f"⭐ Доступно на балансе: <b>{balance}</b>"
  )
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="📤 Вывести звёзды", callback_data="withdraw_stars")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await message.answer(text, reply_markup=keyboard, parse_mode="HTML")


@rt.message(F.text == "🛟 Поддержка")
async def text_support(message: Message, state: FSMContext):
  await state.set_state(user_states.waiting_for_support)
  await message.answer("<b>🛟 Служба поддержки</b>\n\nОтправьте в чат вашу проблему или вопрос — мы постараемся ответить максимально быстро.", parse_mode="HTML")


@rt.callback_query(F.data == "ref")
async def ref_callback(callback: CallbackQuery, state: FSMContext):
  await state.clear()
  user_id = callback.from_user.id
  balance = get_balance(user_id)
  referrals = get_referrals_count(user_id)
  bot_username = (await callback.bot.get_me()).username
  ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
  text = (
      f"<b>👥 РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
      f"Приглашай друзей и получай <b>{REFERRAL_BONUS}</b> ⭐ за каждого, кто купит товар на сумму от 500 ₽.\n\n"
      f"🔗 Ваша реферальная ссылка: <code>{ref_link}</code>\n"
      f"👥 Приглашено друзей: <b>{referrals}</b>\n"
      f"⭐ Доступно на балансе: <b>{balance}</b>"
  )
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="📤 Вывести звёзды", callback_data="withdraw_stars")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await safe_edit(callback, text, keyboard)
  await callback.answer()


@rt.callback_query(F.data == "profile")
async def profile_callback(callback: CallbackQuery, state: FSMContext):
  await state.clear()
  user_id = callback.from_user.id
  user_name = html.escape(callback.from_user.first_name or "друг")
  text = (
      f"<b>👤 ЛИЧНЫЙ КАБИНЕТ</b>\n\n"
      f"• Имя: <b>{user_name}</b>\n"
      f"• ID: <code>{user_id}</code>\n"
      f"• Баланс звезд: <b>{get_balance(user_id)}</b> ⭐\n"
      f"• Активных заказов: <b>0</b>\n"
      f"• Сумма покупок: <b>0.00 ₽</b>"
  )
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="👥 Реферальная система", callback_data="ref")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await safe_edit(callback, text, keyboard)
  await callback.answer()


@rt.callback_query(F.data.startswith("crypto_coin_"))
async def select_crypto_coin(callback: CallbackQuery, state: FSMContext):
  coin = callback.data.split("_")[2]
  await state.update_data(crypto_coin=coin)
  if coin == "USDT":
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="TON Network", callback_data="net_TON")],
            [InlineKeyboardButton(text="TRC20 Network", callback_data="net_TRC20")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")],
        ]
    )
  elif coin == "USDC":
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="TON Network", callback_data="net_TON")],
            [InlineKeyboardButton(text="Ethereum (ERC20)", callback_data="net_ERC20")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")],
        ]
    )
  else:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="TON Network", callback_data="net_TON")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")],
        ]
    )
  await safe_edit(callback, "<b>🌐 Выберите сеть для слияния:</b>", kb)
  await callback.answer()


@rt.callback_query(F.data == "crypto_back")
async def crypto_back(callback: CallbackQuery, state: FSMContext):
  await state.clear()
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="🪙 USDT", callback_data="crypto_coin_USDT")],
          [InlineKeyboardButton(text="💲 USDC", callback_data="crypto_coin_USDC")],
          [InlineKeyboardButton(text="💎 GRAM (TON)", callback_data="crypto_coin_TON")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await safe_edit(callback, "<b>🪙 Покупка криптовалюты</b>\n\nВыберите нужную монету:", keyboard)
  await callback.answer()


@rt.callback_query(F.data.startswith("net_"))
async def select_crypto_network(callback: CallbackQuery, state: FSMContext):
  network = callback.data.split("_")[1]
  await state.update_data(crypto_net=network)
  data = await state.get_data()
  coin = data.get("crypto_coin", "USDT")

  if coin == "TON":
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1 GRAM - 110 ₽ (1.35 USDT)", callback_data="prod_crypto_ton_1")],
            [InlineKeyboardButton(text="3 GRAM - 330 ₽ (4.09 USDT)", callback_data="prod_crypto_ton_3")],
            [InlineKeyboardButton(text="5 GRAM - 550 ₽ (6.82 USDT)", callback_data="prod_crypto_ton_5")],
            [InlineKeyboardButton(text="7 GRAM - 770 ₽ (9.55 USDT)", callback_data="prod_crypto_ton_7")],
            [InlineKeyboardButton(text="10 GRAM - 1100 ₽ (13.64 USDT)", callback_data="prod_crypto_ton_10")],
            [InlineKeyboardButton(text="✍️ Указать своё количество", callback_data="custom_crypto_amount")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")],
        ]
    )
  elif coin == "USDC":
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1 USDC - 45 ₽ (56 звезд) ⭐", callback_data="prod_crypto_usdc_1")],
            [InlineKeyboardButton(text="3 USDC - 135 ₽ (169 звезд) ⭐", callback_data="prod_crypto_usdc_3")],
            [InlineKeyboardButton(text="5 USDC - 225 ₽ (281 звезд) ⭐", callback_data="prod_crypto_usdc_5")],
            [InlineKeyboardButton(text="7 USDC - 315 ₽ (393 звезд) ⭐", callback_data="prod_crypto_usdc_7")],
            [InlineKeyboardButton(text="10 USDC - 450 ₽ (562 звезд) ⭐", callback_data="prod_crypto_usdc_10")],
            [InlineKeyboardButton(text="🔄 Обменять GRAM на USDT/USDC", callback_data="exchange_gram_to_stable")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")],
        ]
    )
  else:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1 USDT - 45 ₽ (56 звезд) ⭐", callback_data="prod_crypto_usdt_1")],
            [InlineKeyboardButton(text="3 USDT - 135 ₽ (169 звезд) ⭐", callback_data="prod_crypto_usdt_3")],
            [InlineKeyboardButton(text="5 USDT - 225 ₽ (281 звезд) ⭐", callback_data="prod_crypto_usdt_5")],
            [InlineKeyboardButton(text="7 USDT - 315 ₽ (393 звезд) ⭐", callback_data="prod_crypto_usdt_7")],
            [InlineKeyboardButton(text="10 USDT - 450 ₽ (562 звезд) ⭐", callback_data="prod_crypto_usdt_10")],
            [InlineKeyboardButton(text="🔄 Обменять GRAM на USDT/USDC", callback_data="exchange_gram_to_stable")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")],
        ]
    )

  await safe_edit(callback, f"<b>📦 Выберите количество {coin} (Сеть: {network}):</b>", kb)
  await callback.answer()


@rt.callback_query(F.data == "custom_crypto_amount")
async def custom_crypto_amount(callback: CallbackQuery, state: FSMContext):
  kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]])
  await safe_edit(callback, "<b>✍️ Введите в чат нужное вам количество монеты цифровой (например: <code>1.5</code> или <code>5</code>):</b>", kb)
  await state.set_state(BuyCryptoSteps.entering_custom_amount)
  await callback.answer()


@rt.callback_query(F.data == "exchange_gram_to_stable")
async def exchange_gram_to_stable(callback: CallbackQuery, state: FSMContext):
  kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]])
  await safe_edit(callback, "<b>🔄 Обмен GRAM на USDT/USDC (Полуавтоматический режим)</b>\n\nНапишите в чат детальный запрос (например: <code>Хочу обменять 10 GRAM на USDT</code>):", kb)
  await state.set_state(BuyCryptoSteps.entering_custom_amount)
  await callback.answer()


@rt.message(BuyCryptoSteps.entering_custom_amount)
async def process_custom_crypto_message(message: Message, state: FSMContext):
  text_val = message.text.strip()
  data = await state.get_data()
  coin = data.get("crypto_coin", "TON")
  network = data.get("crypto_net", "TON")
  await state.clear()
  await message.answer(
      "<b>⏳ Заявка принята в обработку (Полуавтоматический режим)!</b>\n\n"
      f"• Запрос: <code>{text_val}</code>\n"
      f"• Сеть: <b>{network}</b>\n\n"
      "Администратор уже получил уведомление и свяжется с вами для проведения сделки.",
      reply_markup=get_main_reply_keyboard(),
      parse_mode="HTML",
  )
  buyer = message.from_user
  buyer_label = (
      f"@{buyer.username}"
      if buyer.username
      else html.escape(buyer.first_name or "Без имени")
  )
  admin_text = (
      "<b>🚨 ЗАЯВКА НА ОБМЕН / КАСТОМНОЕ КОЛИЧЕСТВО!</b>\n\n"
      f"<b>👤 Покупатель:</b> {buyer_label} (ID: <code>{buyer.id}</code>)\n"
      f"<b>🪙 Монета/Сеть:</b> {coin} ({network})\n"
      f"<b>💬 Детали от клиента:</b>\n<code>{text_val}</code>"
  )
  try:
    await message.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
  except Exception:
    logger.exception("Не удалось отправить уведомление админу")
 
@rt.callback_query(F.data.startswith("prod_crypto_"))
async def ask_crypto_recipient(callback: CallbackQuery, state: FSMContext):
  prod_key = callback.data.replace("prod_", "")
  await state.update_data(crypto_product=prod_key)
  kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")]])
  await safe_edit(callback, "<b>✏️ Отправьте в чат ваш адрес кошелька или @username для получения криптовалюты:</b>", kb)
  await state.set_state(BuyCryptoSteps.entering_address)
  await callback.answer()


@rt.message(BuyCryptoSteps.entering_address)
async def process_crypto_address(message: Message, state: FSMContext):
  address = message.text.strip()
  if len(address) < 4:
    await message.answer("<b>⚠️ Неверный адрес или юзернейм. Попробуйте еще раз:</b>", parse_mode="HTML")
    return

  await state.update_data(crypto_address=address)
  data = await state.get_data()
  prod_key = data.get("crypto_product")
  product_info = PRICES.get(prod_key)

  if not product_info:
    await message.answer("<b>❌ Ошибка товара.</b>", reply_markup=get_main_reply_keyboard(), parse_mode="HTML")
    await state.clear()
    return

  network = data.get("crypto_net", "TON")
  prod_type = product_info.get("type")

  # НАТИВНЫЙ ИНВОЙС TELEGRAM STARS ДЛЯ ПОКУПКИ USDT / USDC
  if prod_type == "crypto_native_stars":
    stars_amount = product_info.get("stars", 1)
    await state.clear()

    prices = [LabeledPrice(label=product_info["title"], amount=stars_amount)]
    await message.bot.send_invoice(
        chat_id=message.chat.id,
        title=f"Покупка {product_info['title']}",
        description=f"Сеть: {network} | Получатель: {address}",
        payload=f"native_star_crypto:{prod_key}:{address}:{network}",
        currency="XTR",
        prices=prices,
    )
    return

  # Покупка GRAM (TON) через CryptoBot в USDT
  rub_price = product_info["amount"]
  usdt_amount = product_info["usdt"]

  try:
    invoice = await cryptopay.create_invoice(
        asset="USDT",
        amount=usdt_amount,
        description=f"Покупка {product_info['title']} ({network}) для {address} ({rub_price} P)",
        payload=f"{prod_key}:{address}:{network}",
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить счет", url=invoice.bot_invoice_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"checkcrypto_{invoice.invoice_id}")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
        ]
    )

    await message.answer(
        "<b>✅ Заказ крипты успешно сформирован!</b>\n\n"
        f"📦 Товар: <b>{product_info['title']}</b>\n"
        f"🌐 Сеть: <b>{network}</b>\n"
        f"👤 Получатель: <code>{address}</code>\n"
        f"💰 Цена: <b>{rub_price} ₽</b> (оплата: <b>{usdt_amount} USDT</b>)\n\n"
        "Нажмите кнопку ниже для безопасной оплаты через CryptoBot:",
        reply_markup=kb,
        parse_mode="HTML",
    )
  except Exception as e:
    logger.error(f"Ошибка создания счета CryptoBot (крипта): {e}")
    await message.answer("<b>❌ Произошла ошибка при создании счета. Попробуйте позже.</b>", parse_mode="HTML")

  await state.clear()


@rt.pre_checkout_query()
async def pre_checkout_handler(pre_checkout_query: PreCheckoutQuery):
  await pre_checkout_query.answer(ok=True)


async def create_cryptobot_check_for_stars(
    asset: str, amount: float, user_id: int
):
  """Автоматическое создание чека CryptoBot для выдачи за Telegram Stars"""
  try:
    check = await cryptopay.create_check(
        asset=asset, amount=amount, pin_to_user_id=user_id
    )
    return check.bot_check_url
  except Exception as e:
    logger.error(f"Ошибка создания чека CryptoBot для выдачи за звёзды: {e}")
    return None


@rt.message(F.successful_payment)
async def successful_payment_handler(message: Message):
  payment_info = message.successful_payment
  payload = payment_info.invoice_payload or ""

  if payload.startswith("native_star_crypto:"):
    parts = payload.split(":", 3)
    prod_key = parts[1] if len(parts) > 1 else "unknown"
    address = parts[2] if len(parts) > 2 else "unknown"
    network = parts[3] if len(parts) > 3 else "TON"

    product_info = PRICES.get(prod_key, {"title": "Криптовалюта", "amount": 0})
    coin_asset = product_info.get("coin", "USDT")
    crypto_amount = product_info.get("usdt", 0)

    # Генерация реального чека CryptoBot для автоматической выдачи
    check_url = await create_cryptobot_check_for_stars(
        asset=coin_asset, amount=crypto_amount, user_id=message.from_user.id
    )

    if check_url:
      await message.answer(
          "<b>✅ Оплата Telegram Stars получена!</b>\n\n"
          f"📦 Товар: <b>{product_info['title']}</b>\n"
          f"🌐 Сеть: <b>{network}</b>\n"
          f"👤 Получатель: <code>{address}</code>\n\n"
          f"🎉 <b>Твой чек на получение {crypto_amount} {coin_asset}:</b>\n"
          f"👉 <a href='{check_url}'>Забрать криптовалюту в CryptoBot</a>",
          reply_markup=get_main_reply_keyboard(),
          parse_mode="HTML",
          disable_web_page_preview=True,
      )
    else:
      await message.answer(
          "<b>✅ Оплата получена, но произошла ошибка при авто-создании чека.</b>\n"
          "Администратор уже уведомлен, средства будут выданы вручную в ближайшее время!",
          reply_markup=get_main_reply_keyboard(),
          parse_mode="HTML",
      )

    buyer = message.from_user
    await publish_to_reviews_channel(
        order_id=random.randint(1000, 9999),
        product_title=product_info["title"],
        buyer=buyer,
        target_user=address,
        amount_rub=product_info["amount"],
    )

    buyer_label = (
        f"@{buyer.username}"
        if buyer.username
        else html.escape(buyer.first_name or "Без имени")
    )
    admin_text = (
        "<b>🔥 УСПЕШНАЯ ПОКУПКА КРИПТЫ ЗА TELEGRAM STARS!</b>\n\n"
        f"📦 Товар: <b>{product_info['title']}</b> ({network})\n"
        f"👤 Покупатель: {buyer_label} (ID: <code>{buyer.id}</code>)\n"
        f"📍 Получатель: <code>{address}</code>\n"
        f"⭐ Оплачено звёздам: <b>{payment_info.total_amount} Stars</b>\n"
        f"🤖 Чек выдан: {'Успешно' if check_url else 'ОШИБКА ВЫДАЧИ ЧЕКА'}"
    )
    try:
      await message.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    except Exception:
      logger.exception("Не удалось отправить уведомление админу")


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

    if invoice.status == "paid":
      payload = invoice.payload or ""
      parts = payload.split(":", 3)
      prod_key = parts[0] if len(parts) > 0 else "unknown"
      address = parts[1] if len(parts) > 1 else "unknown"
      network = parts[2] if len(parts) > 2 else "TON"

      product_info = PRICES.get(prod_key, {"title": "Криптовалюта", "amount": 0})

      await safe_edit(
          callback,
          "<b>✅ Оплата получена, криптовалюта отправлена!</b>\n\n"
          f"📦 Товар: <b>{product_info['title']}</b>\n"
          f"🌐 Сеть: <b>{network}</b>\n"
          f"👤 Получатель: <code>{address}</code>\n"
          f"💎 Средства успешно доставлены.",
          InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]]),
      )

      buyer = callback.from_user
      await publish_to_reviews_channel(
          order_id=invoice.invoice_id,
          product_title=product_info["title"],
          buyer=buyer,
          target_user=address,
          amount_rub=product_info["amount"],
      )

      buyer_label = (
          f"@{buyer.username}"
          if buyer.username
          else html.escape(buyer.first_name or "Без имени")
      )
      admin_text = (
          "<b>🔥 УСПЕШНАЯ ПОКУПКА КРИПТЫ!</b>\n\n"
          f"📦 Товар: <b>{product_info['title']}</b> ({network})\n"
          f"👤 Покупатель: {buyer_label} (ID: <code>{buyer.id}</code>)\n"
          f"📍 Получатель: <code>{address}</code>\n"
          f"💰 Сумма: <b>{invoice.amount} {invoice.asset}</b>\n"
          f"🆔 ID счета: <code>{invoice.invoice_id}</code>"
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

@rt.message(user_states.waiting_for_support)
async def process_support_message(message: Message, state: FSMContext):
  user_id = message.from_user.id
  user_name = html.escape(message.from_user.first_name or "")
  username = (
      f"@{message.from_user.username}"
      if message.from_user.username
      else "нет юзернейма"
  )
  body = html.escape(message.text or message.caption or "[вложение]")

  admin_text = (
      "<b>🛟 Новое обращение в поддержку!</b>\n\n"
      f"<b>От:</b> {user_name} ({username})\n"
      f"<b>ID:</b> <code>{user_id}</code>\n"
      f"<b>Сообщение:</b>\n{body}"
  )
  try:
    await message.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
    if not message.text:
      await message.copy_to(ADMIN_ID)
  except Exception:
    logger.exception("Не удалось отправить обращение в поддержку админу")

  await message.answer("<b>✅ Ваше сообщение успешно отправлено в поддержку! Ожидайте ответа.</b>", reply_markup=get_main_reply_keyboard(), parse_mode="HTML")
  await state.clear()


@rt.callback_query(F.data == "withdraw_stars")
async def withdraw_stars_callback(callback: CallbackQuery, state: FSMContext):
  balance = get_balance(callback.from_user.id)
  await state.set_state(WithdrawState.waiting_for_amount)

  text = (
      f"<b>📤 ВЫВОД ЗВЕЗД</b>\n\n"
      f"• На вашем балансе: <b>{balance}</b> ⭐\n"
      f"• Минимум для вывода: <b>{MIN_WITHDRAW}</b> ⭐\n\n"
      "<b>✍️ Напишите в чат число — сколько звезд вы хотите вывести:</b>"
  )
  keyboard = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]])
  await safe_edit(callback, text, keyboard)
  await callback.answer()


@rt.message(WithdrawState.waiting_for_amount)
async def process_withdraw_amount(message: Message, state: FSMContext):
  user = message.from_user
  user_id = user.id
  raw = message.text.strip()

  if not re.fullmatch(r"[0-9]+", raw):
    await message.answer("<b>❌ Введите целое число цифрами, например: 100</b>", parse_mode="HTML")
    return

  amount = int(raw)
  balance = get_balance(user_id)

  if amount < MIN_WITHDRAW:
    await message.answer(f"<b>❌ Минимальная сумма для вывода: {MIN_WITHDRAW} ⭐. Введите сумму побольше:</b>", parse_mode="HTML")
    return
  if amount > balance:
    await message.answer(f"<b>❌ Недостаточно звезд. Доступно: {balance} ⭐. Введите меньше сумму:</b>", parse_mode="HTML")
    return

  new_balance = balance - amount
  set_balance(user_id, new_balance)
  await state.clear()

  await message.answer(
      "<b>✅ Заявка на вывод успешно создана!</b>\n\n"
      f"⏳ Ожидайте зачисления звезд. Остался баланс: <b>{new_balance}</b> ⭐.",
      reply_markup=get_main_reply_keyboard(),
      parse_mode="HTML",
  )

  user_label = (
      f"@{user.username}"
      if user.username
      else html.escape(user.first_name or "Без имени")
  )
  try:
    await message.bot.send_message(
        ADMIN_ID,
        "<b>📤 Новая заявка на вывод звезд!</b>\n\n"
        f"<b>👤 Пользователь:</b> {user_label} (ID: <code>{user_id}</code>)\n"
        f"<b>⭐ Сумма к выводу:</b> <b>{amount}</b> ⭐",
        parse_mode="HTML",
    )
  except Exception:
    logger.exception("Не удалось отправить уведомление админу (ID-%s)", ADMIN_ID)


@rt.callback_query(F.data.in_({"cat_stars", "cat_premium"}))
async def process_category(callback: CallbackQuery, state: FSMContext):
  category = "stars" if callback.data == "cat_stars" else "premium"
  await state.update_data(category=category)

  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="👤 Себе", callback_data="recipient_self")],
          [InlineKeyboardButton(text="Другу (по username)", callback_data="recipient_friend")],
          [InlineKeyboardButton(text="🔙 Назад", callback_data="stars")],
      ]
  )
  await safe_edit(callback, "<b>👤 Кому отправляем заказ?</b>", kb)
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
  await callback.message.edit_text(
      "<b>✏️ Отправьте в чат @username получателя (например, <code>@durov</code>):</b>",
      reply_markup=kb,
      parse_mode="HTML",
  )
  await state.set_state(BuySteps.entering_username)
  await callback.answer()


@rt.message(BuySteps.entering_username)
async def process_username_input(message: Message, state: FSMContext):
  username = message.text.strip()
  if not username.startswith("@"):
    username = f"@{username}"
  if len(username) < 4:
    await message.answer("<b>⚠️ Неверный формат юзернейма. Попробуйте еще раз:</b>", parse_mode="HTML")
    return

  await state.update_data(target_user=username)
  await message.answer(f"<b>✅ Получатель сохранен: <b>{username}</b></b>", parse_mode="HTML")
  await show_products(message, state)


async def show_products(message: Message, state: FSMContext):
  data = await state.get_data()
  category = data.get("category")

  if category == "stars":
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 50 звезд — 72 ₽", callback_data="prod_stars_50")],
            [InlineKeyboardButton(text="⭐ 100 звезд — 144 ₽", callback_data="prod_stars_100")],
            [InlineKeyboardButton(text="⭐ 150 звезд — 216 ₽", callback_data="prod_stars_150")],
            [InlineKeyboardButton(text="⭐ 250 звезд — 360 ₽", callback_data="prod_stars_250")],
            [InlineKeyboardButton(text="⭐ 500 звезд — 720 ₽", callback_data="prod_stars_500")],
            [InlineKeyboardButton(text="⭐ 1000 звезд — 1440 ₽", callback_data="prod_stars_1000")],
            [InlineKeyboardButton(text="⭐ 2500 звезд — 3600 ₽", callback_data="prod_stars_2500")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
        ]
    )
    text = "<b>⭐ Выберите необходимый пакет звезд:</b>"
  else:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 3 месяца — 1 050 ₽", callback_data="prod_prem_3")],
            [InlineKeyboardButton(text="💎 6 месяцев — 1 400 ₽", callback_data="prod_prem_6")],
            [InlineKeyboardButton(text="💎 12 месяцев — 2 450 ₽", callback_data="prod_prem_12")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
        ]
    )
    text = "<b>💎 Выберите срок подписки TG Premium:</b>"

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
        asset="USDT",
        amount=usdt_amount,
        description=f"Покупка {product_info['title']} для {target_user} (Эквивалент: {rub_price} P)",
        payload=f"{product_key}:{target_user}",
    )

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💳 Оплатить счет", url=invoice.bot_invoice_url)],
            [InlineKeyboardButton(text="🔄 Проверить оплату", callback_data=f"checkcrypto_{invoice.invoice_id}")],
            [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
        ]
    )

    await safe_edit(
        callback,
        "<b>✅ Заказ успешно сформирован!</b>\n\n"
        f"📦 Товар: <b>{product_info['title']}</b>\n"
        f"👤 Получатель: <code>{target_user}</code>\n"
        f"💰 Цена: <b>{rub_price} ₽</b> (оплата: <b>{usdt_amount} USDT</b>)\n\n"
        "Нажмите кнопку ниже для безопасной оплаты через CryptoBot:",
        kb,
    )
  except Exception as e:
    logger.error(f"Ошибка создания счета CryptoBot: {e}")
    await callback.answer("⚠️ Произошла ошибка при создании счета на оплату. Попробуйте позже.", show_alert=True)

  await state.clear()
    
