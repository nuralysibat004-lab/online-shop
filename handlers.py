from aiogram import F, Router, types
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InputFile, InlineKeyboardMarkup, InlineKeyboardButton
# import kb
# import text
import csv
from db import BotDB
import aiofiles
from States import user_states
from aiogram.fsm.context import FSMContext
import re
import asyncio
from Exceptions import WrongItemException
import random
import string
import hashlib
import os
from config import PASSWORD, ADMIN_PASSWORD, ALLOWED_ADMIN_IDS, DATABASE


# PASSWORD = os.getenv('PASSWORD')
# ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
# DATABASE = os.getenv('DATABASE')



rt = Router()
bot_db = BotDB(DATABASE)

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()



@rt.message(Command("start"))
async def start_handler(message: Message, state: FSMContext):
  await state.clear()
  user_name = message.from_user.first_name
  text = (
      f"👋 Салам алейкум, <b>{user_name}</b>! Ты попал в <b>GumStars</b> — бот"
      " по продаже криптовалюты, NFT и звёзд 🌟\n\n💎 Быстро, безопасно и по"
      " выгодному курсу.\nВыберите нужный раздел в меню ниже 👇"
  )
  await message.answer(
      text, reply_markup=get_main_keyboard(), parse_mode="HTML"
  )

@rt.callback_query(F.data.in_(["user_is_seller","user_is_customer"]))
async def add_role(query: types.CallbackQuery, state: FSMContext):
    user_id = query.from_user.id
    # bot_db = BotDB(DATABASE)
    if bot_db.get_role(user_id) != (None,):
        await query.answer(text = "Вы уже выбрали роль. Сменить роль можно через главное меню")
    elif F.data == "user_is_seller":
        bot_db.insert_seller(user_id)
        await query.answer(text=f"Вы были успешно добавлены как продавец. Для продолжения введите команду /start")
    elif F.data == "user_is_customer":
        bot_db.insert_customer(user_id)
        await query.answer(text=f"Вы были успешно добавлены как покупатель. Для продолжения введите команду /start")

@rt.callback_query(F.data == "get_all_orders")
async def get_orders(query: types.CallbackQuery):
    bot_db.check_orders()
    csv_file = 'current_orders.csv'

    try:
        async with aiofiles.open(csv_file, mode='rb') as file:
            input_file = types.FSInputFile('current_orders.csv')
            await query.message.answer_document(input_file)
    except Exception as e:
        print(f"Произошла ошибка при отправке файла: {e}")
        await query.message.answer(text="Произошла ошибка при отправке файла")
        await query.answer()

@rt.callback_query(F.data == "get_users")
async def get_users(query: types.CallbackQuery):
    ##
    data = bot_db.users_list()

    csv_file = 'users_list.csv'

    try:
        async with aiofiles.open(csv_file, mode='rb') as file:
            input_file = types.FSInputFile('users_list.csv')
            await query.message.answer_document(input_file)
            await query.answer()
    except Exception as e:
        print(f"Произошла ошибка при отправке файла: {e}")
        await query.message.answer(text="Произошла ошибка при отправке файла")
        await query.answer()


    
@rt.callback_query(F.data == "create_item")
async def create_item(query:types.CallbackQuery, state:FSMContext):
    #Инициализация создания новой карточки товара#
    new_id = bot_db.create_new_item()
    await query.message.answer(text="Пожалуйста, укажите название для нового товара.")
    await state.set_state(user_states.waiting_for_name)  # Переводим стейт в ожидание названия

@rt.callback_query(F.data == "search_by_name")
async def prompt_search(query: types.CallbackQuery, state: FSMContext):  # Make sure FSMContext is passed here
    await query.message.answer("Введите название товара, который вы хотите найти:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(user_states.waiting_for_product_search)  # Correctly set state 

@rt.message(user_states.waiting_for_name)
async def add_name(message: Message, state: FSMContext):
    #Очищаем полученную строку от спец.символов, двойные пробелы заменяем на одинарные
    pattern = r"([А-Яа-яA-Za-z]+(?:\s[А-Яа-яA-Za-z0-9]+)*)"
    match = re.search(pattern,message.text)
    if match:
        cleaned_string = re.sub(r'[^a-zA-ZА-Яа-я0-9 ]+', '', message.text).strip()
        cleaned_string = re.sub(r'\s+', ' ', cleaned_string)
        if len(cleaned_string)>=4: #Проверка на длину уже очищенной строки
            bot_db.insert_name(cleaned_string)
            await message.answer(text=f"Отлично! Теперь укажите описание к товару.")
            await state.set_state(user_states.waiting_for_description)
        else:
            await message.answer(text = "Кажется, длина названия меньше 4 символов. Минимальная длина 4 символа")
    else:
        await message.answer(text = "Похоже название товара не соответствует требованиям. Введите, пожалуйста корректное название.")

@rt.message(user_states.waiting_for_description)
async def add_description(message: Message, state: FSMContext):
    bot_db.insert_description(message.text)
    await message.answer(text=f"Теперь укажите цену товара.")
    await state.set_state(user_states.waiting_for_price)

@rt.message(user_states.waiting_for_product_search)
async def search_product(message: Message, state: FSMContext):
    product_name = message.text
    products = bot_db.get_product_by_name(product_name)
    print(products)
    for product in products:
        if product:
            response = f"Наименование: {product[1]}\nОписание: {product[2]}\nЦена: {product[3]} руб.\nКоличество: {product[4]}"
            if product[5]:
                await message.answer_photo(photo=product[5], caption=response)
            else:
                await message.answer(response)
        else:
            await message.answer("Товар не найден.")
    await state.clear()

@rt.message(user_states.waiting_for_price)
async def add_price(message: Message, state: FSMContext):
    pattern = r"^\d+$"

    if re.match(pattern, message.text):
        bot_db.insert_price(message.text)
        await message.answer(text="Теперь укажите количество товара в наличии.")
        await state.set_state(user_states.waiting_for_amount)
    else:
        await message.answer(text = "Введенное вами значение не является целым числом. Укажите целое число.")

@rt.message(user_states.waiting_for_amount)
async def add_amount(message: Message, state: FSMContext):
    pattern = r"^\d+$"
    if re.match(pattern, message.text):

        bot_db.insert_amount(message.text)
        await message.answer(text="Теперь отправьте фото товара")
        await state.set_state(user_states.waiting_for_picture)
    else:
        await message.answer(text = "Введенное вами значение не является целым числом. Укажите целое число.")

@rt.message(user_states.waiting_for_picture)
async def add_picture(message:Message, state: FSMContext):
    try:
        picture = message.photo[-1].file_id
        bot_db.insert_picture(picture)
        await message.answer(text= "Новый товар был успешно создан", reply_markup= kb.seller_role_menu)
        await state.clear()
    except:
        await message.answer(text = "Это не фотография. Отправьте фотографию.")

@rt.callback_query(F.data == "plug")
async def plug(query:CallbackQuery):
    await query.answer(text = "Данный функционал еще не реализован, однако мы уже работаем над ним")

@rt.callback_query(F.data == "switch_user_role_to_customer")
async def switch_user_role_to_customer(query:CallbackQuery):
    user_id = query.from_user.id
    bot_db.switch_user_role_to_customer(user_id)
    # await query.answer(text = f"Вы успешно сменили роль на покупателя. Чтобы открыть новое меню, введите команду /start")
    await query.message.answer("Вы авторизованы как покупатель.", reply_markup=kb.customer_role_menu)

@rt.callback_query(F.data == "get_this_seller_orders")
async def get_seller_orders(query: types.CallbackQuery):
    user_id = query.from_user.id
    bot_db.get_seller_orders(user_id)
    csv_file = f"order_list_for_this_seller_{user_id}.csv"

    try:
        async with aiofiles.open(csv_file, mode='rb') as file:
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
        async with aiofiles.open(csv_file, mode='rb') as file:
            input_file = types.FSInputFile(f"order_list_for_this_customer_{user_id}.csv")
            await query.message.answer_document(input_file)
            await query.answer()
    except Exception as e:
        print(f"Произошла ошибка при отправке файла: {e}")
        await query.message.answer(text="Произошла ошибка при отправке файла")
        await query.answer()

@rt.callback_query(F.data == "show_all_items")
async def show_all_items(query: types.CallbackQuery, state:FSMContext):
    items = bot_db.show_all_item()
    for item in items:
        id = item[0]
        Name = item[1]
        Description = item[2]
        Price = item[3]
        Amount = item[4]
        picture = item[5]
        if picture == None:

            Card = str(
                f'Id товара: {id}\n'
                f'Наименование: {Name}\n'
                f'Описание: {Description}\n'
                f'Цена в рублях: {Price}\n'
                f'В наличии: {Amount}\n'
            )
            await query.message.answer(Card)
            await query.answer()
        else:
            Card = str(
                f"{'<b>'}Id товара:{'</b>'} {'<code>'}{id}{'</code>'}\n"
                f"{'<b>'}Наименование:{'</b>'} {Name}\n"
                f"{'<b>'}Описание:{'</b>'} {Description}\n"
                f"{'<b>'}Цена в рублях:{'</b>'} {Price}\n"
                f"{'<b>'}В наличии:{'</b>'} {Amount}\n"
            )
            await query.message.answer_photo(photo=picture, caption = Card, parse_mode="HTML")
            await query.answer()
    await query.message.answer("Пожалуйста, введите артикул товара, который вы хотите добавить в корзину.")
    await state.set_state(user_states.waiting_for_item_pick)
    
@rt.message(user_states.waiting_for_item_pick)
async def add_item_to_cart(message: Message, state: FSMContext):
    user_id = message.from_user.id
    item = message.text
    try:
        bot_db.add_item_to_cart(user_id,item)
        await message.answer(text = "Товар был успешно добавлен в корзину")
        await state.clear()
    except (WrongItemException):
        await message.answer(text = "Похоже, вы указали id несуществующего товара. Либо указанный товар уже есть в вашей корзине.")

@rt.callback_query(F.data == "enter_promocode")
async def enter_promocode(query: types.CallbackQuery, state: FSMContext):
    await query.message.answer("Введите промокод:")
    await state.set_state(user_states.waiting_for_promocode)

@rt.message(user_states.waiting_for_promocode)
async def process_promocode(message: Message, state: FSMContext):
    promocode = message.text.upper()
    if bot_db.check_promocode(promocode):
        await message.answer("Промокод принят!")
        # Действия при успешной проверке промокода
    else:
        await message.answer("Промокод не действителен.")
    await state.clear()


@rt.callback_query(F.data == "create_promocode")
async def prompt_discount_selection(query: types.CallbackQuery):
    # Предложение выбрать процент скидки
    await query.message.answer("Выберите процент скидки:", reply_markup=kb.seller_dicount_menu)

@rt.callback_query(F.data.startswith("discount_"))
async def create_promocode(query: types.CallbackQuery):
    discount_rate = int(query.data.split("_")[1])
    # Генерация промокода, как описано ранее
    letters = ''.join(random.choices(string.ascii_uppercase, k=3))
    numbers = ''.join(random.choices(string.digits, k=5))
    suffix = ''.join(random.choices(string.ascii_uppercase, k=2))
    promocode = f"{letters}{numbers}{suffix}"
    
    # Сохранение в базу данных с указанием скидки
    bot_db.insert_promocode(promocode, discount_rate)
    
    # Отправка сообщения с промокодом
    await query.message.answer(f"Создан промокод: {promocode} на {discount_rate}% скидку", reply_markup=kb.seller_role_menu)

@rt.callback_query(F.data == "go_back")
async def go_back(query: types.CallbackQuery):
    # Удаляем сообщение с выбором скидки и возвращаемся в меню
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
    if user_id in ALLOWED_ADMIN_IDS:
        await msg.answer("Введите административный пароль:", reply_markup=kb.back_to_menu)
        await state.set_state(user_states.waiting_for_admin_password)
    else:
        return  # Если пользователь не в списке, игнорируем команду

@rt.message(user_states.waiting_for_admin_password)
async def process_admin_login(message: Message, state: FSMContext):
    if hash_password(message.text) == ADMIN_PASSWORD:
        user_id = message.from_user.id
        bot_db.switch_user_role_to_admin(user_id)
        await message.answer("Вы успешно вошли как администратор.")
        await start_handler(message, state)  # Вызываем обработчик /start для показа меню администратора
        await state.clear()
    else:
        await message.answer("Неверный пароль. Повторите попытку.", reply_markup=kb.back_to_menu)
        await state.set_state(user_states.waiting_for_admin_password)  # Позволяем пользователю повторно ввести пароль

@rt.callback_query(F.data == "go_back_latest")
async def go_back(query: types.CallbackQuery):
    await query.message.delete()
    await query.message.answer("Вы в главном меню.", reply_markup=kb.customer_role_menu)
    # Функция главного меню (чтобы легко возвращаться назад)
def get_main_keyboard():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(text="🪙 Крипта", callback_data="crypto"),
              InlineKeyboardButton(text="⭐ Звёзды", callback_data="stars"),
          ],
          [
              InlineKeyboardButton(
                  text="🛒 Купить NFT", callback_data="buy_nft"
              ),
              InlineKeyboardButton(
                  text="🔑 Аренда NFT", callback_data="rent_nft"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="📦 Мои заказы", callback_data="my_orders"
              ),
              InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
          ],
          [
              InlineKeyboardButton(
                  text="💬 Отзывы", url="https://t.me/твоя_ссылка_на_отзывы"
              ),
              InlineKeyboardButton(text="👥 Рефералы", callback_data="ref"),
          ],
          [InlineKeyboardButton(text="🆘 Поддержка", callback_data="support")],
          [InlineKeyboardButton(text="🎟 Промокод", callback_data="promocode")],
      ]
  )


# Кнопка возврата в меню
def back_keyboard():
  return InlineKeyboardMarkup(
      inline_keyboard=[
          [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")]
      ]
  )


@rt.message(F.text == "/start")
async def start_handler(message: Message):
  user_name = message.from_user.first_name
  text = (
      f"👋 Салам алейкум, <b>{user_name}</b>! Ты попал в <b>GumStars</b> — бот"
      " по продаже криптовалюты, NFT и звёзд 🌟\n\n💎 Быстро, безопасно и по"
      " выгодному курсу.\nВыберите нужный раздел в меню ниже 👇"
  )
  await message.answer(
      text, reply_markup=get_main_keyboard(), parse_mode="HTML"
  )


# Возврат в главное меню по инлайн-кнопке
@rt.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(callback: CallbackQuery):
  user_name = callback.from_user.first_name
  text = (
      f"👋 Салам алейкум, <b>{user_name}</b>! Ты попал в <b>GumStars</b> — бот"
      " по продаже криптовалюты, NFT и звёзд 🌟\n\n💎 Быстро, безопасно и по"
      " выгодному курсу.\nВыберите нужный раздел в меню ниже 👇"
  )
  await callback.message.edit_text(
      text, reply_markup=get_main_keyboard(), parse_mode="HTML"
  )


# Раздел: Крипта
@rt.callback_query(F.data == "crypto")
async def crypto_menu(callback: CallbackQuery):
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="TON - 125.19 ₽", callback_data="buy_ton"
              ),
              InlineKeyboardButton(
                  text="BTC - 8 155 997.50 ₽", callback_data="buy_btc"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="USDT - 100.57 ₽", callback_data="buy_usdt"
              ),
              InlineKeyboardButton(
                  text="SOL - 10 269.02 ₽", callback_data="buy_sol"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="✏️ Указать свою монету", callback_data="custom_crypto"
              )
          ],
          [
              InlineKeyboardButton(
                  text="◀️ Назад в меню", callback_data="back_to_menu"
              )
          ],
      ]
  )
  text = "🪙 <b>Криптовалюта</b>\n\nОплата в рублях (₽).\nВыберите монету для покупки:"
  await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


# Раздел: Звёзды
@rt.callback_query(F.data == "stars")
async def stars_menu(callback: CallbackQuery):
  keyboard = InlineKeyboardMarkup(
      inline_keyboard=[
          [
              InlineKeyboardButton(
                  text="50 🌟 (75.00 ₽)", callback_data="star_50"
              ),
              InlineKeyboardButton(
                  text="100 🌟 (150.00 ₽)", callback_data="star_100"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="250 🌟 (375.00 ₽)", callback_data="star_250"
              ),
              InlineKeyboardButton(
                  text="500 🌟 (750.00 ₽)", callback_data="star_500"
              ),
          ],
          [
              InlineKeyboardButton(
                  text="⚙️ Указать свое количество",
                  callback_data="custom_stars",
              )
          ],
          [
              InlineKeyboardButton(
                  text="◀️ Назад в меню", callback_data="back_to_menu"
              )
          ],
      ]
  )
  text = "⭐ <b>Покупка Telegram-звёзд</b>\n\nЦена: 1.50 ₽ за 1 звезду.\nВыберите количество звёзд:"
  await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


# Раздел: Купить NFT
@rt.callback_query(F.data == "buy_nft")
async def buy_nft_menu(callback: CallbackQuery):
  text = "🛒 <b>Покупка NFT</b>\n\nВ данный раздел скоро будут добавлены доступные NFT для покупки."
  await callback.message.edit_text(
      text, reply_markup=back_keyboard(), parse_mode="HTML"
  )


# Раздел: Аренда NFT
@rt.callback_query(F.data == "rent_nft")
async def rent_nft_menu(callback: CallbackQuery):
  text = "🔑 <b>Аренда NFT</b>\n\nВ данный раздел скоро будут добавлены NFT для аренды."
  await callback.message.edit_text(
      text, reply_markup=back_keyboard(), parse_mode="HTML"
  )


# Раздел: Профиль
@rt.callback_query(F.data == "profile")
async def profile_menu(callback: CallbackQuery):
  user_id = callback.from_user.id
  user_name = callback.from_user.first_name
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
          [
              InlineKeyboardButton(
                  text="👥 Реферальная система", callback_data="ref"
              )
          ],
          [
              InlineKeyboardButton(
                  text="◀️ Назад в меню", callback_data="back_to_menu"
              )
          ],
      ]
  )
  await callback.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")


# Раздел: Рефералы
@rt.callback_query(F.data == "ref")
async def ref_menu(callback: CallbackQuery):
  user_id = callback.from_user.id
  text = (
      f"👥 <b>РЕФЕРАЛЬНАЯ СИСТЕМА</b>\n\n"
      "Приглашайте друзей — получите 50 🌟 по персональному промокоду!\n\n"
      f"🔗 <b>Ваша ссылка:</b>\n<code>https://t.me/gumstars09_bot?start=ref{user_id}</code>\n\n"
      "👥 Перешло по ссылке: 0\n"
      "⭐ Купили на от 500 ₽: 0\n\n"
      "Пригласите друга, который купит на сумму от 500 ₽ — и получите промокод на 50 🌟."
  )
  await callback.message.edit_text(
      text, reply_markup=back_keyboard(), parse_mode="HTML"
  )



# Раздел: Промокод
@rt.callback_query(F.data == "promocode")
async def promo_menu(callback: CallbackQuery):
  text = (
      "🎟 <b>ПРОМОКОДЫ</b>\n\n"
      "Введите промокод текстом, чтобы получить 🌟 звёзды 👇\n\n"
      "Кодов пока нет — введите первый!"
  )
  await callback.message.edit_text(
      text, reply_markup=back_keyboard(), parse_mode="HTML"
  )


# Раздел: Мои заказы
@rt.callback_query(F.data == "my_orders")
async def orders_menu(callback: CallbackQuery):
  text = "📦 <b>Мои заказы</b>\n\nУ вас пока нет активных или завершенных заказов."
  await callback.message.edit_text(
      text, reply_markup=back_keyboard(), parse_mode="HTML"
)
                     

@rt.callback_query(F.data == "support")
async def support_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text(
        "<b>💬 Поддержка</b>\n\n"
        "Напишите вашу проблему или вопрос — мы постараемся ответить как можно скорее.\n"
        "При необходимости приложите фото или файл.",
        reply_markup=back_keyboard(),
        parse_mode="HTML"
    )
    await state.set_state(user_states.waiting_for_support)
    await callback.answer()

@rt.message(user_states.waiting_for_support)
async def process_support_message(message: Message, state: FSMContext, bot):
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    username = message.from_user.username or "нет юзернейма"
    
    admin_id = 746135387  # Твой ID
    
    admin_text = (
        f"📩 <b>Новое обращение в поддержку!</b>\n\n"
        f"👤 От: {user_name} (@{username})\n"
        f"🆔 ID: <code>{user_id}</code>\n\n"
        f"💬 <b>Сообщение:</b>\n{message.text}"
    )
    
    await bot.send_message(admin_id, admin_text, parse_mode="HTML")
    await message.answer("✅ Ваше сообщение успешно отправлено в поддержку! Ожидайте ответа.")
    await state.clear()
