import asyncio
import aiohttp
import csv
import hashlib
import html
import json
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
    FSInputFile,
    URLInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
    ReplyKeyboardMarkup,
)

from config import ALLOWED_ADMIN_IDS, DATABASE, ADMIN_PASSWORD, PASSWORD
from db import BotDB

logger = logging.getLogger(__name__)

TEST_MODE = False
TEST_BALANCE = 999
MIN_WITHDRAW = 50
REFERRAL_BONUS = 50
REFERRAL_MIN_STARS = 350
REFERRAL_MIN_AMOUNT = 1  # 🧪 ТЕСТОВЫЙ РЕЖИМ: Бонус 50 звезд начисляется при покупке от 1 ₽

ADMIN_IDS = [int(x.strip()) for x in ALLOWED_ADMIN_IDS.split(",") if x.strip().isdigit()]
ADMIN_ID = 7461353872

# Настройки CrystalPAY (СБП и банковские карты РФ)
CRYSTAL_AUTH_LOGIN = os.getenv("CRYSTAL_AUTH_LOGIN", "gumstarsshop")
CRYSTAL_SECRET_KEY = os.getenv("CRYSTAL_SECRET_KEY", "")
CRYSTAL_CASH_NAME = os.getenv("CRYSTAL_CASH_NAME", "GumStars")

cryptopay = AioCryptoPay(token=os.getenv("CRYPTO_BOT_TOKEN"), network=Networks.MAIN_NET)
FRAGMENT_API_URL = os.getenv("FRAGMENT_API_URL", "https://api.fragment-api.com/api/v1/partner")
FRAGMENT_API_KEY = os.getenv("FRAGMENT_API_KEY", "")
REVIEW_CHANNEL_ID = os.getenv("REVIEW_CHANNEL_ID", "@your_reviews_channel")

admin_bot = (
    Bot(token=os.getenv("ADMIN_BOT_TOKEN", ""))
    if os.getenv("ADMIN_BOT_TOKEN")
    else None
)

rt = Router()
bot_db = BotDB(DATABASE)
CRYSTAL_PENDING_ORDERS = {}

async def create_crystalpay_invoice(amount: float, description: str, extra: str = "") -> dict:
    """Создание ссылки на оплату через CrystalPAY (СБП и банковские карты РФ)"""
    if not CRYSTAL_SECRET_KEY:
        logger.warning("CRYSTAL_SECRET_KEY не настроен в переменных окружения Render!")
        return {"ok": False, "error": "Ключ кассы не настроен"}

    url = "https://api.crystalpay.io/v2/invoice/create/"
    payload = {
        "auth_login": CRYSTAL_AUTH_LOGIN,
        "auth_secret": CRYSTAL_SECRET_KEY,
        "amount": amount,
        "type": "purchase",
        "description": description[:120],
        "redirect_url": "https://t.me/GumStars_bot",
        "extra": extra[:120],
        "lifetime": 60,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=20) as resp:
                data = await resp.json()
                if not data.get("error") and data.get("url"):
                    return {
                        "ok": True,
                        "invoice_id": data.get("id"),
                        "url": data.get("url"),
                    }
                err_msg = ", ".join(data.get("errors", [])) or "Ошибка создания счета"
                logger.error(f"CrystalPAY API error: {data}")
                return {"ok": False, "error": err_msg}
    except Exception as e:
        logger.error(f"CrystalPAY connection error: {e}")
        return {"ok": False, "error": str(e)}

async def check_crystalpay_invoice(invoice_id: str) -> dict:
    """Проверка статуса оплаты инвойса в CrystalPAY"""
    if not CRYSTAL_SECRET_KEY:
        return {"ok": False, "is_paid": False, "error": "Ключ кассы не настроен"}

    url = "https://api.crystalpay.io/v2/invoice/info/"
    payload = {
        "auth_login": CRYSTAL_AUTH_LOGIN,
        "auth_secret": CRYSTAL_SECRET_KEY,
        "id": invoice_id,
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload, timeout=20) as resp:
                data = await resp.json()
                if not data.get("error"):
                    state = str(data.get("state", "")).lower()
                    # В CrystalPAY v2 оплаченный статус = "payed"
                    is_paid = state in ("payed", "paid")
                    return {
                        "ok": True,
                        "is_paid": is_paid,
                        "state": state,
                        "amount": data.get("amount"),
                        "currency": data.get("currency", "RUB"),
                        "extra": data.get("extra", ""),
                    }
                return {"ok": False, "is_paid": False, "error": str(data.get("errors"))}
    except Exception as e:
        return {"ok": False, "is_paid": False, "error": str(e)}

async def notify_admin_order(bot_obj: Bot, order_type: str, product_title: str, buyer, amount_str: str, method: str, status: str, extra: str = ""):
    """Мгновенное уведомление администратору о заказе на ID 7461353872"""
    buyer_label = f"@{buyer.username}" if getattr(buyer, "username", None) else html.escape(getattr(buyer, "first_name", "Клиент") or "Клиент")
    buyer_id = getattr(buyer, "id", "Неизвестен")
    
    text = (
        f"🔔 <b>[НОВЫЙ ЗАКАЗ] {order_type}</b>\n\n"
        f"📦 <b>Товар:</b> {product_title}\n"
        f"👤 <b>Покупатель:</b> {buyer_label} (ID: <code>{buyer_id}</code>)\n"
        f"💰 <b>Сумма:</b> <b>{amount_str}</b>\n"
        f"💳 <b>Оплата:</b> {method}\n"
        f"📊 <b>Статус:</b> {status}\n"
    )
    if extra:
        text += f"\nℹ️ <i>{extra}</i>"

    for aid in list(set([ADMIN_ID] + ADMIN_IDS)):
        try:
            await bot_obj.send_message(chat_id=aid, text=text, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Не удалось отправить уведомление админу {aid}: {e}")




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


# БОЕВЫЕ ЦЕНЫ (СОХРАНЕНЫ ДЛЯ БЫСТРОГО ВОЗВРАТА)
REAL_PRICES = {
    "prod_stars_50": {"amount": 78, "usdt": 0.89, "title": "50 Telegram Stars", "type": "stars", "quantity": 50},
    "prod_stars_100": {"amount": 156, "usdt": 1.78, "title": "100 Telegram Stars", "type": "stars", "quantity": 100},
    "prod_stars_150": {"amount": 234, "usdt": 2.68, "title": "150 Telegram Stars", "type": "stars", "quantity": 150},
    "prod_stars_250": {"amount": 390, "usdt": 4.47, "title": "250 Telegram Stars", "type": "stars", "quantity": 250},
    "prod_stars_500": {"amount": 780, "usdt": 8.94, "title": "500 Telegram Stars", "type": "stars", "quantity": 500},
    "prod_stars_1000": {"amount": 1560, "usdt": 17.89, "title": "1000 Telegram Stars", "type": "stars", "quantity": 1000},
    "prod_stars_2500": {"amount": 3900, "usdt": 44.72, "title": "2500 Telegram Stars", "type": "stars", "quantity": 2500},
    "prod_prem_3": {"amount": 1150, "usdt": 14.22, "title": "Telegram Premium (3 месяца)", "type": "premium", "months": 3},
    "prod_prem_6": {"amount": 1850, "usdt": 22.88, "title": "Telegram Premium (6 месяцев)", "type": "premium", "months": 6},
    "prod_prem_12": {"amount": 3300, "usdt": 40.80, "title": "Telegram Premium (12 месяцев)", "type": "premium", "months": 12},
    "prod_crypto_ton_1": {"amount": 110, "usdt": 1.36, "title": "1 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 1},
    "prod_crypto_ton_3": {"amount": 330, "usdt": 4.09, "title": "3 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 3},
    "prod_crypto_ton_5": {"amount": 550, "usdt": 6.82, "title": "5 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 5},
    "prod_crypto_ton_7": {"amount": 770, "usdt": 9.55, "title": "7 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 7},
    "prod_crypto_ton_10": {"amount": 1100, "usdt": 13.64, "title": "10 GRAM (TON)", "type": "crypto", "coin": "TON", "qty": 10},
    "prod_crypto_usdt_1": {"amount": 95, "usdt": 1, "stars": 78, "title": "1 USDT", "type": "crypto_native_stars", "coin": "USDT", "qty": 1},
    "prod_crypto_usdt_3": {"amount": 279, "usdt": 3, "stars": 234, "title": "3 USDT", "type": "crypto_native_stars", "coin": "USDT", "qty": 3},
    "prod_crypto_usdt_5": {"amount": 455, "usdt": 5, "stars": 385, "title": "5 USDT", "type": "crypto_native_stars", "coin": "USDT", "qty": 5},
    "prod_crypto_usdt_7": {"amount": 630, "usdt": 7, "stars": 532, "title": "7 USDT", "type": "crypto_native_stars", "coin": "USDT", "qty": 7},
    "prod_crypto_usdt_10": {"amount": 890, "usdt": 10, "stars": 750, "title": "10 USDT", "type": "crypto_native_stars", "coin": "USDT", "qty": 10},
}

# 🧪 ТЕСТОВЫЙ ПРАЙС-ЛИСТ (ВСЁ ПО 1 ₽ / 0.01 USDT ДЛЯ БЕЗОПАСНОЙ ПРОВЕРКИ)
PRICES = {
    "prod_stars_50": {"amount": 1, "usdt": 0.01, "title": "50 Telegram Stars (ТЕСТ 0.01$)", "type": "stars", "quantity": 50},
    "prod_stars_100": {"amount": 1, "usdt": 0.01, "title": "100 Telegram Stars (ТЕСТ 0.01$)", "type": "stars", "quantity": 100},
    "prod_stars_150": {"amount": 1, "usdt": 0.01, "title": "150 Telegram Stars (ТЕСТ 0.01$)", "type": "stars", "quantity": 150},
    "prod_stars_250": {"amount": 1, "usdt": 0.01, "title": "250 Telegram Stars (ТЕСТ 0.01$)", "type": "stars", "quantity": 250},
    "prod_stars_500": {"amount": 1, "usdt": 0.01, "title": "500 Telegram Stars (ТЕСТ 0.01$)", "type": "stars", "quantity": 500},
    "prod_stars_1000": {"amount": 1, "usdt": 0.01, "title": "1000 Telegram Stars (ТЕСТ 0.01$)", "type": "stars", "quantity": 1000},
    "prod_stars_2500": {"amount": 1, "usdt": 0.01, "title": "2500 Telegram Stars (ТЕСТ 0.01$)", "type": "stars", "quantity": 2500},
    "prod_prem_3": {"amount": 1, "usdt": 0.01, "title": "Telegram Premium 3 мес (ТЕСТ 0.01$)", "type": "premium", "months": 3},
    "prod_prem_6": {"amount": 1, "usdt": 0.01, "title": "Telegram Premium 6 мес (ТЕСТ 0.01$)", "type": "premium", "months": 6},
    "prod_prem_12": {"amount": 1, "usdt": 0.01, "title": "Telegram Premium 12 мес (ТЕСТ 0.01$)", "type": "premium", "months": 12},
    "prod_crypto_ton_1": {"amount": 1, "usdt": 0.01, "title": "1 GRAM (TON) (ТЕСТ 0.01$)", "type": "crypto", "coin": "TON", "qty": 1},
    "prod_crypto_ton_3": {"amount": 1, "usdt": 0.01, "title": "3 GRAM (TON) (ТЕСТ 0.01$)", "type": "crypto", "coin": "TON", "qty": 3},
    "prod_crypto_ton_5": {"amount": 1, "usdt": 0.01, "title": "5 GRAM (TON) (ТЕСТ 0.01$)", "type": "crypto", "coin": "TON", "qty": 5},
    "prod_crypto_ton_7": {"amount": 1, "usdt": 0.01, "title": "7 GRAM (TON) (ТЕСТ 0.01$)", "type": "crypto", "coin": "TON", "qty": 7},
    "prod_crypto_ton_10": {"amount": 1, "usdt": 0.01, "title": "10 GRAM (TON) (ТЕСТ 0.01$)", "type": "crypto", "coin": "TON", "qty": 10},
    "prod_crypto_usdt_1": {"amount": 1, "usdt": 0.01, "stars": 1, "title": "1 USDT (ТЕСТ 0.01$)", "type": "crypto_native_stars", "coin": "USDT", "qty": 1},
    "prod_crypto_usdt_3": {"amount": 1, "usdt": 0.01, "stars": 1, "title": "3 USDT (ТЕСТ 0.01$)", "type": "crypto_native_stars", "coin": "USDT", "qty": 3},
    "prod_crypto_usdt_5": {"amount": 1, "usdt": 0.01, "stars": 1, "title": "5 USDT (ТЕСТ 0.01$)", "type": "crypto_native_stars", "coin": "USDT", "qty": 5},
    "prod_crypto_usdt_7": {"amount": 1, "usdt": 0.01, "stars": 1, "title": "7 USDT (ТЕСТ 0.01$)", "type": "crypto_native_stars", "coin": "USDT", "qty": 7},
    "prod_crypto_usdt_10": {"amount": 1, "usdt": 0.01, "stars": 1, "title": "10 USDT (ТЕСТ 0.01$)", "type": "crypto_native_stars", "coin": "USDT", "qty": 10},
}


class WrongItemException(Exception):
  pass


class user_states(StatesGroup):
  waiting_for_support = State()


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
    event: CallbackQuery | Message, text: str, reply_markup=None
) -> None:
  msg = event.message if isinstance(event, CallbackQuery) else event
  if not msg:
    return

  is_photo = bool(getattr(msg, "photo", None) or getattr(msg, "caption", None) is not None)

  if is_photo:
    # Сообщение с фотографией (баннером) в Telegram редактируется исключительно через edit_caption
    try:
      await msg.edit_caption(
          caption=text[:1024],
          reply_markup=reply_markup,
          parse_mode="HTML",
      )
      return
    except Exception as e:
      err = str(e).lower()
      if "message is not modified" in err:
        return
      # При ошибке редактирования подписи (слишком длинный текст и т.д.) переходим к удалению и отправке
  else:
    # Обычное текстовое сообщение редактируется через edit_text
    try:
      await msg.edit_text(
          text,
          reply_markup=reply_markup,
          parse_mode="HTML",
      )
      return
    except Exception as e:
      err = str(e).lower()
      if "message is not modified" in err:
        return
      if "message to edit has no text" in err or "message is not a text" in err:
        try:
          await msg.edit_caption(
              caption=text[:1024],
              reply_markup=reply_markup,
              parse_mode="HTML",
          )
          return
        except Exception:
          pass

  # Надежный fallback: сначала отправляем новое сообщение, и только при успехе удаляем старое!
  new_msg = None
  try:
    new_msg = await msg.bot.send_message(
        chat_id=msg.chat.id,
        text=text,
        reply_markup=reply_markup,
        parse_mode="HTML",
    )
  except Exception as e:
    logger.warning("safe_edit send_message HTML error: %s", e)
    try:
      # Попытка без HTML parse_mode, если в тексте были неэкранированные символы
      new_msg = await msg.bot.send_message(
          chat_id=msg.chat.id,
          text=re.sub(r"<[^>]+>", "", text),
          reply_markup=reply_markup,
      )
    except Exception as e2:
      logger.error("safe_edit send_message plain text error: %s", e2)

  if new_msg:
    try:
      await msg.delete()
    except Exception:
      pass


BANNERS_FILE = "banners.json"

def load_banners() -> dict:
  banners = {}
  # 1. Из базы данных Neon PostgreSQL (вечное облако, не сбрасывается при деплоях Render!)
  try:
    db_banners = bot_db.get_all_banners()
    if db_banners:
      banners.update(db_banners)
  except Exception as e:
    logger.debug("bot_db.get_all_banners error: %s", e)

  # 2. Из локального файла banners.json
  if os.path.exists(BANNERS_FILE):
    try:
      with open(BANNERS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        if isinstance(data, dict):
          banners.update(data)
    except Exception:
      pass
  return banners

def save_banner_file_id(name: str, file_id: str):
  # 1. Сохраняем в постоянную базу данных Neon
  try:
    bot_db.set_banner(name, file_id)
  except Exception as e:
    logger.error("Не удалось сохранить banner в bot_db: %s", e)

  # 2. Дублируем в локальный файл banners.json
  banners = load_banners()
  banners[name] = file_id
  try:
    with open(BANNERS_FILE, "w", encoding="utf-8") as f:
      json.dump(banners, f, ensure_ascii=False, indent=2)
  except Exception as e:
    logger.error("Не удалось сохранить banner в banners.json: %s", e)

SECTION_PATTERNS = {
    "menu": ["menu", "меню", "161446"],
    "crypto": ["crypto", "крипт", "114039"],
    "stars": ["star", "звезд", "142345"],
    "orders": ["order", "заказ", "131026"],
    "profile": ["profile", "профил", "141012"],
    "reviews": ["review", "отзыв", "163600"],
    "referrals": ["referral", "ref", "рефер", "162856"],
    "support": ["support", "поддерж", "134353"],
    "other": ["other", "прочее", "141816"],
}

SECTION_NAMES_RU = {
    "menu": "🏠 Главное меню",
    "crypto": "🪙 Криптовалюта",
    "stars": "⭐ Звёзды & Premium",
    "orders": "📦 История заказов",
    "profile": "👤 Профиль",
    "reviews": "💬 Отзывы",
    "referrals": "👥 Рефералы",
    "support": "🛟 Поддержка",
    "other": "⚙️ Прочее",
}

def get_banner(name: str):
  """
  Ищет баннер:
  1. Telegram file_id из базы данных Neon PostgreSQL (вечное облачное хранилище)
  2. Telegram file_id из banners.json
  3. Локальный файл в images/, public/images/ или .
  4. Поиск по имени файла/таймстемпу с телефона
  """
  # 1. Проверяем базу данных
  try:
    db_file_id = bot_db.get_banner(name)
    if db_file_id:
      return db_file_id
  except Exception:
    pass

  # 2. Проверяем banners.json
  banners = load_banners()
  if name in banners and banners[name]:
    return banners[name]

  # 3. Проверяем точное имя на диске
  for folder in ["images", "public/images", "."]:
    for ext in [".png", ".jpg", ".jpeg"]:
      p = os.path.join(folder, f"{name}{ext}")
      if os.path.exists(p):
        try:
          return FSInputFile(p)
        except Exception:
          pass

  # 4. Проверяем совпадение по имени или таймстемпу телефона
  patterns = SECTION_PATTERNS.get(name, [name])
  for folder in ["images", "public/images", "."]:
    if os.path.exists(folder):
      try:
        for fname in os.listdir(folder):
          fname_low = fname.lower()
          for p in patterns:
            if p in fname_low and fname_low.endswith((".png", ".jpg", ".jpeg")):
              return FSInputFile(os.path.join(folder, fname))
      except Exception:
        pass

  return None


@rt.message(F.photo, F.caption.startswith(("/banner", "/setbanner")))
@rt.message(F.text.startswith(("/banner", "/setbanner")))
async def set_banner_handler(message: Message):
  text_content = (message.caption or message.text or "").strip()
  parts = text_content.split()

  user_id = message.from_user.id
  is_admin = (
      (user_id in ADMIN_IDS)
      or (user_id == ADMIN_ID)
      or (ADMIN_PASSWORD and len(parts) >= 3 and parts[2] == ADMIN_PASSWORD)
  )
  if not is_admin:
    return

  if len(parts) < 2:
    sections_list = "\n".join([f"• <code>/banner {k}</code> — {v}" for k, v in SECTION_NAMES_RU.items()])
    await message.answer(
        "🖼 <b>Установка баннеров разделов прямо из Telegram:</b>\n\n"
        "Отправьте фотографию в этот чат и в подписи (caption) укажите команду:\n"
        f"{sections_list}\n\n"
        "<i>Или ответьте (Reply) командой на любое ранее отправленное фото!</i>",
        parse_mode="HTML",
    )
    return

  raw_sec = parts[1].strip().lower()
  target_sec = None
  for sec_key, aliases in SECTION_PATTERNS.items():
    if raw_sec == sec_key or raw_sec in aliases:
      target_sec = sec_key
      break

  if not target_sec:
    await message.answer(
        f"❌ Неизвестный раздел: <code>{html.escape(raw_sec)}</code>.\n"
        f"Доступные разделы: <code>{', '.join(SECTION_NAMES_RU.keys())}</code>",
        parse_mode="HTML",
    )
    return

  photo_obj = None
  if message.photo:
    photo_obj = message.photo[-1]
  elif message.reply_to_message and message.reply_to_message.photo:
    photo_obj = message.reply_to_message.photo[-1]

  if not photo_obj:
    await message.answer(
        f"❌ Фотография не найдена!\n"
        f"Прикрепите картинку к сообщению с подписью <code>/banner {target_sec}</code> "
        f"или ответьте этой командой на нужное фото.",
        parse_mode="HTML",
    )
    return

  save_banner_file_id(target_sec, photo_obj.file_id)
  title = SECTION_NAMES_RU.get(target_sec, target_sec)
  await message.answer(
      f"🎉 <b>Баннер успешно сохранен в базу Neon!</b>\n\n"
      f"Раздел: <b>{title}</b> (<code>{target_sec}</code>)\n"
      f"Теперь этот баннер привязан к облачной базе данных PostgreSQL и никогда не исчезнет при перезапусках бота или деплоях Render! ✨",
      parse_mode="HTML",
  )


@rt.message(Command("banners"))
async def cmd_banners_status(message: Message):
  user_id = message.from_user.id
  is_admin = (user_id in ADMIN_IDS) or (user_id == ADMIN_ID)
  if not is_admin:
    return

  lines = ["<b>📊 Статус баннеров разделов в боте:</b>\n"]
  for key, title in SECTION_NAMES_RU.items():
    has_banner = bool(get_banner(key))
    status = "✅ Установлен" if has_banner else "❌ Не установлен"
    lines.append(f"• {title}: {status} (<code>/banner {key}</code>)")

  lines.append(
      "\n<i>💡 Отправьте любое фото с подписью <code>/banner &lt;раздел&gt;</code> или ответьте этой командой на фото, чтобы закрепить его навсегда в облачную базу данных!</i>"
  )
  await message.answer("\n".join(lines), parse_mode="HTML")


@rt.message(Command("broadcast"))
@rt.message(Command("send_all"))
async def cmd_broadcast(message: Message, command: CommandObject = None):
  """Рассылка сообщения всем пользователям бота (доступно только админу)"""
  user_id = message.from_user.id
  is_admin = (user_id in ADMIN_IDS) or (user_id == ADMIN_ID)
  if not is_admin:
    return

  text_to_send = (command.args or "").strip() if command else ""
  reply_msg = message.reply_to_message

  if not text_to_send and not reply_msg:
    await message.answer(
        "📢 <b>Рассылка сообщений всем пользователям бота:</b>\n\n"
        "<b>Как использовать:</b>\n"
        "• <code>/broadcast Текст вашей новости или акции</code>\n"
        "• Либо отправьте фото/картинку с текстом и ответьте на неё командой <code>/broadcast</code>",
        parse_mode="HTML",
    )
    return

  all_users = bot_db.get_all_user_ids()
  if not all_users:
    await message.answer("❌ В базе данных пока нет зарегистрированных пользователей.")
    return

  status_msg = await message.answer(
      f"⏳ <b>Начинаю рассылку для {len(all_users)} пользователей...</b>",
      parse_mode="HTML",
  )

  success_count = 0
  blocked_count = 0

  for uid in all_users:
    try:
      if reply_msg:
        await reply_msg.copy_to(chat_id=uid)
      else:
        await message.bot.send_message(chat_id=uid, text=text_to_send, parse_mode="HTML")
      success_count += 1
      await asyncio.sleep(0.04)  # Защита от лимитов Telegram (25 сообщ/сек)
    except Exception:
      blocked_count += 1

  await status_msg.edit_text(
      "✅ <b>Рассылка успешно завершена!</b>\n\n"
      f"• Всего в базе: <b>{len(all_users)}</b>\n"
      f"• Успешно доставлено: <b>{success_count}</b>\n"
      f"• Ошибок (бот заблокирован/удален): <b>{blocked_count}</b>",
      parse_mode="HTML",
  )


@rt.message(Command("setbalance"))
@rt.message(Command("set_balance"))
async def cmd_set_balance(message: Message, command: CommandObject = None):
  """Установка баланса пользователя (для администратора)"""
  user_id = message.from_user.id
  is_admin = (user_id in ADMIN_IDS) or (user_id == ADMIN_ID)
  if not is_admin:
    return

  args = (command.args or "").strip().split() if command else []
  if not args:
    await message.answer(
        "<b>⚙️ Управление балансом звёзд (Команда админа):</b>\n\n"
        "• <code>/setbalance 999</code> — установить себе 999 звёзд\n"
        "• <code>/setbalance 7461353872 999</code> — установить 999 звёзд конкретному ID\n\n"
        f"Ваш текущий баланс: <b>{get_balance(user_id)}</b> ⭐",
        parse_mode="HTML",
    )
    return

  if len(args) == 1:
    target_id = user_id
    try:
      amount = int(args[0])
    except ValueError:
      await message.answer("❌ Сумма должна быть числом!")
      return
  else:
    try:
      target_id = int(args[0])
      amount = int(args[1])
    except ValueError:
      await message.answer("❌ Формат: <code>/setbalance &lt;ID&gt; &lt;кол-во&gt;</code>")
      return

  bot_db.update_balance(target_id, amount)
  await message.answer(
      f"✅ <b>Баланс пользователя <code>{target_id}</code> успешно изменён!</b>\n\n"
      f"⭐ Новый баланс: <b>{amount}</b> звёзд.",
      parse_mode="HTML",
  )


@rt.message(Command("refund"))
@rt.message(Command("refund_stars"))
async def cmd_refund_stars(message: Message, command: CommandObject):
  """Возврат Telegram Stars через официальный API Telegram refundStarPayment"""
  user_id = message.from_user.id
  if user_id not in list(set([ADMIN_ID] + ADMIN_IDS)):
    return

  target_id = 6549054070
  raw_args = (command.args or "").strip()
  if raw_args:
    try:
      target_id = int(raw_args.split()[0])
    except ValueError:
      pass

  status_msg = await message.answer(
      f"🔍 <i>Поиск транзакций для возврата звёзд пользователю <code>{target_id}</code>...</i>",
      parse_mode="HTML",
  )

  try:
    star_txs = await message.bot.get_star_transactions()
    transactions = getattr(star_txs, "transactions", []) or []

    refunded = False
    for tx in transactions:
      source = getattr(tx, "source", None)
      source_user = getattr(source, "user", None)
      source_id = getattr(source_user, "id", None)

      if source_id == target_id:
        charge_id = tx.id
        await message.bot.refund_star_payment(
            user_id=target_id, telegram_payment_charge_id=charge_id
        )
        await status_msg.edit_text(
            f"✅ <b>Звёзды успешно возвращены пользователю <code>{target_id}</code>!</b>\n\n"
            f"⭐ Сумма: <b>{tx.amount} Stars</b>\n"
            f"🆔 ID транзакции: <code>{charge_id}</code>",
            parse_mode="HTML",
        )
        refunded = True
        break

    if not refunded:
      for tx in transactions:
        charge_id = tx.id
        try:
          await message.bot.refund_star_payment(
              user_id=target_id, telegram_payment_charge_id=charge_id
          )
          await status_msg.edit_text(
              f"✅ <b>Звёзды успешно возвращены пользователю <code>{target_id}</code>!</b>\n\n"
              f"⭐ Сумма: <b>{tx.amount} Stars</b>\n"
              f"🆔 ID транзакции: <code>{charge_id}</code>",
              parse_mode="HTML",
          )
          refunded = True
          break
        except Exception:
          continue

    if not refunded:
      await status_msg.edit_text(
          f"⚠️ <b>Транзакция не найдена.</b>\n\n"
          f"Проверено транзакций: {len(transactions)}.\n"
          f"Если у вас есть ID транзакции (charge_id), можете вызвать:\n"
          f"<code>/refund {target_id} &lt;charge_id&gt;</code>",
          parse_mode="HTML",
      )
  except Exception as e:
    logger.exception("Ошибка при выполнении refund:")
    await status_msg.edit_text(
        f"❌ <b>Ошибка возврата:</b> <code>{html.escape(str(e))}</code>",
        parse_mode="HTML",
    )



async def send_section(
    event: Message | CallbackQuery,
    banner_name: str,
    caption: str,
    reply_markup=None,
):
  """Отправляет раздел меню с фото баннером (или текстом, если фото не найдено)"""
  banner = get_banner(banner_name)

  if isinstance(event, CallbackQuery):
    msg = event.message
    chat_id = msg.chat.id if msg else event.from_user.id
    if banner:
      try:
        if msg:
          await msg.delete()
      except Exception:
        pass
      try:
        await event.bot.send_photo(
            chat_id=chat_id,
            photo=banner,
            caption=caption[:1024],
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        try:
          await event.answer()
        except Exception:
          pass
        return
      except Exception as e:
        logger.error(f"send_photo error in send_section for {banner_name}: {e}")
    await safe_edit(event, caption, reply_markup)
    try:
      await event.answer()
    except Exception:
      pass
  else:
    if banner:
      try:
        await event.answer_photo(
            photo=banner,
            caption=caption[:1024],
            reply_markup=reply_markup,
            parse_mode="HTML",
        )
        return
      except Exception as e:
        logger.error(f"answer_photo error in send_section for {banner_name}: {e}")
        try:
          await event.bot.send_photo(
              chat_id=event.chat.id,
              photo=banner,
              caption=caption[:1024],
              reply_markup=reply_markup,
              parse_mode="HTML",
          )
          return
        except Exception as e2:
          logger.error(f"send_photo fallback error for {banner_name}: {e2}")
    await event.answer(caption, reply_markup=reply_markup, parse_mode="HTML")



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
          [
              KeyboardButton(text="🛟 Поддержка"),
              KeyboardButton(text="⚙️ Прочее"),
          ],
      ],
      resize_keyboard=True,
      input_field_placeholder="Выберите пункт меню 👇",
  )


def back_keyboard():
  return InlineKeyboardMarkup(
      inline_keyboard=[[InlineKeyboardButton(text="🔙 Вернуться в меню", callback_data="back_to_menu")]]
  )


OFERTA_URL = "https://telegra.ph/Publichnaya-oferta-i-Politika-vozvrata-GumStars-11-05"
DOCS_URL = "https://telegra.ph/Dokumenty-i-Politika-GumStars-11-02"



def get_other_inline_keyboard():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="📑 Оферта", url=OFERTA_URL)],
          [InlineKeyboardButton(text="📄 Документы", url=DOCS_URL)],
          [InlineKeyboardButton(text="📬 Контакты", callback_data="show_contacts_only")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
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
      f"<b>👤 Получатель:</b> <code>{target_user}</code>\n"
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
      f"• Когда твой друг купит товар на сумму от 300 ₽, тебе на баланс автоматически зачислится <b>{REFERRAL_BONUS}</b> ⭐!\n\n"
      f"⚙️ Оферта, документы и контакты доступны в разделе <b>«⚙️ Прочее»</b>.\n\n"
      f"Выберите нужный раздел в меню ниже 👇"
  )
  await send_section(message, "menu", text, get_main_reply_keyboard())


@rt.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext):
  await state.clear()
  user_name = html.escape(callback.from_user.first_name or "друг")
  text = (
      f"<b>Добро пожаловать, {user_name}! Ты попал в GumStars — лучший бот по покупке криптовалюты и цифровых товаров ⭐</b>\n\n"
      f"⚙️ Оферта, документы и контакты доступны в разделе <b>«⚙️ Прочее»</b>.\n\n"
      f"Выберите нужный раздел в меню ниже 👇"
  )
  try:
    await callback.message.delete()
  except Exception:
    pass
  await send_section(callback, "menu", text, get_main_reply_keyboard())
  try:
    await callback.answer()
  except Exception:
    pass


@rt.message(F.text.in_({"🩷 Отзывы", "💬 Отзывы", "Отзывы"}))
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
          [InlineKeyboardButton(text="⭐ Перейти в канал с отзывами", url="https://t.me/GumNyam1")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  text = (
      "<b>💬 Отзывы и выполненные заказы!</b>\n\n"
      "Здесь вы можете ознакомиться с реальными отзывами наших клиентов и списком выполненных заказов ✨"
  )
  await send_section(message, "reviews", text, kb)


@rt.message(F.text.in_({"🪙 Криптовалюта", "Криптовалюта", "криптовалюта"}))
async def text_crypto_main(message: Message, state: FSMContext):
  await state.clear()
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="💲 USDT (Tether)", callback_data="crypto_coin_USDT")],
          [InlineKeyboardButton(text="💎 GRAM (TON)", callback_data="crypto_coin_TON")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await send_section(
      message,
      "crypto",
      "<b>🪙 Покупка криптовалюты</b>\n\nВыберите нужную монету:",
      keyboard,
  )


@rt.message(F.text.in_({"💛 ⭐ Купить звёзды", "⭐ Купить звёзды", "Купить звёзды"}))
async def text_stars(message: Message, state: FSMContext):
  await state.clear()
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="⭐ Купить Telegram Stars", callback_data="cat_stars")],
          [InlineKeyboardButton(text="💎 Купить Telegram Premium", callback_data="cat_premium")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await send_section(
      message,
      "stars",
      "<b>⭐ Магазин Telegram Stars & Premium</b>\n\nВыберите категорию товара:",
      kb,
  )


@rt.message(F.text.in_({"🩷 История заказов", "📦 История заказов", "История заказов"}))
async def text_orders(message: Message, state: FSMContext):
  await state.clear()
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await send_section(
      message,
      "orders",
      "<b>📦 История заказов</b>\n\nУ вас пока нет активных или завершенных заказов.",
      kb,
  )


@rt.message(F.text.in_({"🩷 Профиль", "👤 Профиль", "Профиль"}))
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
  await send_section(message, "profile", text, keyboard)


@rt.message(F.text.in_({"🩷 Рефералы", "👥 Рефералы", "Рефералы"}))
async def text_ref(message: Message, state: FSMContext):
  await state.clear()
  user_id = message.from_user.id
  balance = get_balance(user_id)
  referrals = get_referrals_count(user_id)
  bot_username = (await message.bot.get_me()).username
  ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"
  text = (
      f"<b>👥 РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
      f"Приглашай друзей и получай <b>{REFERRAL_BONUS}</b> ⭐ за каждого, кто купит товар на сумму от 300 ₽.\n\n"
      f"🔗 Ваша реферальная ссылка: <code>{ref_link}</code>\n"
      f"👥 Приглашено друзей: <b>{referrals}</b>\n"
      f"⭐ Доступно на балансе: <b>{balance}</b>"
  )
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="🏆 Лидерборд (Топ рефералов)", callback_data="ref_leaderboard")],
          [InlineKeyboardButton(text="📤 Вывести звёзды", callback_data="withdraw_stars")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await send_section(message, "referrals", text, keyboard)


@rt.message(F.text.in_({"🔴 Поддержка", "🛟 Поддержка", "Поддержка"}))
async def text_support(message: Message, state: FSMContext):
  await state.set_state(user_states.waiting_for_support)
  support_text = (
      "<b>🛟 Служба поддержки GumStars</b>\n\n"
      "Отправьте в чат вашу проблему или вопрос — мы ответим максимально быстро.\n\n"
      "📧 Официальная почта: <code>gumsupport@gmail.com</code>"
  )
  await send_section(message, "support", support_text, back_keyboard())


@rt.message(F.text.in_({"🔴 Прочее", "⚙️ Прочее", "Прочее", "прочее", "📄 Документы и оферта", "Документы", "Оферта", "Контакты"}))
@rt.message(Command("more"))
@rt.message(Command("other"))
@rt.message(Command("docs"))
@rt.message(Command("legal"))
async def text_other_section(message: Message, state: FSMContext):
  await state.clear()
  text = (
      "⚙️ <b>Раздел: Прочее</b>\n\n"
      "Выберите интересующий пункт ниже:"
  )
  await send_section(message, "other", text, get_other_inline_keyboard())


@rt.callback_query(F.data.in_({"open_other_menu", "doc_menu"}))
async def open_other_menu_callback(callback: CallbackQuery):
  text = (
      "⚙️ <b>Раздел: Прочее</b>\n\n"
      "Выберите интересующий пункт ниже:"
  )
  await safe_edit(callback, text, get_other_inline_keyboard())
  await callback.answer()


@rt.callback_query(F.data.in_({"show_contacts_only", "doc_contacts"}))
async def contacts_only_callback(callback: CallbackQuery):
  text = (
      "📬 <b>Контакты технической поддержки GumStars</b>\n\n"
      "По всем вопросам и обращениям обращайтесь на нашу официальную почту:\n\n"
      "📧 <b>Электронная почта:</b> <code>gumsupport@gmail.com</code>\n\n"
      "<i>(Нажмите на адрес почты выше, чтобы скопировать его)</i>"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="« Назад в Прочее", callback_data="open_other_menu")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await safe_edit(callback, text, kb)
  await callback.answer()


@rt.message(Command("contacts"))
async def cmd_contacts_only(message: Message):
  text = (
      "📬 <b>Контакты технической поддержки GumStars</b>\n\n"
      "По всем вопросам и обращениям обращайтесь на нашу официальную почту:\n\n"
      "📧 <b>Электронная почта:</b> <code>gumsupport@gmail.com</code>\n\n"
      "<i>(Нажмите на адрес почты выше, чтобы скопировать его)</i>"
  )
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="« Назад в Прочее", callback_data="open_other_menu")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await message.answer(text, reply_markup=kb, parse_mode="HTML")


@rt.message(Command("terms"))
@rt.message(Command("oferta"))
async def cmd_terms(message: Message):
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="📑 Открыть оферту (Telegra.ph)", url=OFERTA_URL)],
          [InlineKeyboardButton(text="« Назад в Прочее", callback_data="open_other_menu")],
      ]
  )
  await message.answer("📑 <b>Публичная оферта и Пользовательское соглашение:</b>", reply_markup=kb, parse_mode="HTML")


@rt.message(Command("privacy"))
@rt.message(Command("policy"))
@rt.message(Command("refund"))
async def cmd_docs_teleg(message: Message):
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="📄 Открыть документы (Telegra.ph)", url=DOCS_URL)],
          [InlineKeyboardButton(text="📑 Открыть оферту и возврат (Telegra.ph)", url=OFERTA_URL)],
          [InlineKeyboardButton(text="« Назад в Прочее", callback_data="open_other_menu")],
      ]
  )
  text = (
      "📑 <b>Политика возврата и гарантии сервиса:</b>\n\n"
      "• <b>3.1. Цифровые товары:</b>\n"
      "Цифровые товары надлежащего качества после успешной доставки возврату не подлежат.\n\n"
      "• <b>3.2. 100% Гарантия при сбое или недоставке:</b>\n"
      "В случае технического сбоя сети или задержки доставки покупателю гарантируется <b>повторная отправка товара либо полный возврат уплаченных средств</b> через поддержку (@bull9bull / gumsupport@gmail.com)."
  )
  await message.answer(text, reply_markup=kb, parse_mode="HTML")


@rt.callback_query(F.data.in_({"doc_terms", "doc_privacy", "doc_refund"}))
async def doc_teleg_callback(callback: CallbackQuery):
  url = OFERTA_URL if callback.data == "doc_terms" else DOCS_URL
  label = "📑 Открыть оферту" if callback.data == "doc_terms" else "📄 Открыть документы"
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text=label, url=url)],
          [InlineKeyboardButton(text="« Назад в Прочее", callback_data="open_other_menu")],
      ]
  )
  await safe_edit(callback, "📄 <b>Ознакомьтесь с официальным документом по ссылке ниже:</b>", kb)
  await callback.answer()

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
      f"Приглашай друзей и получай <b>{REFERRAL_BONUS}</b> ⭐ за каждого, кто купит товар на сумму от 300 ₽.\n\n"
      f"🔗 Ваша реферальная ссылка: <code>{ref_link}</code>\n"
      f"👥 Приглашено друзей: <b>{referrals}</b>\n"
      f"⭐ Доступно на балансе: <b>{balance}</b>"
  )
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="🏆 Лидерборд (Топ рефералов)", callback_data="ref_leaderboard")],
          [InlineKeyboardButton(text="📤 Вывести звёзды", callback_data="withdraw_stars")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await safe_edit(callback, text, keyboard)
  await callback.answer()


@rt.callback_query(F.data == "ref_leaderboard")
async def ref_leaderboard_callback(callback: CallbackQuery):
  user_id = callback.from_user.id
  top_users = bot_db.get_top_referrers(10)
  my_rank = bot_db.get_user_referral_rank(user_id)
  my_count = bot_db.count_referrals(user_id)

  medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
  lines = [
      "<b>🏆 ЛИДЕРБОРД РЕФЕРАЛОВ GUMSTARS</b>\n",
      "Топ участников, пригласивших больше всего друзей:\n",
  ]

  if not top_users:
    lines.append("<i>Пока никто не пригласил друзей. Будьте первым!</i>\n")
  else:
    for idx, (ref_id, cnt) in enumerate(top_users):
      medal = medals[idx] if idx < len(medals) else f"{idx+1}."
      s_id = str(ref_id)
      masked_id = s_id[:4] + "***" if len(s_id) >= 6 else s_id
      is_me = " (Вы)" if ref_id == user_id else ""
      lines.append(f"{medal} <code>ID {masked_id}</code>{is_me} — <b>{cnt}</b> приглашено")

  lines.append(f"\n👤 <b>Ваш результат:</b> позиция <b>#{my_rank}</b> (приглашено: <b>{my_count}</b>)")
  lines.append(f"🪙 <b>Ваш баланс звёзд:</b> <b>{get_balance(user_id)}</b> ⭐")
  lines.append(f"\n<i>Приглашайте друзей по ссылке и получайте по <b>{REFERRAL_BONUS} ⭐</b> за каждую покупку от 300 ₽!</i>")

  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="« Назад в Рефералы", callback_data="ref")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await safe_edit(callback, "\n".join(lines), kb)
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



async def deliver_stars_via_fragment(recipient: str, quantity: int) -> dict:
    """Автоматическая покупка и отправка звезд через Fragment API (v1 partner)"""
    if not FRAGMENT_API_KEY:
        logger.warning("FRAGMENT_API_KEY не задан в переменных окружения!")
        return {"ok": False, "error": "No API key"}

    url = f"{FRAGMENT_API_URL}/orders/star"
    headers = {
        "API-Key": FRAGMENT_API_KEY,
        "Idempotency-Key": str(uuid.uuid4()),
        "Content-Type": "application/json"
    }
    payload = {
        "recipient": recipient.lstrip("@"),
        "quantity": quantity,
        "wallet_type": "TON"
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload, timeout=25) as resp:
                data = await resp.json()
                if resp.status in (200, 201) and (data.get("ok") is not False) and not data.get("error"):
                    return {"ok": True, "data": data}
                logger.error(f"Fragment API order error ({resp.status}): {data}")
                return {"ok": False, "error": data.get("message") or data.get("error") or str(data)}
    except Exception as e:
        logger.error(f"Fragment API connection error: {e}")
        return {"ok": False, "error": str(e)}


@rt.callback_query(F.data.startswith("crypto_coin_"))
async def select_crypto_coin(callback: CallbackQuery, state: FSMContext):
  coin = callback.data.split("_")[2]
  # Единая надежная сеть TON (без дорогих комиссий TRC20 и Ethereum)
  network = "TON"
  await state.update_data(crypto_coin=coin, crypto_net=network)
  
  if coin == "TON":
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1 GRAM — 110 ₽ (1.36 USDT)", callback_data="prod_crypto_ton_1")],
            [InlineKeyboardButton(text="3 GRAM — 330 ₽ (4.09 USDT)", callback_data="prod_crypto_ton_3")],
            [InlineKeyboardButton(text="5 GRAM — 550 ₽ (6.82 USDT)", callback_data="prod_crypto_ton_5")],
            [InlineKeyboardButton(text="7 GRAM — 770 ₽ (9.55 USDT)", callback_data="prod_crypto_ton_7")],
            [InlineKeyboardButton(text="10 GRAM — 1100 ₽ (13.64 USDT)", callback_data="prod_crypto_ton_10")],
            [InlineKeyboardButton(text="✍️ Указать своё количество", callback_data="custom_crypto_amount")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")],
        ]
    )
  else:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1 USDT — 95 ₽ (78 ⭐)", callback_data="prod_crypto_usdt_1")],
            [InlineKeyboardButton(text="3 USDT — 279 ₽ (234 ⭐)", callback_data="prod_crypto_usdt_3")],
            [InlineKeyboardButton(text="5 USDT — 455 ₽ (385 ⭐)", callback_data="prod_crypto_usdt_5")],
            [InlineKeyboardButton(text="7 USDT — 630 ₽ (532 ⭐)", callback_data="prod_crypto_usdt_7")],
            [InlineKeyboardButton(text="10 USDT — 890 ₽ (750 ⭐)", callback_data="prod_crypto_usdt_10")],
            [InlineKeyboardButton(text="🔄 Обменять GRAM на USDT", callback_data="exchange_gram_to_stable")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")],
        ]
    )
  await safe_edit(callback, f"<b>📦 Выберите количество {coin} (Сеть: {network}):</b>", kb)
  await callback.answer()


@rt.callback_query(F.data == "crypto_back")
async def crypto_back(callback: CallbackQuery, state: FSMContext):
  await state.clear()
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="💲 USDT", callback_data="crypto_coin_USDT")],
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
            [InlineKeyboardButton(text="1 GRAM — 110 ₽ (1.36 USDT)", callback_data="prod_crypto_ton_1")],
            [InlineKeyboardButton(text="3 GRAM — 330 ₽ (4.09 USDT)", callback_data="prod_crypto_ton_3")],
            [InlineKeyboardButton(text="5 GRAM — 550 ₽ (6.82 USDT)", callback_data="prod_crypto_ton_5")],
            [InlineKeyboardButton(text="7 GRAM — 770 ₽ (9.55 USDT)", callback_data="prod_crypto_ton_7")],
            [InlineKeyboardButton(text="10 GRAM — 1100 ₽ (13.64 USDT)", callback_data="prod_crypto_ton_10")],
            [InlineKeyboardButton(text="✍️ Указать своё количество", callback_data="custom_crypto_amount")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="crypto_back")],
        ]
    )
  else:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="1 USDT — 95 ₽ (78 ⭐)", callback_data="prod_crypto_usdt_1")],
            [InlineKeyboardButton(text="3 USDT — 279 ₽ (234 ⭐)", callback_data="prod_crypto_usdt_3")],
            [InlineKeyboardButton(text="5 USDT — 455 ₽ (385 ⭐)", callback_data="prod_crypto_usdt_5")],
            [InlineKeyboardButton(text="7 USDT — 630 ₽ (532 ⭐)", callback_data="prod_crypto_usdt_7")],
            [InlineKeyboardButton(text="10 USDT — 890 ₽ (750 ⭐)", callback_data="prod_crypto_usdt_10")],
            [InlineKeyboardButton(text="🔄 Обменять GRAM на USDT", callback_data="exchange_gram_to_stable")],
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
  await safe_edit(callback, "<b>🔄 Обмен GRAM на USDT (Полуавтоматический режим)</b>\n\nНапишите в чат детальный запрос (например: <code>Хочу обменять 10 GRAM на USDT</code>):", kb)
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
async def process_crypto_product_selection(callback: CallbackQuery, state: FSMContext):
  prod_key = callback.data
  await state.update_data(crypto_product=prod_key)
  
  data = await state.get_data()
  product_info = PRICES.get(prod_key)

  if not product_info:
    await callback.answer("❌ Ошибка товара!", show_alert=True)
    return

  network = data.get("crypto_net", "TON")
  prod_type = product_info.get("type")
  target_user = f"@{callback.from_user.username}" if callback.from_user.username else str(callback.from_user.id)
  rub_price = product_info.get("amount", 0)
  usdt_amount = product_info.get("usdt", 0)

  # Для USDT оплата через Telegram Stars (звёздами)!
  is_stable = prod_key.startswith("prod_crypto_usdt")

  # Формируем счет CryptoBot (только для TON/GRAM)
  cryptobot_url = None
  cryptobot_id = None
  if not is_stable:
    try:
      invoice = await cryptopay.create_invoice(
          asset="USDT",
          amount=usdt_amount,
          description=f"Покупка {product_info['title']} ({network}) для {target_user} ({rub_price} ₽)",
          payload=f"{prod_key}:{target_user}:{network}",
      )
      cryptobot_url = invoice.bot_invoice_url
      cryptobot_id = invoice.invoice_id
    except Exception as e:
      logger.error(f"Ошибка создания счета CryptoBot (крипта): {e}")

  buttons = []

  # 1. Кнопка оплаты Telegram Stars (для USDT)
  if product_info.get("stars"):
    buttons.append([InlineKeyboardButton(text=f"⭐ Оплатить звёздами ({product_info['stars']} Stars)", callback_data=f"buystars_crypto_{prod_key}")])

  # 2. Кнопка CryptoBot (для TON/GRAM)
  if not is_stable and cryptobot_url:
    buttons.append([InlineKeyboardButton(text=f"💎 Оплатить через CryptoBot ({usdt_amount} USDT)", url=cryptobot_url)])
    buttons.append([InlineKeyboardButton(text="🔄 Проверить оплату CryptoBot", callback_data=f"checkcrypto_{cryptobot_id}")])

  buttons.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")])

  kb = InlineKeyboardMarkup(inline_keyboard=buttons)

  methods_text = (
      "• <b>Telegram Stars</b> — моментальный обмен за звёзды Telegram"
      if is_stable else
      "• <b>CryptoBot</b> — моментально в USDT/TON прямо в Telegram"
  )

  order_text = (
      "<b>✅ Заказ криптовалюты успешно сформирован!</b>\n\n"
      f"📦 Товар: <b>{product_info['title']}</b>\n"
      f"🌐 Сеть: <b>{network}</b>\n"
      f"👤 Получатель: <code>{target_user}</code>\n"
      f"💰 Стоимость: " + (f"<b>{product_info['stars']} ⭐</b>" if product_info.get("stars") else f"<b>{usdt_amount} USDT</b>") + "\n\n"
      "<b>Способ оплаты:</b>\n"
      f"{methods_text}"
  )

  await safe_edit(callback, order_text, kb)
  await state.clear()



@rt.callback_query(F.data.startswith("buystars_crypto_"))
async def buystars_crypto_callback(callback: CallbackQuery):
  prod_key = callback.data.replace("buystars_crypto_", "")
  product_info = PRICES.get(prod_key)
  if not product_info:
    await callback.answer("❌ Ошибка товара!", show_alert=True)
    return
  stars_amount = product_info.get("stars", 78)
  target_user = f"@{callback.from_user.username}" if callback.from_user.username else str(callback.from_user.id)
  prices = [LabeledPrice(label=product_info["title"], amount=stars_amount)]
  await callback.message.bot.send_invoice(
      chat_id=callback.message.chat.id,
      title=f"Покупка {product_info['title']}",
      description=f"Сеть: TON | Автоматическая выдача чека в боте",
      payload=f"native_star_crypto:{prod_key}:{target_user}:TON",
      currency="XTR",
      prices=prices,
  )
  await callback.answer()


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
          f"🌐 Сеть: <b>{network}</b>\n\n"
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
    try:
      if product_info.get("amount", 0) >= REFERRAL_MIN_AMOUNT:
        user_id = buyer.id
        user_record = bot_db.get_user(user_id)
        if user_record and len(user_record) > 1 and user_record[1]:
          referrer_id = user_record[1]
          ref_current_balance = (
              bot_db.get_user(referrer_id)[0]
              if bot_db.get_user(referrer_id)
              else 0
          )
          new_ref_balance = ref_current_balance + REFERRAL_BONUS
          bot_db.update_balance(referrer_id, new_ref_balance)
          await message.bot.send_message(
              referrer_id,
              f"🎉 <b>Реферальный бонус!</b>\n\n"
              f"Ваш приглашенный друг совершил покупку на сумму от 300 ₽!\n"
              f"Вам начислено <b>+{REFERRAL_BONUS} ⭐</b> на баланс.",
              parse_mode="HTML",
          )
    except Exception as e:
      logger.error(f"Ошибка начисления реферального бонуса: {e}")
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
      parts = payload.split(":")
      prod_key = parts[0] if len(parts) > 0 else "unknown"
      address = parts[1] if len(parts) > 1 else ""
      network = parts[2] if len(parts) > 2 else "TON"

      product_info = PRICES.get(prod_key, {"title": "Товар", "amount": 0})
      buyer = callback.from_user
      buyer_label = f"@{buyer.username}" if buyer.username else html.escape(buyer.first_name or f"ID {buyer.id}")

      # 1. Автоматическая доставка звёзд через Fragment API
      if prod_key.startswith("prod_stars_"):
        star_qty = product_info.get("quantity", 50)
        frag_res = await deliver_stars_via_fragment(recipient=address, quantity=star_qty)

        if frag_res.get("ok"):
          logger.info(f"Fragment API: {star_qty} звёзд успешно отправлено на {address}")
          await safe_edit(
              callback,
              "<b>✅ Оплата получена! Звёзды отправлены! ⭐</b>\n\n"
              f"📦 Товар: <b>{product_info['title']}</b>\n"
              f"🎯 Получатель: <code>{address}</code>\n\n"
              "⚡ <i>Звёзды автоматически отправлены на ваш аккаунт через Fragment API!</i>",
              InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]]),
          )
          admin_text = (
              "<b>⚡ [АВТО-ВЫДАЧА FRAGMENT] ЗВЁЗДЫ ДОСТАВЛЕНЫ!</b>\n\n"
              f"<b>📦 Товар:</b> {product_info['title']}\n"
              f"<b>👤 Покупатель:</b> {buyer_label} (ID: <code>{buyer.id}</code>)\n"
              f"<b>🎯 Получатель:</b> <code>{address}</code>\n"
              f"<b>💰 Оплачено:</b> <b>{product_info['amount']} ₽</b> ({invoice.amount} {invoice.asset})\n"
              f"<b>🆔 Инвойс CryptoBot:</b> <code>#{invoice.invoice_id}</code>\n"
              "<b>Статус:</b> ✅ Успешно отправлено через Fragment"
          )
        else:
          logger.error(f"Fragment API ошибка: {frag_res.get('error')}")
          await safe_edit(
              callback,
              "<b>✅ Оплата подтверждена!</b>\n\n"
              f"📦 Товар: <b>{product_info['title']}</b>\n"
              f"🎯 Получатель: <code>{address}</code>\n\n"
              "⏳ <i>Заказ принят в обработку. Звёзды поступят на ваш аккаунт в течение нескольких минут!</i>",
              InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]]),
          )
          admin_text = (
              "<b>⚠️ [ТРЕБУЕТСЯ РУЧНАЯ ВЫДАЧА ЗВЁЗД]</b>\n\n"
              f"<b>📦 Товар:</b> {product_info['title']}\n"
              f"<b>👤 Покупатель:</b> {buyer_label} (ID: <code>{buyer.id}</code>)\n"
              f"<b>🎯 Получатель:</b> <code>{address}</code>\n"
              f"<b>💰 Оплачено:</b> <b>{product_info['amount']} ₽</b> ({invoice.amount} {invoice.asset})\n"
              f"<b>🆔 Инвойс CryptoBot:</b> <code>#{invoice.invoice_id}</code>\n"
              f"<b>❌ Ошибка авто-выдачи Fragment:</b> <code>{frag_res.get('error')}</code>\n\n"
              f"👉 <i>Пожалуйста, зайдите во Fragment и отправьте {star_qty} звёзд получателю вручную:</i> <code>{address}</code>"
          )

      # 2. Telegram Premium (полуавтоматический режим)
      elif prod_key.startswith("prod_prem_"):
        await safe_edit(
            callback,
            "<b>✅ Оплата получена! Заказ передан в обработку 💎</b>\n\n"
            f"📦 Товар: <b>{product_info['title']}</b>\n"
            f"🎯 Получатель: <code>{address}</code>\n\n"
            "⏳ <i>Администратор активирует Telegram Premium на ваш аккаунт в течение 5–15 минут!</i>",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]]),
        )
        source_tip = "в самом Telegram (напрямую дешевле)" if prod_key == "prod_prem_3" else "через Fragment"
        admin_text = (
            "<b>💎 [НОВЫЙ ЗАКАЗ] TELEGRAM PREMIUM!</b>\n\n"
            f"<b>📦 Товар:</b> {product_info['title']}\n"
            f"<b>👤 Покупатель:</b> {buyer_label} (ID: <code>{buyer.id}</code>)\n"
            f"<b>🎯 Получатель:</b> <code>{address}</code>\n"
            f"<b>💰 Оплачено:</b> <b>{product_info['amount']} ₽</b> ({invoice.amount} {invoice.asset})\n"
            f"<b>🆔 Инвойс CryptoBot:</b> <code>#{invoice.invoice_id}</code>\n\n"
            f"👉 <i>Подарите подписку {source_tip} получателю:</i> <code>{address}</code>"
        )

      # 3. Криптовалюта (GRAM / TON / USDT)
        raw_coin = product_info.get("coin", "TON")
        target_asset = "TON" if raw_coin in ("TON", "GRAM") else raw_coin
        target_qty = product_info.get("qty", 1)

        # Пытаемся автоматически выдать чек через CryptoBot
        check_url = None
        last_check_err = None
        # Сначала пробуем выдать именной чек (pin_to_user_id), если не получается — обычный чек
        for pin_id in [buyer.id, None]:
          try:
            kwargs = {"asset": target_asset, "amount": target_qty}
            if pin_id:
              kwargs["pin_to_user_id"] = pin_id
            chk = await cryptopay.create_check(**kwargs)
            check_url = chk.bot_check_url
            break
          except Exception as e:
            last_check_err = str(e)
            logger.warning(f"Ошибка создания чека ({target_asset}, pin={pin_id}): {e}")

        if check_url:
          kb = InlineKeyboardMarkup(
              inline_keyboard=[
                  [InlineKeyboardButton(text=f"🎁 Забрать чек на {target_qty} {target_asset}", url=check_url)],
                  [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
              ]
          )
          await safe_edit(
              callback,
              "<b>✅ Оплата получена! Ваш чек готов:</b>\n\n"
              f"📦 Товар: <b>{product_info['title']}</b>\n"
              f"🌐 Сеть: <b>{network}</b>\n\n"
              f"👇 <b>Нажмите кнопку ниже, чтобы забрать чек в CryptoBot:</b>",
              kb,
          )
          admin_text = (
              "<b>⚡ [АВТО-ВЫДАЧА ЧЕКА] КРИПТОВАЛЮТА ВЫДАНА!</b>\n\n"
              f"<b>📦 Товар:</b> {product_info['title']} ({network})\n"
              f"<b>👤 Покупатель:</b> {buyer_label} (ID: <code>{buyer.id}</code>)\n"
              f"<b>💰 Оплачено:</b> <b>{product_info['amount']} ₽</b> ({invoice.amount} {invoice.asset})\n"
              f"<b>🆔 Инвойс CryptoBot:</b> <code>#{invoice.invoice_id}</code>\n"
              f"<b>🔗 Чек выдан автоматически:</b> {check_url}"
          )
        else:
          await safe_edit(
              callback,
              "<b>✅ Оплата получена!</b>\n\n"
              f"📦 Товар: <b>{product_info['title']}</b>\n"
              f"🌐 Сеть: <b>{network}</b>\n\n"
              "⏳ <i>Заказ принят! Чек будет выдан администратором вручную в ближайшее время.</i>",
              InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]]),
          )
          admin_text = (
              "<b>🪙 [НОВЫЙ ЗАКАЗ] КРИПТОВАЛЮТА (ТРЕБУЕТСЯ РУЧНАЯ ВЫДАЧА)!</b>\n\n"
              f"<b>📦 Товар:</b> {product_info['title']} ({network})\n"
              f"<b>👤 Покупатель:</b> {buyer_label} (ID: <code>{buyer.id}</code>)\n"
              f"<b>🎯 Получатель:</b> <code>{address}</code>\n"
              f"<b>💰 Оплачено:</b> <b>{product_info['amount']} ₽</b> ({invoice.amount} {invoice.asset})\n"
              f"<b>🆔 Инвойс CryptoBot:</b> <code>#{invoice.invoice_id}</code>\n"
              f"⚠️ <b>Причина ошибки авто-чека:</b> <code>{last_check_err}</code>\n"
              "👉 <i>Проверьте баланс приложения в @CryptoBot (Crypto Pay -> My Apps -> Баланс) и включены ли Checks в Security!</i>"
          )

      # Уведомление администратора
      try:
        await callback.bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
      except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")

      # Реферальный бонус (при покупке от 300 руб, временно от 1 руб для теста)
      try:
        if product_info.get("amount", 0) >= REFERRAL_MIN_AMOUNT:
          user_id = buyer.id
          user_record = bot_db.get_user(user_id)
          if user_record and len(user_record) > 1 and user_record[1]:
            referrer_id = user_record[1]
            ref_current_balance = (
                bot_db.get_user(referrer_id)[0]
                if bot_db.get_user(referrer_id)
                else 0
            )
            new_ref_balance = ref_current_balance + REFERRAL_BONUS
            bot_db.update_balance(referrer_id, new_ref_balance)
            await callback.bot.send_message(
                referrer_id,
                f"🎉 <b>Реферальный бонус!</b>\n\n"
                f"Ваш приглашенный друг совершил покупку на сумму от 300 ₽!\n"
                f"Вам начислено <b>+{REFERRAL_BONUS} ⭐</b> на баланс.",
                parse_mode="HTML",
            )
      except Exception as e:
        logger.error(f"Ошибка начисления реферального бонуса: {e}")

      # Публикация в канал отзывов
      await publish_to_reviews_channel(
          order_id=invoice.invoice_id,
          product_title=product_info["title"],
          buyer=buyer,
          target_user=address,
          amount_rub=product_info["amount"],
      )
    else:
      await callback.answer("⏳ Счет еще не оплачен. Оплатите счет в CryptoBot и нажмите кнопку снова.", show_alert=True)
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


@rt.callback_query(F.data == "menu_stars")
async def menu_stars_callback(callback: CallbackQuery, state: FSMContext):
  await state.clear()
  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="⭐ Купить Telegram Stars", callback_data="cat_stars")],
          [InlineKeyboardButton(text="💎 Купить Telegram Premium", callback_data="cat_premium")],
          [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
      ]
  )
  await safe_edit(
      callback,
      "<b>⭐ Магазин Telegram Stars & Premium</b>\n\nВыберите категорию товара:",
      kb,
  )
  await callback.answer()


@rt.callback_query(F.data.in_({"cat_stars", "cat_premium"}))
async def process_category(callback: CallbackQuery, state: FSMContext):
  category = "stars" if callback.data == "cat_stars" else "premium"
  await state.update_data(category=category)

  kb = InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="👤 Себе", callback_data="recipient_self")],
          [InlineKeyboardButton(text="Другу (по username)", callback_data="recipient_friend")],
          [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_stars")],
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
  await show_products(callback, state)
  await callback.answer()


@rt.callback_query(BuySteps.choosing_recipient, F.data == "recipient_friend")
async def recipient_friend(callback: CallbackQuery, state: FSMContext):
  kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="menu_stars")]])
  await safe_edit(
      callback,
      "<b>✏️ Отправьте в чат @username получателя (например, <code>@durov</code>):</b>",
      kb,
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


async def show_products(message: Message | CallbackQuery, state: FSMContext):
  data = await state.get_data()
  category = data.get("category")

  if category == "stars":
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⭐ 50 звезд — 78 ₽ (0.89 USDT)", callback_data="prod_stars_50")],
            [InlineKeyboardButton(text="⭐ 100 звезд — 156 ₽ (1.78 USDT)", callback_data="prod_stars_100")],
            [InlineKeyboardButton(text="⭐ 150 звезд — 234 ₽ (2.68 USDT)", callback_data="prod_stars_150")],
            [InlineKeyboardButton(text="⭐ 250 звезд — 390 ₽ (4.47 USDT)", callback_data="prod_stars_250")],
            [InlineKeyboardButton(text="⭐ 500 звезд — 780 ₽ (8.94 USDT)", callback_data="prod_stars_500")],
            [InlineKeyboardButton(text="⭐ 1000 звезд — 1560 ₽ (17.89 USDT)", callback_data="prod_stars_1000")],
            [InlineKeyboardButton(text="⭐ 2500 звезд — 3900 ₽ (44.72 USDT)", callback_data="prod_stars_2500")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_stars")],
        ]
    )
    text = "<b>⭐ Выберите пакет звезд:</b>"
  else:
    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="💎 3 месяца — 14.22 USDT (1150 ₽)", callback_data="prod_prem_3")],
            [InlineKeyboardButton(text="💎 6 месяцев — 22.88 USDT (1850 ₽)", callback_data="prod_prem_6")],
            [InlineKeyboardButton(text="💎 12 месяцев — 40.80 USDT (3300 ₽)", callback_data="prod_prem_12")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="menu_stars")],
        ]
    )
    text = "<b>💎 Выберите срок подписки TG Premium:</b>\n<i>(Оплата через CryptoBot в USDT)</i>"

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
  is_stars = product_info.get("type") == "stars"

  # 1. Формируем счет CryptoBot (USDT)
  cryptobot_url = None
  cryptobot_id = None
  try:
    invoice = await cryptopay.create_invoice(
        asset="USDT",
        amount=usdt_amount,
        description=f"Покупка {product_info['title']} для {target_user} ({rub_price} ₽)",
        payload=f"{product_key}:{target_user}",
    )
    cryptobot_url = invoice.bot_invoice_url
    cryptobot_id = invoice.invoice_id
  except Exception as e:
    logger.error(f"Ошибка создания счета CryptoBot: {e}")

  buttons = []

  # 2. СБП подключаем ТОЛЬКО для Telegram Stars! В Premium и Крипте СБП отключен.
  if is_stars:
    crystal_res = await create_crystalpay_invoice(
        amount=rub_price,
        description=f"{product_info['title']} для {target_user}",
        extra=f"{product_key}:{target_user}",
    )
    if crystal_res.get("ok") and crystal_res.get("url"):
      crystal_id = str(crystal_res.get("invoice_id"))
      CRYSTAL_PENDING_ORDERS[crystal_id] = {
          "prod_key": product_key,
          "target_user": target_user,
          "rub_price": rub_price,
      }
      buttons.append([InlineKeyboardButton(text=f"🇷🇺 Оплатить по СБП ({rub_price} ₽)", url=crystal_res["url"])])
      buttons.append([InlineKeyboardButton(text="🔄 Проверить оплату СБП", callback_data=f"chk_cryst_{crystal_id}")])

  # Кнопки CryptoBot
  if cryptobot_url:
    cb_text = f"💎 Оплатить криптой ({usdt_amount} USDT)" if is_stars else f"💎 Оплатить через CryptoBot ({usdt_amount} USDT)"
    buttons.append([InlineKeyboardButton(text=cb_text, url=cryptobot_url)])
    buttons.append([InlineKeyboardButton(text="🔄 Проверить оплату CryptoBot", callback_data=f"checkcrypto_{cryptobot_id}")])

  buttons.append([InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")])

  kb = InlineKeyboardMarkup(inline_keyboard=buttons)

  if is_stars:
    order_msg = (
        "<b>✅ Заказ успешно сформирован!</b>\n\n"
        f"📦 Товар: <b>{product_info['title']}</b>\n"
        f"👤 Получатель: <code>{target_user}</code>\n"
        f"💰 Стоимость: <b>{rub_price} ₽</b> (по СБП) или <b>{usdt_amount} USDT</b> (криптой)\n\n"
        "<b>Выберите способ оплаты ниже:</b>\n"
        "• <b>🇷🇺 СБП (Система быстрых платежей)</b> — моментально через любой банк РФ\n"
        "• <b>💎 CryptoBot</b> — оплата со скидкой в USDT прямо в Telegram"
    )
  else:
    order_msg = (
        "<b>✅ Заказ Telegram Premium сформирован!</b>\n\n"
        f"📦 Подписка: <b>{product_info['title']}</b>\n"
        f"👤 Получатель: <code>{target_user}</code>\n"
        f"💰 Стоимость: <b>{usdt_amount} USDT</b>\n\n"
        "<b>Способ оплаты:</b>\n"
        "• <b>💎 CryptoBot</b> — моментальная оплата в USDT или TON прямо в Telegram"
    )

  await safe_edit(callback, order_msg, kb)
  await state.clear()


@rt.callback_query(F.data.startswith("chk_cryst_"))
@rt.callback_query(F.data.startswith("checkcrystal_"))
async def check_crystalpay_payment_callback(callback: CallbackQuery):
  """Проверка статуса оплаты через кассу CrystalPAY (СБП)"""
  raw_data = callback.data
  if raw_data.startswith("chk_cryst_"):
    invoice_id = raw_data.replace("chk_cryst_", "")
    pending = CRYSTAL_PENDING_ORDERS.get(str(invoice_id), {})
    prod_key = pending.get("prod_key", "")
    target_user = pending.get("target_user", f"@{callback.from_user.username}" if callback.from_user.username else str(callback.from_user.id))
  else:
    parts = raw_data.split("_")
    invoice_id = parts[1]
    prod_key = parts[2] if len(parts) > 2 else ""
    target_user = parts[3] if len(parts) > 3 else f"@{callback.from_user.username}"

  status_data = await check_crystalpay_invoice(invoice_id)

  # Если prod_key не был найден в памяти, достаем его из extra, сохраненного в счете
  if (not prod_key or prod_key not in PRICES) and status_data.get("extra"):
    extra_parts = status_data["extra"].split(":")
    prod_key = extra_parts[0]
    if len(extra_parts) > 1 and not target_user:
      target_user = extra_parts[1]

  product_info = PRICES.get(prod_key, {"title": "Товар", "amount": 0, "usdt": 0})
  rub_price = product_info["amount"]

  if status_data.get("is_paid"):
    buyer = callback.from_user
    buyer_label = f"@{buyer.username}" if buyer.username else html.escape(buyer.first_name or f"ID {buyer.id}")

    # 1. Автоматическая доставка Stars через Fragment API
    if prod_key.startswith("prod_stars_"):
      star_qty = product_info.get("quantity", 50)
      frag_res = await deliver_stars_via_fragment(recipient=target_user, quantity=star_qty)

      if frag_res.get("ok"):
        logger.info(f"Fragment API: {star_qty} звёзд отправлено через СБП на {target_user}")
        await safe_edit(
            callback,
            "<b>✅ Оплата по СБП успешно получена! Звёзды отправлены! ⭐</b>\n\n"
            f"📦 Товар: <b>{product_info['title']}</b>\n"
            f"🎯 Получатель: <code>{target_user}</code>\n\n"
            "⚡ <i>Звёзды автоматически доставлены на ваш аккаунт через Fragment API!</i>",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]]),
        )
      else:
        await safe_edit(
            callback,
            "<b>✅ Оплата по СБП получена!</b>\n\n"
            f"📦 Товар: <b>{product_info['title']}</b>\n"
            f"🎯 Получатель: <code>{target_user}</code>\n\n"
            "⏳ <i>Заказ принят. Звёзды поступят на ваш аккаунт в течение нескольких минут!</i>",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]]),
        )
    # 2. Telegram Premium
    elif prod_key.startswith("prod_prem_"):
      await safe_edit(
          callback,
          "<b>✅ Оплата по СБП получена! Заказ передан в обработку 💎</b>\n\n"
          f"📦 Товар: <b>{product_info['title']}</b>\n"
          f"🎯 Получатель: <code>{target_user}</code>\n\n"
          "⏳ <i>Администратор активирует подписку Telegram Premium в течение 5–15 минут!</i>",
          InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]]),
      )
    # 3. Криптовалюта
    else:
      raw_coin = product_info.get("coin", "TON")
      target_asset = "TON" if raw_coin in ("TON", "GRAM") else raw_coin
      target_qty = product_info.get("qty", 1)

      check_url = None
      for pin_id in [buyer.id, None]:
        try:
          kwargs = {"asset": target_asset, "amount": target_qty}
          if pin_id:
            kwargs["pin_to_user_id"] = pin_id
          chk = await cryptopay.create_check(**kwargs)
          check_url = chk.bot_check_url
          break
        except Exception as e:
          logger.warning(f"Не удалось выдать чек СБП с ассетом {target_asset} (pin={pin_id}): {e}")

      if check_url:
        kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text=f"🎁 Забрать чек на {target_qty} {target_asset}", url=check_url)],
                [InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")],
            ]
        )
        await safe_edit(
            callback,
            "<b>✅ Оплата по СБП получена! Ваш чек готов:</b>\n\n"
            f"📦 Товар: <b>{product_info['title']}</b>\n\n"
            f"👇 <b>Нажмите кнопку ниже, чтобы забрать монеты в CryptoBot:</b>",
            kb,
        )
      else:
        await safe_edit(
            callback,
            "<b>✅ Оплата по СБП получена!</b>\n\n"
            f"📦 Товар: <b>{product_info['title']}</b>\n"
            f"🎯 Получатель: <code>{target_user}</code>\n\n"
            "⏳ <i>Заказ принят! Чек будет выдан администратором вручную в ближайшее время.</i>",
            InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🏠 В главное меню", callback_data="back_to_menu")]]),
        )

    # Уведомление администратора об успешной оплате
    await notify_admin_order(
        bot_obj=callback.bot,
        order_type="ОПЛАЧЕНО ПО СБП (CrystalPAY) 🎉",
        product_title=product_info["title"],
        buyer=buyer,
        amount_str=f"{rub_price} ₽",
        method="СБП (CrystalPAY)",
        status="✅ Оплата получена, заказ выполнен!",
        extra=f"Получатель: {target_user} | Инвойс: #{invoice_id}",
    )

    # Реферальный бонус (при покупке от 300 руб, временно от 1 руб для теста)
    try:
      if rub_price >= REFERRAL_MIN_AMOUNT:
        user_id = buyer.id
        user_record = bot_db.get_user(user_id)
        if user_record and len(user_record) > 1 and user_record[1]:
          referrer_id = user_record[1]
          ref_current_balance = (
              bot_db.get_user(referrer_id)[0]
              if bot_db.get_user(referrer_id)
              else 0
          )
          new_ref_balance = ref_current_balance + REFERRAL_BONUS
          bot_db.update_balance(referrer_id, new_ref_balance)
          await callback.bot.send_message(
              referrer_id,
              f"🎉 <b>Реферальный бонус!</b>\n\n"
              f"Ваш приглашенный друг совершил покупку на сумму от 300 ₽!\n"
              f"Вам начислено <b>+{REFERRAL_BONUS} ⭐</b> на баланс.",
              parse_mode="HTML",
          )
    except Exception as e:
      logger.error(f"Ошибка начисления реферального бонуса: {e}")

    # Публикация в канал отзывов
    await publish_to_reviews_channel(
        order_id=invoice_id,
        product_title=product_info["title"],
        buyer=buyer,
        target_user=target_user,
        amount_rub=rub_price,
    )
  else:
    await callback.answer(
        "⏳ Счет еще не оплачен. Оплатите через СБП в приложении вашего банка и нажмите кнопку снова.",
        show_alert=True,
    )

      
