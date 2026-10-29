import sqlite3

def init_db():
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    # Таблица пользователей (ID, баланс звёзд, кто пригласил)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            referrer_id INTEGER DEFAULT NULL
        )
    """)
    
    # Таблица для отслеживания покупок (чтобы бонус начислялся 1 раз за друга)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS completed_purchases (
            user_id INTEGER PRIMARY KEY
        )
    """)
    
    conn.commit()
    conn.close()

# Добавить пользователя (если его еще нет)
def add_user(user_id: int, referrer_id: int = None):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        # Если есть реферер и он не равен самому себе
        ref = referrer_id if referrer_id and referrer_id != user_id else None
        cursor.execute("INSERT INTO users (user_id, balance, referrer_id) VALUES (?, 0, ?)", (user_id, ref))
        conn.commit()
        
    conn.close()

# Получить данные пользователя
def get_user(user_id: int):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT balance, referrer_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row

# Начислить баланс
def add_balance(user_id: int, amount: int):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

# Проверка, совершал ли пользователь покупку ранее для бонуса
def has_received_bonus_for(user_id: int) -> bool:
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM completed_purchases WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def mark_purchase_bonused(user_id: int):
    conn = sqlite3.connect("bot.db")
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO completed_purchases (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()
