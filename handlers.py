import csv
import hashlib
import html
import logging
import random
import re
import string

import aiofiles
from aiogram import F, Router, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputFile,
    LabeledPrice,
    Message,
    PreCheckoutQuery,
)

from config import PASSWORD, ADMIN_PASSWORD, ALLOWED_ADMIN_IDS, DATABASE
from db import BotDB
from Exceptions import WrongItemException
from States import user_states

try:
    import kb
except ImportError:
    kb = None
    logging.warning("Модуль kb не найден: меню продавца/покупателя работать не будут")

logger = logging.getLogger(__name__)

TEST_MODE = False
TEST_BALANCE = 999
MIN_WITHDRAW = 50
REFERRAL_BONUS = 50
REFERRAL_MIN_STARS = 350

ADMIN_IDS = {int(x) for x in ALLOWED_ADMIN_IDS}
ADMIN_ID = 7461353872

rt = Router()
bot_db = BotDB(DATABASE)

_test_balances: dict[int, int] = {}


class WithdrawState(StatesGroup):
    waiting_for_amount = State()


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
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise


def get_main_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🪙 Крипта", callback_data="crypto"),
                InlineKeyboardButton(text="⭐ Звёзды", callback_data="stars"),
            ],
            [
                InlineKeyboardButton(text="🛒 Купить NFT", callback_data="buy_nft"),
                InlineKeyboardButton(text="🔑 Аренда NFT", callback_data="rent_nft"),
            ],
            [
                InlineKeyboardButton(text="📦 Мои заказы", callback_data="my_orders"),
                InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
            ],
            [
                InlineKeyboardButton(text="💬 Отзывы", url="https://t.me/твоя_ссылка_на_отзывы"),
                InlineKeyboardButton(text="👥 Рефералы", callback_data="ref"),
            ],
            [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
        ]
    )


def back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")]
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
        if referrer_id and not bot_db.get_user(referrer_id):
            referrer_id = None
        bot_db.add_user(user_id, referrer_id)

        if referrer_id:
            try:
                await message.bot.send_message(
                    referrer_id,
                    f"👥 По вашей ссылке зарегистрировался новый пользователь: <b>{user_name}</b>!",
                    parse_mode="HTML",
                )
            except Exception:
                logger.exception("Не удалось уведомить реферера %s", referrer_id)

    balance = get_balance(user_id)
    bot_username = (await message.bot.get_me()).username
    ref_link = f"https://t.me/{bot_username}?start=ref_{user_id}"

    text = (
        f"👋 Салам Алейкум, <b>{user_name}</b>! Ты попал в <b>GumStars</b> — бот\n"
        f"по продаже криптовалюты, NFT и звёзд ⭐\n\n"
        f"⭐ Твой баланс звёзд: <b>{balance}</b> ⭐\n\n"
        f"👥 <b>Реферальная система:</b>\n"
        f"Приглашай друзей по своей ссылке:\n<code>{ref_link}</code>\n\n"
        f"🔥 Когда твой друг купит товар на сумму от 500 ₽, тебе на баланс "
        f"автоматически зачислится <b>+{REFERRAL_BONUS} ⭐</b>!\n\n"
        f"👇 Выберите нужный раздел в меню ниже 👇"
    )
    await message.answer(text, reply_markup=get_main_keyboard(), parse_mode="HTML")


@rt.callback_query(F.data.in_(["user_is_seller", "user_is_customer"]))
async def add_role(query: types.CallbackQuery, state: FSMContext):
    user_id = query.from_user.id
    if bot_db.get_role(user_id) != (None,):
        await query.answer(text="Вы уже выбрали роль. Сменить роль можно через главное меню")
    elif query.data == "user_is_seller":
        bot_db.insert_seller(user_id)
        await query.answer(text="Вы были успешно добавлены как продавец. Для продолжения введите команду /start")
    elif query.data == "user_is_customer":
        bot_db.insert_customer(user_id)
        await query.answer(text="Вы были успешно добавлены как покупатель. Для продолжения введите команду /start")


@rt.callback_query(F.data == "get_all_orders")
async def get_orders(query: types.CallbackQuery):
    bot_db.check_orders()
    csv_file = "current_orders.csv"
    try:
        async with aiofiles.open(csv_file, mode="rb") as file:
            input_file = types.FSInputFile("current_orders.csv")
            await query.message.answer_document(input_file)
    except Exception as e:
        print(f"Произошла ошибка при отправке файла: {e}")
        await query.message.answer(text="Произошла ошибка при отправке файла")
    await query.answer()


@rt.callback_query(F.data == "get_users")
async def get_users(query: types.CallbackQuery):
    data = bot_db.users_list()
    csv_file = "users_list.csv"
    try:
        async with aiofiles.open(csv_file, mode="rb") as file:
            input_file = types.FSInputFile("users_list.csv")
            await query.message.answer_document(input_file)
            await query.answer()
    except Exception as e:
        print(f"Произошла ошибка при отправке файла: {e}")
        await query.message.answer(text="Произошла ошибка при отправке файла")
        await query.answer()


@rt.callback_query(F.data == "get_this_seller_orders")
async def get_seller_orders(query: types.CallbackQuery):
    user_id = query.from_user.id
    bot_db.get_seller_orders(user_id)
    csv_file = f"order_list_for_this_seller_{user_id}.csv"
    try:
        async with aiofiles.open(csv_file, mode="rb") as file:
            input_file = types.FSInputFile(f"order_list_for_this_seller_{user_id}.csv")
            await query.message.answer_document(input_file)
            await query.answer()
    except Exception as e:
        print(f"Произошла ошибка при отправке файла: {e}")
        await query.message.answer(text="Произошла ошибка при отправке файла")
        await query.answer()


@rt.callback_query(F.data == "get_this_customer_orders")
async def get_customer_orders(query: types.CallbackQuery):
    user_id = query.from_user.id
    bot_db.get_customer_orders(user_id)
    csv_file = f"order_list_for_this_customer_{user_id}.csv"
    try:
        async with aiofiles.open(csv_file, mode="rb") as file:
            input_file = types.FSInputFile(f"order_list_for_this_customer_{user_id}.csv")
            await query.message.answer_document(input_file)
            await query.answer()
    except Exception as e:
        print(f"Произошла ошибка при отправке файла: {e}")
        await query.message.answer(text="Произошла ошибка при отправке файла")
        await query.answer()


@rt.callback_query(F.data == "create_item")
async def create_item(query: types.CallbackQuery, state: FSMContext):
    new_id = bot_db.create_new_item()
    await query.message.answer(text="Пожалуйста, укажите название для нового товара.")
    await state.set_state(user_states.waiting_for_name)


@rt.callback_query(F.data == "search_by_name")
async def prompt_search(query: types.CallbackQuery, state: FSMContext):
    await query.message.answer(
        "Введите название товара, который вы хотите найти:",
        reply_markup=types.ReplyKeyboardRemove(),
    )
    await state.set_state(user_states.waiting_for_product_search)


@rt.message(user_states.waiting_for_name)
async def add_name(message: Message, state: FSMContext):
    pattern = r"([А-Яа-яA-Za-z]+(?:\s[А-Яа-яA-Za-z0-9]+)*)"
    match = re.search(pattern, message.text)
    if match:
        cleaned_string = re.sub(r"[^a-zA-ZА-Яа-яЁё0-9 ]+", "", message.text).strip()
        cleaned_string = re.sub(r"\s+", " ", cleaned_string)
        if len(cleaned_string) >= 4:
            bot_db.insert_name(cleaned_string)
            await message.answer(text="Отлично! Теперь укажите описание к товару.")
            await state.set_state(user_states.waiting_for_description)
        else:
            await message.answer(text="Кажется, длина названия меньше 4 символов. Минимальная длина 4 символа")
    else:
        await message.answer(
            text="Похоже название товара не соответствует требованиям. Введите, пожалуйста корректное название"
        )


@rt.message(user_states.waiting_for_description)
async def add_description(message: Message, state: FSMContext):
    bot_db.insert_description(message.text)
    await message.answer(text="Теперь укажите цену товара.")
    await state.set_state(user_states.waiting_for_price)


@rt.message(user_states.waiting_for_product_search)
async def search_product(message: Message, state: FSMContext):
    product_name = message.text
    products = bot_db.get_product_by_name(product_name)
    for product in products:
        if product:
            response = (
                f"Наименование: {product[1]}\n"
                f"Описание: {product[2]}\n"
                f"Цена: {product[3]} руб.\n"
                f"Количество: {product[4]}"
            )
            if product[5]:
                await message.answer_photo(photo=product[5], caption=response)
            else:
                await message.answer(response)
        else:
            await message.answer("Товар не найден.")
    await state.clear()


@rt.message(user_states.waiting_for_price)
async def add_price(message: Message, state: FSMContext):
    if re.fullmatch(r"\d+", message.text or ""):
        bot_db.insert_price(message.text)
        await message.answer(text="Теперь укажите количество товара в наличии.")
        await state.set_state(user_states.waiting_for_amount)
    else:
        await message.answer(text="Введенное вами значение не является целым числом. Укажите целое число.")


@rt.message(user_states.waiting_for_amount)
async def add_amount(message: Message, state: FSMContext):
    if re.fullmatch(r"\d+", message.text or ""):
        bot_db.insert_amount(message.text)
        await message.answer(text="Теперь отправьте фото товара")
        await state.set_state(user_states.waiting_for_picture)
    else:
        await message.answer(text="Введенное вами значение не является целым числом. Укажите целое число.")


@rt.message(user_states.waiting_for_picture)
async def add_picture(message: Message, state: FSMContext):
    try:
        picture = message.photo[-1].file_id
        bot_db.insert_picture(picture)
        await message.answer(text="Новый товар был успешно создан", reply_markup=kb.seller_role_menu)
        await state.clear()
    except Exception:
        await message.answer(text="Это не фотография. Отправьте фотографию.")


@rt.callback_query(F.data == "plug")
async def plug(query: CallbackQuery):
    await query.answer(text="Данный функционал еще не реализован, однако мы уже работаем над ним")


@rt.callback_query(F.data == "switch_user_role_to_customer")
async def switch_user_role_to_customer(query: CallbackQuery):
    user_id = query.from_user.id
    bot_db.switch_user_role_to_customer(user_id)
    await query.message.answer("Вы авторизованы как покупатель.", reply_markup=kb.customer_role_menu)

@rt.callback_query(F.data == "show_all_items")
async def show_all_items(query: types.CallbackQuery, state: FSMContext):
    items = bot_db.show_all_item()
    for item in items:
        item_id = item[0]
        name = html.escape(str(item[1]))
        description = html.escape(str(item[2]))
        price = item[3]
        amount = item[4]
        picture = item[5]

        card = (
            f"<b>Id товара:</b> <code>{item_id}</code>\n"
            f"<b>Наименование:</b> {name}\n"
            f"<b>Описание:</b> {description}\n"
            f"<b>Цена в рублях:</b> {price}\n"
            f"<b>В наличии:</b> {amount}\n"
        )
        if picture is None:
            await query.message.answer(card, parse_mode="HTML")
        else:
            await query.message.answer_photo(photo=picture, caption=card, parse_mode="HTML")
        await query.answer()
    await query.message.answer("Пожалуйста, введите артикул товара, который вы хотите добавить в корзину.")
    await state.set_state(user_states.waiting_for_item_pick)


@rt.message(user_states.waiting_for_item_pick)
async def add_item_to_cart(message: Message, state: FSMContext):
    user_id = message.from_user.id
    item = message.text
    try:
        bot_db.add_item_to_cart(user_id, item)
        await message.answer(text="Товар был успешно добавлен в корзину")
        await state.clear()
    except WrongItemException:
        await message.answer(
            text="Похоже, вы указали id несуществующего товара. "
                 "Либо указанный товар уже есть в вашей корзине."
        )


@rt.callback_query(F.data == "enter_promocode")
async def enter_promocode(query: types.CallbackQuery, state: FSMContext):
    await query.message.answer("Введите промокод:")
    await state.set_state(user_states.waiting_for_promocode)


@rt.message(user_states.waiting_for_promocode)
async def process_promocode(message: Message, state: FSMContext):
    promocode = message.text.upper()
    if bot_db.check_promocode(promocode):
        await message.answer("Промокод принят!")
    else:
        await message.answer("Промокод не действителен.")
    await state.clear()


@rt.callback_query(F.data == "create_promocode")
async def prompt_discount_selection(query: types.CallbackQuery):
    await query.message.answer("Выберите процент скидки:", reply_markup=kb.seller_dicount_menu)


@rt.callback_query(F.data.startswith("discount_"))
async def create_promocode(query: types.CallbackQuery):
    discount_rate = int(query.data.split("_")[1])
    letters = "".join(random.choices(string.ascii_uppercase, k=3))
    numbers = "".join(random.choices(string.digits, k=5))
    suffix = "".join(random.choices(string.ascii_uppercase, k=2))
    promocode = f"{letters}{numbers}{suffix}"
    bot_db.insert_promocode(promocode, discount_rate)
    await query.message.answer(
        f"Создан промокод: {promocode} на {discount_rate}% скидку",
        reply_markup=kb.seller_role_menu,
    )


@rt.callback_query(F.data == "go_back")
async def go_back_seller(query: types.CallbackQuery):
    await query.message.delete()
    await query.message.answer("Вы в главном меню.", reply_markup=kb.seller_role_menu)


@rt.callback_query(F.data == "request_role_change_to_seller")
async def request_role_change_to_seller(query: types.CallbackQuery, state: FSMContext):
    await query.message.answer("Введите пароль:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(user_states.waiting_for_role_change_password)


@rt.message(user_states.waiting_for_role_change_password)
async def process_role_change_password(message: Message, state: FSMContext):
    if hash_password(message.text) == PASSWORD:
        user_id = message.from_user.id
        bot_db.switch_user_role_to_seller(user_id)
        await message.answer("Роль успешно изменена на продавца.", reply_markup=kb.seller_role_menu)
        await state.clear()
    else:
        await message.answer("Неверный пароль, повторите ввод", reply_markup=kb.back_button_menu)


@rt.callback_query(F.data == "go_back_customer")
async def go_back_customer(query: types.CallbackQuery):
    await query.message.delete()
    await query.message.answer("Вы в главном меню.", reply_markup=kb.customer_role_menu)


@rt.message(Command("admin"))
async def admin_login_request(msg: Message, state: FSMContext):
    user_id = msg.from_user.id
    if user_id in ADMIN_IDS:
        await msg.answer("Введите административный пароль:", reply_markup=kb.back_to_menu)
        await state.set_state(user_states.waiting_for_admin_password)
    else:
        return


@rt.message(user_states.waiting_for_admin_password)
async def process_admin_login(message: Message, state: FSMContext):
    if hash_password(message.text) == ADMIN_PASSWORD:
        user_id = message.from_user.id
        bot_db.switch_user_role_to_admin(user_id)
        await message.answer("Вы успешно вошли как администратор.")
        await start_handler(message, state)
        await state.clear()
    else:
        await message.answer("Неверный пароль. Повторите попытку.", reply_markup=kb.back_to_menu)
        await state.set_state(user_states.waiting_for_admin_password)


@rt.callback_query(F.data == "go_back_latest")
async def go_back_latest(query: types.CallbackQuery):
    await query.message.delete()
    await query.message.answer("Вы в главном меню.", reply_markup=kb.customer_role_menu)


@rt.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_name = html.escape(callback.from_user.first_name or "друг")
    text = (
        f"👋 Салам алейкум, <b>{user_name}</b>! Ты попал в <b>GumStars</b> — бот"
        " по продаже криптовалюты, NFT и звёзд ⭐\n\n💎 Быстро, безопасно и по"
        " выгодному курсу.\nВыберите нужный раздел в меню ниже 👇"
    )
    await safe_edit(callback, text, get_main_keyboard())
    await callback.answer()


@rt.callback_query(F.data == "crypto")
async def crypto_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="TON - 125.19 ₽", callback_data="buy_ton"),
                InlineKeyboardButton(text="BTC - 8 155 997.50 ₽", callback_data="buy_btc"),
            ],
            [
                InlineKeyboardButton(text="USDT - 100.57 ₽", callback_data="buy_usdt"),
                InlineKeyboardButton(text="SOL - 10 269.02 ₽", callback_data="buy_sol"),
            ],
            [InlineKeyboardButton(text="✏️ Указать свою монету", callback_data="custom_crypto")],
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
        ]
    )
    text = "🪙 <b>Криптовалюта</b>\n\nОплата в рублях (₽).\nВыберите монету для покупки:"
    await safe_edit(callback, text, keyboard)
    await callback.answer()


@rt.callback_query(F.data == "stars")
async def stars_menu(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="50 🌟 (75.00 ₽)", callback_data="star_50"),
                InlineKeyboardButton(text="100 🌟 (150.00 ₽)", callback_data="star_100"),
            ],
            [
                InlineKeyboardButton(text="250 🌟 (375.00 ₽)", callback_data="star_250"),
                InlineKeyboardButton(text="500 🌟 (750.00 ₽)", callback_data="star_500"),
            ],
            [InlineKeyboardButton(text="⚙️ Указать своё количество", callback_data="custom_stars")],
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
        ]
    )
    text = "⭐ <b>Покупка Telegram-звёзд</b>\n\nЦена: 1.50 ₽ за 1 звезду.\nВыберите количество звёзд:"
    await safe_edit(callback, text, keyboard)
    await callback.answer()


@rt.callback_query(F.data == "buy_nft")
async def buy_nft_menu(callback: CallbackQuery):
    text = "🛒 <b>Покупка NFT</b>\n\nВ данный раздел скоро будут добавлены доступные NFT для покупки."
    await safe_edit(callback, text, back_keyboard())
    await callback.answer()


@rt.callback_query(F.data == "rent_nft")
async def rent_nft_menu(callback: CallbackQuery):
    text = "🔑 <b>Аренда NFT</b>\n\nВ данный раздел скоро будут добавлены NFT для аренды."
    await safe_edit(callback, text, back_keyboard())
    await callback.answer()


@rt.callback_query(F.data == "profile")
async def profile_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_name = html.escape(callback.from_user.first_name or "друг")
    text = (
        f"👤 <b>ПРОФИЛЬ</b>\n\n"
        f"👤 Имя: {user_name}\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        "⭐ Куплено звёзд: 0\n"
        "📦 Заказов: 0\n"
        "💳 Сумма покупок: 0.00 ₽\n\n"
        "📦 <b>История покупок:</b>\n"
        "Покупок пока нет — оформите первую!"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="👥 Реферальная система", callback_data="ref")],
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
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
        f"Приглашайте друзей и получайте <b>{REFERRAL_BONUS} ⭐</b> за каждого, "
        f"кто купит товар на сумму от 500 ₽.\n\n"
        f"🔗 <b>Ваша ссылка:</b>\n<code>{ref_link}</code>\n\n"
        f"👥 Перешло по ссылке: <b>{referrals}</b>\n"
        f"💰 Доступно на балансе: <b>{balance}</b> ⭐\n\n"
        f"Вы можете вывести накопленные звёзды в любой момент."
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📤 Вывести звёзды", callback_data="withdraw_stars")],
            [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")],
        ]
    )
    await safe_edit(callback, text, keyboard)
    await callback.answer()


@rt.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery, state: FSMContext):
    await safe_edit(
        callback,
        "<b>💬 Поддержка</b>\n\n"
        "Напишите вашу проблему или вопрос — мы постараемся ответить как можно скорее.\n"
        "При необходимости приложите фото или файл.",
        back_keyboard(),
    )
    await state.set_state(user_states.waiting_for_support)
    await callback.answer()


@rt.message(user_states.waiting_for_support)
async def process_support_message(message: Message, state: FSMContext, bot):
    user_id = message.from_user.id
    user_name = html.escape(message.from_user.first_name or "")
    username = message.from_user.username or "нет юзернейма"
    body = html.escape(message.text or message.caption or "[вложение]")

    admin_text = (
        f"📩 <b>Новое обращение в поддержку!</b>\n\n"
        f"👤 От: {user_name} (@{username})\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"💬 <b>Сообщение:</b>\n{body}"
    )

    try:
        await bot.send_message(ADMIN_ID, admin_text, parse_mode="HTML")
        if not message.text:
            await message.copy_to(ADMIN_ID)
    except Exception:
        logger.exception("Не удалось отправить обращение в поддержку админу")
    await message.answer("✅ Ваше сообщение успешно отправлено в поддержку! Ожидайте ответа.")
    await state.clear()


@rt.callback_query(F.data == "buy_stars_example")
async def send_stars_invoice(callback: CallbackQuery):
    await callback.message.answer_invoice(
        title="Покупка Telegram Stars",
        description="Тестовая оплата звёздами внутри бота",
        prices=[LabeledPrice(label="Звёзды Telegram", amount=1)],
        provider_token="",
        currency="XTR",
        payload="payload_buy_stars_1",
    )
    await callback.answer()


@rt.pre_checkout_query()
async def process_pre_checkout(pre_checkout_query: PreCheckoutQuery):
    await pre_checkout_query.answer(ok=True)


@rt.message(F.successful_payment)
async def process_successful_payment(message: Message):
    user_id = message.from_user.id
    payment_info = message.successful_payment
    stars_amount = payment_info.total_amount

    await message.answer(
        f"🎉 <b>Оплата прошла успешно!</b>\n\n"
        f"Вы успешно приобрели пакет на <b>{stars_amount} ⭐</b>. Спасибо за покупку!",
        parse_mode="HTML",
    )

    if stars_amount >= REFERRAL_MIN_STARS:
        user_data = bot_db.get_user(user_id)
        if user_data:
            referrer_id = user_data[1] if len(user_data) > 1 else None
            if referrer_id and not bot_db.has_received_bonus_for(user_id):
                bot_db.mark_purchase_bonused(user_id)
                add_to_balance(referrer_id, REFERRAL_BONUS)

                try:
                    await message.bot.send_message(
                        referrer_id,
                        f"🎉 <b>Твой друг совершил покупку на сумму от 500 ₽!</b>\n\n"
                        f"Тебе начислено бонусное вознаграждение: <b>+{REFERRAL_BONUS} ⭐</b> на баланс!",
                        parse_mode="HTML",
                    )
                except Exception:
                    logger.exception("Не удалось уведомить реферера %s о бонусе", referrer_id)


@rt.callback_query(F.data == "withdraw_stars")
async def withdraw_start(callback: CallbackQuery, state: FSMContext):
    balance = get_balance(callback.from_user.id)
    await state.set_state(WithdrawState.waiting_for_amount)

    text = (
        f"📤 <b>ВЫВОД ЗВЁЗД</b>\n\n"
        f"⭐ На вашем балансе: <b>{balance}</b>\n"
        f"Минимум для вывода: <b>{MIN_WITHDRAW}</b>\n\n"
        f"✍️ Напишите в чат число — сколько звёзд вы хотите вывести:"
    )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="❌ Отмена", callback_data="ref")]]
    )
    await safe_edit(callback, text, keyboard)
    await callback.answer()


@rt.message(WithdrawState.waiting_for_amount, F.text)
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
        await message.answer(
            f"❌ Минимальная сумма для вывода: {MIN_WITHDRAW} ⭐. Введите сумму побольше:"
        )
        return
    if amount > balance:
        await message.answer(
            f"❌ Недостаточно звёзд. Доступно: {balance} ⭐. Введите меньшую сумму:"
        )
        return

    new_balance = balance - amount
    set_balance(user_id, new_balance)
    await state.clear()

    await message.answer(
        f"✅ <b>Запрос на вывод {amount} ⭐ успешно создан!</b>\n\n"
        f"⏳ Ожидайте зачисления звёзд на ваш аккаунт. Оставшийся баланс: {new_balance} ⭐",
        parse_mode="HTML",
    )

    user_label = f"@{user.username}" if user.username else html.escape(user.first_name or "без имени")
    try:
        await message.bot.send_message(
            ADMIN_ID,
            f"🔔 <b>Новая заявка на вывод звёзд!</b>\n\n"
            f"👤 Пользователь: {user_label} (ID: <code>{user_id}</code>)\n"
            f"💰 Сумма к выводу: <b>{amount} ⭐</b>",
            parse_mode="HTML",
        )
    except Exception:
        logger.exception("Не удалось отправить уведомление админу (ID=%s)", ADMIN_ID)


@rt.message(WithdrawState.waiting_for_amount)
async def withdraw_amount_not_text(message: Message):
    await message.answer("❌ Отправьте сумму числом в текстовом сообщении.")
