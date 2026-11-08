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
                    if self.conn:
                        try:
                            self.conn.rollback()
                        except Exception:
                            pass
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
            for stmt in [
                "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS id SERIAL;",
                "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS order_id TEXT;",
                "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS user_id BIGINT;",
                "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS amount NUMERIC;",
                "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS provider TEXT;",
                "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS status TEXT;",
                "ALTER TABLE transactions ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;",
                "ALTER TABLE transactions ALTER COLUMN user_id TYPE BIGINT USING user_id::BIGINT;",
                "ALTER TABLE transactions ALTER COLUMN amount TYPE NUMERIC USING amount::NUMERIC;",
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_transactions_order_id ON transactions(order_id);"
            ]:
                try:
                    self._run(stmt)
                except Exception as ex:
                    logger.warning(f"Transactions migration notice ({stmt}): {ex}")

            self._run("""
                CREATE TABLE IF NOT EXISTS bot_banners (
                    section_name TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL
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
            self._run("""
                CREATE TABLE IF NOT EXISTS bot_banners (
                    section_name TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL
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

    def get_referrals_list(self, user_id: int) -> list:
        q = ("SELECT user_id FROM users WHERE referrer_id = %s" 
             if self.is_postgres else 
             "SELECT user_id FROM users WHERE referrer_id = ?")
        rows = self._run(q, (user_id,), fetch="all")
        return [int(r[0]) for r in rows if r and r[0]] if rows else []

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

    def get_banner(self, section_name: str):
        row = self._run(
            "SELECT file_id FROM bot_banners WHERE section_name = %s" if self.is_postgres else "SELECT file_id FROM bot_banners WHERE section_name = ?",
            (section_name,),
            fetch="one"
        )
        return row[0] if row else None

    def set_banner(self, section_name: str, file_id: str):
        if self.is_postgres:
            q = """
                INSERT INTO bot_banners (section_name, file_id) 
                VALUES (%s, %s)
                ON CONFLICT (section_name) DO UPDATE SET file_id = EXCLUDED.file_id;
            """
        else:
            q = "INSERT OR REPLACE INTO bot_banners (section_name, file_id) VALUES (?, ?)"
        self._run(q, (section_name, file_id))

    def get_all_banners(self) -> dict:
        try:
            rows = self._run("SELECT section_name, file_id FROM bot_banners", fetch="all")
            return {r[0]: r[1] for r in rows} if rows else {}
        except Exception:
            return {}

    def get_all_user_ids(self) -> list:
        try:
            rows = self._run("SELECT DISTINCT user_id FROM users WHERE user_id IS NOT NULL", fetch="all")
            return [int(r[0]) for r in rows if r and r[0]] if rows else []
        except Exception as e:
            logger.error(f"get_all_user_ids error: {e}")
            return []

    def get_top_referrers(self, limit: int = 10) -> list:
        try:
            q = """
                SELECT referrer_id, COUNT(*) as ref_count 
                FROM users 
                WHERE referrer_id IS NOT NULL AND referrer_id != 0 
                GROUP BY referrer_id 
                ORDER BY ref_count DESC 
                LIMIT %s
            """ if self.is_postgres else """
                SELECT referrer_id, COUNT(*) as ref_count 
                FROM users 
                WHERE referrer_id IS NOT NULL AND referrer_id != 0 
                GROUP BY referrer_id 
                ORDER BY ref_count DESC 
                LIMIT ?
            """
            rows = self._run(q, (limit,), fetch="all")
            return [(int(r[0]), int(r[1])) for r in rows if r and r[0]] if rows else []
        except Exception as e:
            logger.error(f"get_top_referrers error: {e}")
            return []

    def get_user_referral_rank(self, user_id: int) -> int:
        try:
            user_count = self.count_referrals(user_id)
            if user_count == 0:
                return 0
            q = """
                SELECT COUNT(DISTINCT referrer_id) + 1 
                FROM (
                    SELECT referrer_id, COUNT(*) as cnt 
                    FROM users 
                    WHERE referrer_id IS NOT NULL 
                    GROUP BY referrer_id
                ) t 
                WHERE t.cnt > %s
            """ if self.is_postgres else """
                SELECT COUNT(DISTINCT referrer_id) + 1 
                FROM (
                    SELECT referrer_id, COUNT(*) as cnt 
                    FROM users 
                    WHERE referrer_id IS NOT NULL 
                    GROUP BY referrer_id
                ) 
                WHERE cnt > ?
            """
            row = self._run(q, (user_count,), fetch="one")
            return row[0] if row else 1
        except Exception as e:
            logger.error(f"get_user_referral_rank error: {e}")
            return 1

    def add_transaction(self, order_id: str, user_id: int, amount: float, provider: str, status: str = "completed"):
        """Сохраняет ордер в базу данных с привязкой к user_id и статусу"""
        order_str = str(order_id)
        uid = int(user_id)
        amt = float(amount or 0)
        try:
            if self.is_postgres:
                existing = self._run("SELECT order_id FROM transactions WHERE order_id = %s", (order_str,), fetch="one")
                if existing:
                    self._run(
                        "UPDATE transactions SET status = %s, amount = %s, provider = %s, user_id = %s WHERE order_id = %s",
                        (status, amt, provider, uid, order_str)
                    )
                else:
                    self._run(
                        "INSERT INTO transactions (order_id, user_id, amount, provider, status) VALUES (%s, %s, %s, %s, %s)",
                        (order_str, uid, amt, provider, status)
                    )
            else:
                existing = self._run("SELECT order_id FROM transactions WHERE order_id = ?", (order_str,), fetch="one")
                if existing:
                    self._run(
                        "UPDATE transactions SET status = ?, amount = ?, provider = ?, user_id = ? WHERE order_id = ?",
                        (status, amt, provider, uid, order_str)
                    )
                else:
                    self._run(
                        "INSERT INTO transactions (order_id, user_id, amount, provider, status) VALUES (?, ?, ?, ?, ?)",
                        (order_str, uid, amt, provider, status)
                    )
            logger.info(f"Transaction saved: order={order_str}, user={uid}, amount={amt}, status={status}")
        except Exception as e:
            logger.error(f"add_transaction error: {e}", exc_info=True)

    def get_user_orders(self, user_id: int, status: str = None) -> list:
        """Возвращает реальные заказы конкретного пользователя из таблицы transactions"""
        uid_str = str(user_id)
        uid_int = int(user_id) if str(user_id).isdigit() else 0
        try:
            st_cond_pg = ""
            st_cond_sq = ""
            if status:
                st_lower = status.lower().strip()
                if st_lower in ("in_progress", "pending", "в процессе"):
                    st_cond_pg = "AND LOWER(status) IN ('in_progress', 'pending', 'в процессе')"
                    st_cond_sq = "AND LOWER(status) IN ('in_progress', 'pending', 'в процессе')"
                elif st_lower in ("completed", "paid", "success", "выполненные", "выполнен"):
                    st_cond_pg = "AND LOWER(status) IN ('completed', 'paid', 'success', 'выполненные', 'выполнен')"
                    st_cond_sq = "AND LOWER(status) IN ('completed', 'paid', 'success', 'выполненные', 'выполнен')"
                elif st_lower in ("cancelled", "canceled", "failed", "отменённые", "отмененные", "отменен", "отменено", "отменён"):
                    st_cond_pg = "AND LOWER(status) IN ('cancelled', 'canceled', 'failed', 'отменённые', 'отмененные', 'отменен', 'отменено', 'отменён')"
                    st_cond_sq = "AND LOWER(status) IN ('cancelled', 'canceled', 'failed', 'отменённые', 'отмененные', 'отменен', 'отменено', 'отменён')"
                else:
                    st_cond_pg = f"AND LOWER(status) = '{st_lower}'"
                    st_cond_sq = f"AND LOWER(status) = '{st_lower}'"

            q = ("SELECT order_id, amount, provider, status, created_at FROM transactions WHERE (user_id::text = %s OR user_id = %s) " + st_cond_pg + " ORDER BY id DESC"
                 if self.is_postgres else
                 "SELECT order_id, amount, provider, status, created_at FROM transactions WHERE (CAST(user_id AS TEXT) = ? OR user_id = ?) " + st_cond_sq + " ORDER BY id DESC")
            params = (uid_str, uid_int)
            rows = self._run(q, params, fetch="all")
            return rows or []
        except Exception as e:
            logger.error(f"get_user_orders error with ORDER BY: {e}, attempting fallback")
            try:
                q_fallback = ("SELECT order_id, amount, provider, status, created_at FROM transactions WHERE (user_id::text = %s OR user_id = %s)"
                              if self.is_postgres else
                              "SELECT order_id, amount, provider, status, created_at FROM transactions WHERE (CAST(user_id AS TEXT) = ? OR user_id = ?)")
                rows = self._run(q_fallback, (uid_str, uid_int), fetch="all")
                return list(reversed(rows or []))
            except Exception as e2:
                logger.error(f"get_user_orders fatal fallback error: {e2}")
                return []

    def get_user_orders_stats(self, user_id: int) -> dict:
        """Считает точное количество заказов по статусам для пользователя"""
        try:
            orders = self.get_user_orders(user_id)
            stats = {"total": len(orders), "in_progress": 0, "completed": 0, "cancelled": 0}
            for o in orders:
                st = str(o[3]).lower().strip()
                if st in ("in_progress", "pending", "в процессе"):
                    stats["in_progress"] += 1
                elif st in ("completed", "paid", "success", "выполненные", "выполнен"):
                    stats["completed"] += 1
                elif st in ("cancelled", "canceled", "failed", "отменённые", "отмененные", "отменен", "отменено", "отменён"):
                    stats["cancelled"] += 1
                else:
                    stats["completed"] += 1
            return stats
        except Exception as e:
            logger.error(f"get_user_orders_stats error: {e}")
            return {"total": 0, "in_progress": 0, "completed": 0, "cancelled": 0}

    def cancel_pending_orders(self, user_id: int, order_id: str = None):
        """Отменяет все незавершенные (in_progress) заказы пользователя или конкретный заказ"""
        uid_str = str(user_id)
        uid_int = int(user_id) if str(user_id).isdigit() else 0
        try:
            if order_id:
                q = ("UPDATE transactions SET status = 'cancelled' WHERE order_id = %s"
                     if self.is_postgres else
                     "UPDATE transactions SET status = 'cancelled' WHERE order_id = ?")
                self._run(q, (str(order_id),))
                logger.info(f"Order {order_id} marked as cancelled")
            else:
                q = ("""
                    UPDATE transactions 
                    SET status = 'cancelled' 
                    WHERE (user_id::text = %s OR user_id = %s) 
                      AND LOWER(status) IN ('in_progress', 'pending', 'в процессе');
                """ if self.is_postgres else """
                    UPDATE transactions 
                    SET status = 'cancelled' 
                    WHERE (CAST(user_id AS TEXT) = ? OR user_id = ?) 
                      AND LOWER(status) IN ('in_progress', 'pending', 'в процессе');
                """)
                self._run(q, (uid_str, uid_int))
                logger.info(f"All pending orders cancelled for user {user_id}")
        except Exception as e:
            logger.error(f"cancel_pending_orders error: {e}")

    def cancel_order(self, order_id: str):
        """Отменяет заказ по его ID"""
        return self.cancel_pending_orders(user_id=0, order_id=order_id)

    def cancel_latest_pending_order(self, user_id: int):
        """Отменяет все текущие незавершенные заказы пользователя"""
        return self.cancel_pending_orders(user_id=user_id)
