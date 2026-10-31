import os
import logging
import sqlite3

logger = logging.getLogger(__name__)

class BotDB:
    """
    Универсальная база данных для Telegram-магазина (Stars / Premium / Crypto).
    - Если задана переменная DATABASE_URL -> использует PostgreSQL (Neon / Render).
    - Если DATABASE_URL не задана -> автоматически использует локальный SQLite (bot_db.db).
    """
    def __init__(self, db_file="bot_db.db"):
        self.dsn = os.getenv("DATABASE_URL")
        self.is_postgres = bool(self.dsn and str(self.dsn).startswith(("postgres://", "postgresql://")))
        self.sqlite_file = "bot_db.db"
        self.conn = None
        
        if self.is_postgres:
            import psycopg2
            self.psycopg2 = psycopg2
            logger.info("BotDB: Использование PostgreSQL (Neon)")
        else:
            logger.info("BotDB: Использование SQLite (bot_db.db)")
            
        self._create_tables()

    def _get_connection(self):
        if self.is_postgres:
            if self.conn is None or self.conn.closed:
                self.conn = self.psycopg2.connect(self.dsn, connect_timeout=15)
            return self.conn
        else:
            return sqlite3.connect(self.sqlite_file)

    def _run(self, query, params=None, fetch=None):
        params = params or ()
        if self.is_postgres:
            for _ in range(2):
                try:
                    conn = self._get_connection()
                    with conn.cursor() as cur:
                        cur.execute(query, params)
                        res = None
                        if fetch == "one":
                            res = cur.fetchone()
                        elif fetch == "all":
                            res = cur.fetchall()
                    conn.commit()
                    return res
                except Exception as e:
                    logger.warning(f"Postgres retry error: {e}")
                    self.conn = None
        else:
            conn = self._get_connection()
            cur = conn.cursor()
            cur.execute(query, params)
            res = None
            if fetch == "one":
                res = cur.fetchone()
            elif fetch == "all":
                res = cur.fetchall()
            conn.commit()
            conn.close()
            return res

    def _create_tables(self):
        if self.is_postgres:
            # 1. Автоматическая миграция: если в Neon колонка называлась telegram_id вместо user_id
            try:
                self._run("""
                    DO $$ 
                    BEGIN 
                        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='telegram_id') 
                           AND NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='user_id') THEN
                            ALTER TABLE users RENAME COLUMN telegram_id TO user_id;
                        END IF;
                    END $$;
                """)
            except Exception as e:
                logger.warning(f"Rename migration notice: {e}")

            # 2. Создание таблиц, если их нет
            self._run("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    referrer_id BIGINT DEFAULT NULL
                );
            """)
            self._run("""
                CREATE TABLE IF NOT EXISTS completed_purchases (
                    user_id BIGINT PRIMARY KEY
                );
            """)

            # 3. Гарантируем наличие всех нужных колонок
            try:
                self._run("ALTER TABLE users ADD COLUMN IF NOT EXISTS user_id BIGINT;")
                self._run("ALTER TABLE users ADD COLUMN IF NOT EXISTS balance INTEGER DEFAULT 0;")
                self._run("ALTER TABLE users ADD COLUMN IF NOT EXISTS referrer_id BIGINT DEFAULT NULL;")
            except Exception as e:
                logger.warning(f"Column migration notice: {e}")

            self._run("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id SERIAL PRIMARY KEY,
                    order_id TEXT UNIQUE,
                    user_id BIGINT,
                    amount NUMERIC,
                    provider TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
        else:
            self._run("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    balance INTEGER DEFAULT 0,
                    referrer_id INTEGER DEFAULT NULL
                );
            """)
            self._run("""
                CREATE TABLE IF NOT EXISTS completed_purchases (
                    user_id INTEGER PRIMARY KEY
                );
            """)
            self._run("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT UNIQUE,
                    user_id INTEGER,
                    amount REAL,
                    provider TEXT,
                    status TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)

    def get_user(self, user_id: int):
        return self._run(
            "SELECT balance, referrer_id FROM users WHERE user_id = %s" if self.is_postgres else "SELECT balance, referrer_id FROM users WHERE user_id = ?",
            (user_id,),
            fetch="one"
        )

    def add_user(self, user_id: int, referrer_id: int = None):
        if not self.get_user(user_id):
            ref = referrer_id if referrer_id and referrer_id != user_id else None
            q = ("INSERT INTO users (user_id, balance, referrer_id) VALUES (%s, 0, %s)" 
                 if self.is_postgres else 
                 "INSERT INTO users (user_id, balance, referrer_id) VALUES (?, 0, ?)")
            self._run(q, (user_id, ref))

    def update_balance(self, user_id: int, new_balance: int):
        q = ("UPDATE users SET balance = %s WHERE user_id = %s" 
             if self.is_postgres else 
             "UPDATE users SET balance = ? WHERE user_id = ?")
        self._run(q, (new_balance, user_id))

    def count_referrals(self, user_id: int) -> int:
        q = ("SELECT COUNT(*) FROM users WHERE referrer_id = %s" 
             if self.is_postgres else 
             "SELECT COUNT(*) FROM users WHERE referrer_id = ?")
        row = self._run(q, (user_id,), fetch="one")
        return row[0] if row else 0

    def has_received_bonus_for(self, user_id: int) -> bool:
        q = ("SELECT 1 FROM completed_purchases WHERE user_id = %s" 
             if self.is_postgres else 
             "SELECT 1 FROM completed_purchases WHERE user_id = ?")
        return bool(self._run(q, (user_id,), fetch="one"))

    def mark_bonus_received(self, user_id: int):
        q = ("INSERT INTO completed_purchases (user_id) VALUES (%s) ON CONFLICT DO NOTHING" 
             if self.is_postgres else 
             "INSERT OR IGNORE INTO completed_purchases (user_id) VALUES (?)")
        self._run(q, (user_id,))
