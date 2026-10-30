import csv
import os

import psycopg2

from Exceptions import WrongItemException


class BotDB:
    """Версия для Postgres (Neon). Ссылка на базу берётся из переменной окружения DATABASE_URL."""

    def __init__(self, db_file=None):
        self.dsn = os.getenv("DATABASE_URL")
        # запасной вариант: если ссылка на Postgres лежит в config.DATABASE
        if not self.dsn and db_file and str(db_file).startswith(("postgres://", "postgresql://")):
            self.dsn = str(db_file)
        if not self.dsn:
            raise RuntimeError(
                "Не задана переменная окружения DATABASE_URL (ссылка на Postgres). "
                "Добавь её в Render -> Environment."
            )

        self.conn = None
        self.actual_id = None  # id товара, который сейчас создаётся

        self._create_tables()

    # ------------------------------------------------------------------
    # Служебные методы
    # ------------------------------------------------------------------
    def _run(self, query, params=None, fetch=None):
        """
        Выполняет запрос и сам делает commit.
        fetch: None | "one" | "all" | "table" (вернёт (названия_колонок, строки)).
        Если соединение оборвалось (Neon засыпает после простоя) — переподключается и повторяет.
        """
        last_error = None
        for _ in range(2):
            try:
                if self.conn is None or self.conn.closed:
                    self.conn = psycopg2.connect(self.dsn, connect_timeout=15)
                with self.conn.cursor() as cur:
                    cur.execute(query, params)
                    result = None
                    if fetch == "one":
                        result = cur.fetchone()
                    elif fetch == "all":
                        result = cur.fetchall()
                    elif fetch == "table":
                        columns = [d[0] for d in cur.description]
                        result = (columns, cur.fetchall())
                self.conn.commit()
                return result
            except (psycopg2.OperationalError, psycopg2.InterfaceError) as e:
                last_error = e
                try:
                    self.conn.close()
                except Exception:
                    pass
                self.conn = None
            except Exception:
                try:
                    self.conn.rollback()
                except Exception:
                    pass
                raise
        raise last_error

    @staticmethod
    def _write_csv(csv_file, columns, rows):
        with open(csv_file, mode="w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow(columns)
            writer.writerows(rows)

    def _create_tables(self):
        self._run('''
            CREATE TABLE IF NOT EXISTS Users (
                Telegram_id BIGINT PRIMARY KEY,
                role TEXT DEFAULT 'Customer',
                balance INTEGER DEFAULT 0,
                referrer_id BIGINT DEFAULT NULL,
                purchase_bonused INTEGER DEFAULT 0
            )
        ''')
        self._run('''
            CREATE TABLE IF NOT EXISTS Orders (
                id SERIAL PRIMARY KEY,
                Customer_telegram_id BIGINT,
                Seller_telegram_id BIGINT
            )
        ''')
        self._run('''
            CREATE TABLE IF NOT EXISTS Items (
                item_id SERIAL PRIMARY KEY,
                name TEXT,
                description TEXT,
                price REAL,
                amount INTEGER,
                Picture TEXT
            )
        ''')
        self._run('''
            CREATE TABLE IF NOT EXISTS Favorite_Cart (
                Item_id INTEGER,
                Telegram_id BIGINT,
                Item_location TEXT
            )
        ''')
        self._run('''
            CREATE TABLE IF NOT EXISTS Seller (
                Seller_telegram_id BIGINT PRIMARY KEY,
                Description TEXT
            )
        ''')
        self._run('''
            CREATE TABLE IF NOT EXISTS Promo (
                promocode TEXT,
                discount INTEGER
            )
        ''')

    # ------------------------------------------------------------------
    # Пользователи и роли
    # ------------------------------------------------------------------
    def is_user_in_db(self, user_id):
        row = self._run("SELECT Telegram_id FROM Users WHERE Telegram_id = %s", (user_id,), fetch="one")
        return row is not None

    def create_new_user(self, user_id):
        self._run(
            "INSERT INTO Users (Telegram_id) VALUES (%s) ON CONFLICT (Telegram_id) DO NOTHING",
            (user_id,),
        )

    def insert_seller(self, user_id):
        self._run(
            "INSERT INTO Seller (Seller_Telegram_id) VALUES (%s) ON CONFLICT (Seller_Telegram_id) DO NOTHING",
            (user_id,),
        )
        self._run("UPDATE Users SET role = %s WHERE Telegram_id = %s", ("Seller", user_id))

    def insert_customer(self, user_id):
        self._run("UPDATE Users SET role = %s WHERE Telegram_id = %s", ("Customer", user_id))

    def get_role(self, user_id):
        return self._run("SELECT role FROM Users WHERE Telegram_id = %s", (user_id,), fetch="one")

    def switch_user_role_to_seller(self, user_id):
        self._run("UPDATE Users SET role = %s WHERE Telegram_id = %s", ("Seller", user_id))

    def switch_user_role_to_customer(self, user_id):
        self._run("UPDATE Users SET role = %s WHERE Telegram_id = %s", ("Customer", user_id))

    def switch_user_role_to_admin(self, user_id):
        self._run("UPDATE Users SET role = %s WHERE Telegram_id = %s", ("Administrator", user_id))

    # ------------------------------------------------------------------
    # CSV-выгрузки
    # ------------------------------------------------------------------
    def users_list(self):
        csv_file = "users_list.csv"
        try:
            columns, rows = self._run("SELECT * FROM Users", fetch="table")
            self._write_csv(csv_file, columns, rows)
            return csv_file
        except Exception as e:
            print(f"Произошла ошибка при создании CSV файла: {e}")
            return None

    def check_orders(self):
        csv_file = "current_orders.csv"
        try:
            columns, rows = self._run("SELECT * FROM Orders", fetch="table")
            self._write_csv(csv_file, columns, rows)
            return csv_file
        except Exception as e:
            print(f"Произошла ошибка при создании CSV файла: {e}")
            return None

    def get_seller_orders(self, user_id):
        csv_file = f"order_list_for_this_seller_{user_id}.csv"
        try:
            columns, rows = self._run(
                "SELECT * FROM Orders WHERE Seller_Telegram_id = %s", (user_id,), fetch="table"
            )
            self._write_csv(csv_file, columns, rows)
            return csv_file
        except Exception as e:
            print(f"Произошла ошибка при создании CSV файла: {e}")
            return None

    def get_customer_orders(self, user_id):
        csv_file = f"order_list_for_this_customer_{user_id}.csv"
        try:
            columns, rows = self._run(
                "SELECT * FROM Orders WHERE Customer_Telegram_id = %s", (user_id,), fetch="table"
            )
            self._write_csv(csv_file, columns, rows)
            return csv_file
        except Exception as e:
            print(f"Произошла ошибка при создании CSV файла: {e}")
            return None

    # ------------------------------------------------------------------
    # Товары
    # ------------------------------------------------------------------
    def _current_item_id(self):
        """id товара, который сейчас заполняется. После перезапуска берём последний созданный."""
        if self.actual_id is None:
            row = self._run("SELECT MAX(item_id) FROM Items", fetch="one")
            self.actual_id = row[0] if row else None
        return self.actual_id

    def create_new_item(self):
        row = self._run(
            "INSERT INTO Items (name, description, price, amount) VALUES (%s, %s, %s, %s) RETURNING item_id",
            ("default", "default", 0, 0),
            fetch="one",
        )
        self.actual_id = row[0]
        return self.actual_id

    def insert_name(self, name):
        self._run("UPDATE Items SET name = %s WHERE item_id = %s", (name, self._current_item_id()))

    def insert_description(self, description):
        self._run("UPDATE Items SET description = %s WHERE item_id = %s", (description, self._current_item_id()))

    def insert_price(self, price):
        self._run("UPDATE Items SET price = %s WHERE item_id = %s", (float(price), self._current_item_id()))

    def insert_amount(self, amount):
        self._run("UPDATE Items SET amount = %s WHERE item_id = %s", (int(amount), self._current_item_id()))

    def insert_picture(self, picture):
        self._run("UPDATE Items SET Picture = %s WHERE item_id = %s", (picture, self._current_item_id()))

    def insert_shop_description(self, text, Telegram_id):
        self._run(
            "UPDATE Seller SET Description = %s WHERE Seller_Telegram_id = %s",
            (text, Telegram_id),
        )

    def show_all_item(self):
        return self._run("SELECT * FROM Items ORDER BY item_id", fetch="all")

    def get_product_by_name(self, name):
        return self._run("SELECT * FROM Items WHERE Name ILIKE %s", ("%" + name + "%",), fetch="all")

    def add_item_to_cart(self, user_id, item):
        try:
            item_id = int(str(item).strip())
        except ValueError:
            raise WrongItemException

        exists = self._run("SELECT Item_id FROM Items WHERE Item_id = %s", (item_id,), fetch="one")
        in_cart = self._run(
            "SELECT Item_id FROM Favorite_Cart WHERE Item_id = %s AND Telegram_id = %s",
            (item_id, user_id),
            fetch="one",
        )
        if exists is not None and in_cart is None:
            self._run(
                "INSERT INTO Favorite_Cart (Item_id, Telegram_id, Item_location) VALUES (%s, %s, %s)",
                (item_id, user_id, "Cart"),
            )
        else:
            raise WrongItemException

    # ------------------------------------------------------------------
    # Промокоды
    # ------------------------------------------------------------------
    def insert_promocode(self, promocode, discount):
        # для одной скидки хранится только один промокод
        self._run("DELETE FROM Promo WHERE discount = %s", (discount,))
        self._run("INSERT INTO Promo (promocode, discount) VALUES (%s, %s)", (promocode, discount))

    def check_promocode(self, promocode):
        row = self._run("SELECT * FROM Promo WHERE promocode = %s", (promocode,), fetch="one")
        return bool(row)

    # ------------------------------------------------------------------
    # Рефералка и баланс
    # ------------------------------------------------------------------
    def add_user(self, user_id, referrer_id=None):
        """Добавляет пользователя, если его нет, и сохраняет реферера. True — если пользователь новый."""
        if referrer_id == user_id:
            referrer_id = None
        row = self._run(
            "INSERT INTO Users (Telegram_id, referrer_id, balance, purchase_bonused) "
            "VALUES (%s, %s, 0, 0) ON CONFLICT (Telegram_id) DO NOTHING RETURNING Telegram_id",
            (user_id, referrer_id),
            fetch="one",
        )
        return row is not None

    def get_user(self, user_id):
        """Возвращает (баланс, реферер) или None, если пользователя нет."""
        return self._run(
            "SELECT balance, referrer_id FROM Users WHERE Telegram_id = %s", (user_id,), fetch="one"
        )

    def add_balance(self, user_id, amount):
        self._run("UPDATE Users SET balance = balance + %s WHERE Telegram_id = %s", (amount, user_id))

    def update_balance(self, user_id, new_balance):
        self._run("UPDATE Users SET balance = %s WHERE Telegram_id = %s", (new_balance, user_id))

    def has_received_bonus_for(self, user_id):
        row = self._run("SELECT purchase_bonused FROM Users WHERE Telegram_id = %s", (user_id,), fetch="one")
        return row[0] if row and row[0] is not None else 0

    def mark_purchase_bonused(self, user_id):
        self._run("UPDATE Users SET purchase_bonused = 1 WHERE Telegram_id = %s", (user_id,))

    def count_referrals(self, user_id):
        row = self._run("SELECT COUNT(*) FROM Users WHERE referrer_id = %s", (user_id,), fetch="one")
        return row[0] if row else 0
