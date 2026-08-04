import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")

PG = bool(os.environ.get("DATABASE_URL"))


def connect():
    if PG:
        import psycopg2
        conn = psycopg2.connect(os.environ["DATABASE_URL"])
        with conn.cursor() as cur:
            cur.execute("SET search_path TO neargram, public")
        return conn
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def execute(conn, sql, params=()):
    if PG:
        import psycopg2.extras
        cur = conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        cur.execute(sql.replace("?", "%s"), params)
        return cur
    return conn.execute(sql, params)


def insert_id(conn, sql, params=()):
    if PG:
        cur = execute(conn, sql + " RETURNING id", params)
        conn.commit()
        return cur.fetchone()[0]
    cur = execute(conn, sql, params)
    conn.commit()
    return cur.lastrowid


def now_default():
    if PG:
        return "to_char(now(), 'YYYY-MM-DD HH24:MI:SS')"
    return "datetime('now')"


def schema():
    now = now_default()
    if PG:
        return [
            f"""CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(24) UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT DEFAULT {now})""",
            f"""CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT DEFAULT {now})""",
            f"""CREATE TABLE IF NOT EXISTS spots (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                name VARCHAR(120) NOT NULL,
                description TEXT DEFAULT '',
                lat DOUBLE PRECISION NOT NULL,
                lng DOUBLE PRECISION NOT NULL,
                photo_b64 TEXT NOT NULL,
                photo_mime VARCHAR(10) NOT NULL,
                radius_m INTEGER NOT NULL DEFAULT 500,
                created_at TEXT DEFAULT {now})""",
            f"""CREATE TABLE IF NOT EXISTS likes (
                spot_id INTEGER NOT NULL REFERENCES spots(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TEXT DEFAULT {now},
                PRIMARY KEY (spot_id, user_id))""",
            f"""CREATE TABLE IF NOT EXISTS comments (
                id SERIAL PRIMARY KEY,
                spot_id INTEGER NOT NULL REFERENCES spots(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                text VARCHAR(500) NOT NULL,
                created_at TEXT DEFAULT {now})""",
        ]
    return [
        """CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')))""",
        """CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT DEFAULT (datetime('now')))""",
        """CREATE TABLE IF NOT EXISTS spots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            photo_b64 TEXT NOT NULL,
            photo_mime TEXT NOT NULL,
            radius_m INTEGER NOT NULL DEFAULT 500,
            created_at TEXT DEFAULT (datetime('now')))""",
        """CREATE TABLE IF NOT EXISTS likes (
            spot_id INTEGER NOT NULL REFERENCES spots(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (spot_id, user_id))""",
        """CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spot_id INTEGER NOT NULL REFERENCES spots(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')))""",
    ]


def init():
    conn = connect()
    if PG:
        with conn.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS neargram")
        conn.commit()
    for stmt in schema():
        execute(conn, stmt)
    conn.commit()
    conn.close()
