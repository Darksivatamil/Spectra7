import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "spectra7.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS attacks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attack_type TEXT,
        target TEXT,
        message_count INTEGER,
        success_count INTEGER,
        fail_count INTEGER,
        status TEXT,
        started_at TEXT,
        finished_at TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        attack_id INTEGER,
        api_name TEXT,
        target TEXT,
        status TEXT,
        response TEXT,
        timestamp TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS api_status (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        api_name TEXT UNIQUE,
        api_type TEXT,
        last_alive TIMESTAMP,
        fail_count INTEGER DEFAULT 0
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key_name TEXT UNIQUE,
        encrypted_key TEXT NOT NULL,
        provider TEXT NOT NULL DEFAULT 'nvidia',
        is_default INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

def log_attack(attack_type, target, message_count):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO attacks (attack_type, target, message_count, status, started_at) VALUES (?,?,?,?,?)",
              (attack_type, target, message_count, "running", datetime.now().isoformat()))
    attack_id = c.lastrowid
    conn.commit()
    conn.close()
    return attack_id

def update_attack(attack_id, success_count, fail_count, status):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE attacks SET success_count=?, fail_count=?, status=?, finished_at=? WHERE id=?",
              (success_count, fail_count, status, datetime.now().isoformat(), attack_id))
    conn.commit()
    conn.close()

def log_api_call(attack_id, api_name, target, status, response):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO logs (attack_id, api_name, target, status, response, timestamp) VALUES (?,?,?,?,?,?)",
              (attack_id, api_name, target, status, response, datetime.now().isoformat()))
    conn.commit()
    conn.close()

def update_api_status(api_name, api_type, alive):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if alive:
        c.execute("INSERT OR REPLACE INTO api_status (api_name, api_type, last_alive, fail_count) VALUES (?,?,?,COALESCE((SELECT fail_count FROM api_status WHERE api_name=?),0))",
                  (api_name, api_type, datetime.now().isoformat(), api_name))
    else:
        c.execute("INSERT INTO api_status (api_name, api_type, last_alive, fail_count) VALUES (?,?,?,1) ON CONFLICT(api_name) DO UPDATE SET fail_count = fail_count + 1",
                  (api_name, api_type, datetime.now().isoformat()))
    conn.commit()
    conn.close()


def get_target_count_today(target):
    """Count total message_count for a target in the last 24 hours."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    today = datetime.now().isoformat()[:10]
    c.execute("SELECT COALESCE(SUM(message_count), 0) FROM attacks WHERE target = ? AND started_at >= ?",
              (target, today))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0
