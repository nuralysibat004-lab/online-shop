import sqlite3
import csv
from Exceptions import WrongItemException

class BotDB:
    actual_id = int()

    def __init__(self, db_file):
        # Инициализация соединения с БД
        clean_path = db_file.replace("sqlite+aiosqlite:///", "").replace("sqlite:///", "")
        self.conn = sqlite3.connect(clean_path)
        self.cursor = self.conn.cursor()

        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS Users (
                Telegram_id INTEGER PRIMARY KEY,
                role TEXT DEFAULT 'Customer',
                balance INTEGER DEFAULT 0,
                referrer_id INTEGER DEFAULT NULL,
                purchase_bonused INTEGER DEFAULT 0
            )
        ''')
        
        
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS Orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                Customer_telegram_id INTEGER,
                Seller_telegram_id INTEGER
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS Items (
                item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT,
                description TEXT,
                price REAL,
                amount INTEGER,
                Picture TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS Favorite_Cart (
                Item_id INTEGER,
                Telegram_id INTEGER,
                Item_location INTEGER
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS Seller (
                Seller_telegram_id INTEGER PRIMARY KEY,
                Description TEXT
            )
        ''')
        
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS Promo (
                promocode TEXT,
                discount INTEGER
            )
        ''')
        
        self.conn.commit()
        
                


    
    def is_user_in_db(self, user_id):
        query = self.cursor.execute("Select Telegram_id from Users where Telegram_id = ?", (user_id,)).fetchone()
        if query == None:
            return False
        else:
            return True
    
    def create_new_user(self, user_id):
        self.cursor.execute("INSERT INTO users (Telegram_id) values(?)", (user_id, ))
        self.conn.commit()
    
    def insert_seller(self, user_id):
        self.cursor.execute('''INSERT INTO Seller (Seller_Telegram_id) VALUES (?)''', (user_id, ))
        self.cursor.execute("UPDATE users set role = ? where telegram_id = ?", ("Seller", user_id))
        self.conn.commit()
    
    def insert_customer(self, user_id):
        self.cursor.execute("UPDATE users set role = ? where telegram_id = ?", ("Customer", user_id))
        self.conn.commit()

    def get_role(self, user_id):
        role = self.cursor.execute("Select role from users where telegram_id = ?", (user_id, )).fetchone()
        print(role)
        return role
    
    def users_list(self):
        #Получение списка пользователей из БД
        csv_file = 'users_list.csv'
        users_list = self.cursor.execute("SELECT * from users")
        rows = users_list.fetchall()
    
        try:
            users_list = self.cursor.execute("SELECT * from users")
            rows = users_list.fetchall()
        
            with open(csv_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([description[0] for description in self.cursor.description])
                writer.writerows(rows)
   
            return csv_file
        
        except Exception as e:
            print(f"Произошла ошибка при создании CSV файла: {e}")
            return None
 
    def check_orders(self):
        #Формируем csv файл со списком заказов#
        csv_file = "current_orders.csv"
        try:
            order_list = self.cursor.execute("SELECT * from Orders")
            order_list = order_list.fetchall()
        
            with open(csv_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([description[0] for description in self.cursor.description])
                writer.writerows(order_list)
   
            return csv_file
        
        except Exception as e:
            print(f"Произошла ошибка при создании CSV файла: {e}")
            return None
    
    def create_new_item(self):
        name = "default"
        description = "default"
        price = 0
        amount = 0
        self.cursor.execute('''INSERT INTO items (name, description, price, amount) VALUES (?, ?, ? ,?)''', (name, description, price, amount))
        self.conn.commit()
        global actual_id
        actual_id = self.cursor.lastrowid
    
    def insert_name(self, name):
        global actual_id
        self.cursor.execute('''UPDATE items set name = ? where item_id = (?)''', (name, actual_id) )
        self.conn.commit()

    def insert_description(self, description):
        global actual_id
        self.cursor.execute('''UPDATE items set description = ? where item_id = (?)''', (description, actual_id) )
        self.conn.commit()

    def insert_price(self, price):
        global actual_id
        self.cursor.execute('''UPDATE items set price = ? where item_id = (?)''', (price, actual_id) )
        self.conn.commit()  
    
    def insert_amount(self, amount):
        global actual_id
        self.cursor.execute('''UPDATE items set amount = ? where item_id = (?)''', (amount, actual_id) )
        self.conn.commit()  
    
    def switch_user_role_to_seller(self, user_id):
        self.cursor.execute('''UPDATE Users set role = ? where Telegram_id = (?)''', ("Seller", user_id) )
        self.conn.commit()
    
    def switch_user_role_to_customer(self, user_id):
        self.cursor.execute('''UPDATE Users set role = ? where Telegram_id = (?)''', ("Customer", user_id) )
        self.conn.commit()

    def switch_user_role_to_admin(self, user_id):
        self.cursor.execute('''UPDATE Users set role = ? where Telegram_id = (?)''', ("Administrator", user_id) )
        self.conn.commit()

    def get_seller_orders(self, user_id):
        #Формируем csv файл со списком заказов данного продавца#
        csv_file = f"order_list_for_this_seller_{user_id}.csv"
        try:
            order_list_for_this_seller = self.cursor.execute("SELECT * from Orders where Seller_Telegram_id = ?", (user_id, )).fetchall()
        
            with open(csv_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([description[0] for description in self.cursor.description])
                writer.writerows(order_list_for_this_seller)
   
            return csv_file
        
        except Exception as e:
            print(f"Произошла ошибка при создании CSV файла: {e}")
            return None
    
    def insert_picture(self, picture):
        self.cursor.execute('''UPDATE Items set Picture = ? where item_id = (?)''', (picture, actual_id))
        self.conn.commit()
        
    def insert_shop_description(self, text, Telegram_id):
        self.cursor.execute('''UPDATE Seller set Description = ? where Seller_Telegram_id = (?)''', (text, Telegram_id))
        self.conn.commit()
    
    def get_customer_orders(self, user_id):
        #Формируем csv файл со списком заказов данного продавца#
        csv_file = f"order_list_for_this_customer_{user_id}.csv"
        try:
            order_list_for_this_seller = self.cursor.execute("SELECT * from Orders where Customer_Telegram_id = ?", (user_id, )).fetchall()
        
            with open(csv_file, mode='w', newline='') as file:
                writer = csv.writer(file)
                writer.writerow([description[0] for description in self.cursor.description])
                writer.writerows(order_list_for_this_seller)
   
            return csv_file
        
        except Exception as e:
            print(f"Произошла ошибка при создании CSV файла: {e}")
            return None
    
    def show_all_item(self):
       result = self.cursor.execute('''Select * from items''').fetchall()
       return result

    def add_item_to_cart(self, user_id, item):
        print(item)
        if self.cursor.execute('''select Item_id from Items where Item_id = (?)''', (item,)).fetchone()!= None and self.cursor.execute('''select Item_id from Favorite_Cart where Item_id = (?) and Telegram_id = (?)''', (item,user_id)).fetchone()== None:
            self.cursor.execute('''INSERT INTO Favorite_Cart (Item_id, Telegram_id, Item_location) VALUES (?, ?, ?)''', (item, user_id, "Cart"))
            self.conn.commit()
        else:
            raise WrongItemException
        
    def get_product_by_name(self, name):
        self.cursor.execute("SELECT * FROM Items WHERE Name LIKE ?", ('%' + name + '%',))
        return self.cursor.fetchall()
    
    def insert_promocode(self, promocode, discount):
        # Проверяем, есть ли записи с таким же значением discount
        self.cursor.execute("SELECT * FROM Promo WHERE discount = ?", (discount,))
        existing_records = self.cursor.fetchall()

        if existing_records:
            # Если есть, удаляем их
            self.cursor.execute("DELETE FROM Promo WHERE discount = ?", (discount,))
            self.conn.commit()

        # Записываем новый промокод и скидку
        self.cursor.execute("INSERT INTO Promo (promocode, discount) VALUES (?, ?)", (promocode, discount))
        self.conn.commit()

    def check_promocode(self, promocode):
        result = self.cursor.execute("SELECT * FROM Promo WHERE promocode = ?", (promocode,)).fetchone()
        return bool(result)

    def add_user(self, user_id, referrer_id=None):
        """Добавляет пользователя в базу, если его там нет, и сохраняет реферера."""
        self.cursor.execute("SELECT Telegram_id FROM Users WHERE Telegram_id = ?", (user_id,))
        row = self.cursor.fetchone()
        if not row:
            if referrer_id == user_id:
                referrer_id = None
            self.cursor.execute(
                "INSERT INTO Users (Telegram_id, referrer_id, balance, purchase_bonused) VALUES (?, ?, 0, 0)",
                (user_id, referrer_id)
            )
            self.conn.commit()

    def get_user(self, user_id):
        """Возвращает баланс и реферера пользователя."""
        self.cursor.execute("SELECT balance, referrer_id FROM Users WHERE Telegram_id = ?", (user_id,))
        return self.cursor.fetchone()

    def add_balance(self, user_id, amount):
        """Начисляет звезды на баланс пользователя."""
        self.cursor.execute("UPDATE Users SET balance = balance + ? WHERE Telegram_id = ?", (amount, user_id))
        self.conn.commit()

    def has_received_bonus_for(self, user_id):
        """Проверяет, был ли уже выдан бонус за покупку этого пользователя."""
        self.cursor.execute("SELECT purchase_bonused FROM Users WHERE Telegram_id = ?", (user_id,))
        row = self.cursor.fetchone()
        return row[0] if row and len(row) > 0 else 0

    def mark_purchase_bonused(self, user_id):
        """Отмечает, что бонус за покупку этого пользователя уже выплачен."""
        self.cursor.execute("UPDATE Users SET purchase_bonused = 1 WHERE Telegram_id = ?", (user_id,))
        self.conn.commit()
        
