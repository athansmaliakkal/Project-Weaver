import sqlite3
import os
from config import DB_PATH, DB_DIR

def initialize_database():
    print(f"[*] Initializing database at {DB_PATH}...")
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uid TEXT NOT NULL,
            web_domain TEXT NOT NULL,
            web_email TEXT,
            web_phone TEXT,
            web_address TEXT,
            web_status TEXT NOT NULL,
            scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(uid, web_domain)
        )
    ''')

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS runs (
            uid TEXT PRIMARY KEY,
            total_domains INTEGER,
            successful_domains INTEGER,
            status TEXT,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print("[+] Database initialized successfully.")

if __name__ == "__main__":
    initialize_database()
