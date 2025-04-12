# db_handler.py
import sqlite3
import os
from datetime import datetime

DB_NAME = "positions.db"

class DBHandler:
    def __init__(self, db_path=DB_NAME):
        self.db_path = db_path
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)  # ✅ Chỉ mở 1 lần
        self._init_db()

    def _init_db(self):
        cursor = self.conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                entry_price REAL NOT NULL,
                position_type TEXT NOT NULL,
                strength TEXT,
                max_price REAL NOT NULL,
                is_trailing_active INTEGER DEFAULT 0,
                mdd_limit_percent REAL DEFAULT 1.5,
                open_time TEXT,
                last_update_time TEXT
            )
        ''')
        self.conn.commit()

    def insert_position(self, symbol, entry_price, position_type, strength, max_price, mdd_limit_percent=1.5):
        cursor = self.conn.cursor()
        now = datetime.utcnow().isoformat()
        cursor.execute('''
            INSERT INTO positions (symbol, entry_price, position_type, strength, max_price, is_trailing_active, mdd_limit_percent, open_time, last_update_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, entry_price, position_type, strength, max_price, 0, mdd_limit_percent, now, now))
        self.conn.commit()

    def update_position(self, symbol, update_fields: dict):
        cursor = self.conn.cursor()
        set_clause = ", ".join([f"{key} = ?" for key in update_fields.keys()])
        params = list(update_fields.values()) + [datetime.utcnow().isoformat(), symbol]
        cursor.execute(f'''
            UPDATE positions
            SET {set_clause}, last_update_time = ?
            WHERE symbol = ?
        ''', params)
        self.conn.commit()

    def get_position(self, symbol):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM positions WHERE symbol = ?', (symbol,))
        return cursor.fetchone()

    def delete_position(self, symbol):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM positions WHERE symbol = ?', (symbol,))
        self.conn.commit()

    def list_positions(self):
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM positions')
        return cursor.fetchall()

    def clear_all_positions(self):
        cursor = self.conn.cursor()
        cursor.execute('DELETE FROM positions')
        self.conn.commit()

    def close(self):
        self.conn.close()
