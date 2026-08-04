import base64
import hashlib
import json
import math
import os
import secrets
import sqlite3
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "data.db")
STATIC_DIR = os.path.join(BASE_DIR, "static")
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
DEFAULT_RADIUS_M = 500
MAX_IMAGE_BYTES = 6 * 1024 * 1024

os.makedirs(UPLOAD_DIR, exist_ok=True)


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS spots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            lat REAL NOT NULL,
            lng REAL NOT NULL,
            photo TEXT NOT NULL,
            radius_m INTEGER NOT NULL DEFAULT 500,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS likes (
            spot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            PRIMARY KEY (spot_id, user_id),
            FOREIGN KEY (spot_id) REFERENCES spots(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS comments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            spot_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            text TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (spot_id) REFERENCES spots(id),
            FOREIGN KEY (user_id) REFERENCES users(id)
        );
        """
    )
    conn.commit()
    conn.close()


def haversine_m(lat1, lng1, lat2, lng2):
    R = 6371000
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def hash_password(password):
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
    return f"{salt}${digest}"


def verify_password(password, stored):
    salt, digest = stored.split("$")
    check = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 120000).hex()
    return secrets.compare_digest(check, digest)


def get_user_by_token(token):
    if not token:
        return None
    conn = get_db()
    row = conn.execute(
        "SELECT u.* FROM users u JOIN sessions s ON s.user_id = u.id WHERE s.token = ?",
        (token,),
    ).fetchone()
    conn.close()
    return row


def public_spot(spot, viewer_id=None, viewer_lat=None, viewer_lng=None):
    conn = get_db()
    user = conn.execute("SELECT username FROM users WHERE id = ?", (spot["user_id"],)).fetchone()
    like_count = conn.execute(
        "SELECT COUNT(*) FROM likes WHERE spot_id = ?", (spot["id"],)
    ).fetchone()[0]
    liked = False
    if viewer_id:
        liked = conn.execute(
            "SELECT 1 FROM likes WHERE spot_id = ? AND user_id = ?",
            (spot["id"], viewer_id),
        ).fetchone() is not None
    comments = conn.execute(
        """SELECT c.id, c.text, c.created_at, u.username
           FROM comments c JOIN users u ON u.id = c.user_id
           WHERE c.spot_id = ? ORDER BY c.created_at ASC""",
        (spot["id"],),
    ).fetchall()
    conn.close()

    distance_m = None
    unlocked = None
    if viewer_lat is not None and viewer_lng is not None:
        distance_m = round(haversine_m(viewer_lat, viewer_lng, spot["lat"], spot["lng"]), 1)
        unlocked = distance_m <= spot["radius_m"]

    return {
        "id": spot["id"],
        "name": spot["name"],
        "description": spot["description"],
        "lat": spot["lat"],
        "lng": spot["lng"],
        "photo": spot["photo"] if unlocked else None,
        "radius_m": spot["radius_m"],
        "author": user["username"] if user else "unknown",
        "created_at": spot["created_at"],
        "like_count": like_count,
        "liked": liked,
        "comments": [
            {"id": c["id"], "text": c["text"], "author": c["username"], "created_at": c["created_at"]}
            for c in comments
        ],
        "distance_m": distance_m,
        "unlocked": unlocked,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "NearGram/1.0"
    pending_cookie = None

    def log_message(self, format, *args):
        pass

    def _send(self, status, data, content_type="application/json"):
        body = json.dumps(data).encode("utf-8") if isinstance(data, (dict, list)) else data
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if self.pending_cookie:
            self.send_header("Set-Cookie", self.pending_cookie)
            self.pending_cookie = None
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_IMAGE_BYTES * 2:
            raise ValueError("payload too large")
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _get_token(self):
        cookie = self.headers.get("Cookie", "")
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("token="):
                return part[len("token="):]
        return None

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.handle_api("GET")
            return
        self.serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.handle_api("POST")
            return
        self._send(404, {"error": "not found"})

    def handle_api(self, method):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        try:
            if method == "GET" and path == "/api/me":
                self.api_me()
            elif method == "GET" and path == "/api/spots":
                self.api_spots(query)
            elif method == "POST" and path == "/api/register":
                self.api_register()
            elif method == "POST" and path == "/api/login":
                self.api_login()
            elif method == "POST" and path == "/api/logout":
                self.api_logout()
            elif method == "POST" and path == "/api/spots":
                self.api_create_spot()
            elif method == "POST" and path.startswith("/api/spots/") and path.endswith("/like"):
                self.api_like()
            elif method == "POST" and path.startswith("/api/spots/") and path.endswith("/comments"):
                self.api_comment()
            else:
                self._send(404, {"error": "endpoint not found"})
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            self._send(500, {"error": f"internal error: {e}"})

    def api_me(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(200, {"user": None})
            return
        self._send(200, {"user": {"id": user["id"], "username": user["username"]}})

    def api_register(self):
        data = self._read_json()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        if not (4 <= len(username) <= 24):
            raise ValueError("username deve ter entre 4 e 24 caracteres")
        if len(password) < 4:
            raise ValueError("senha deve ter pelo menos 4 caracteres")
        conn = get_db()
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            conn.close()
            raise ValueError("username já existe")
        cur = conn.execute(
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, cur.lastrowid))
        conn.commit()
        conn.close()
        self.pending_cookie = f"token={token}; Path=/; HttpOnly"
        self._send(201, {"token": token, "username": username})

    def api_login(self):
        data = self._read_json()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            conn.close()
            raise ValueError("credenciais inválidas")
        token = secrets.token_hex(32)
        conn.execute("INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user["id"]))
        conn.commit()
        conn.close()
        self.pending_cookie = f"token={token}; Path=/; HttpOnly"
        self._send(200, {"token": token, "username": username})

    def api_logout(self):
        token = self._get_token()
        if token:
            conn = get_db()
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()
        self.send_response(200)
        self.send_header("Set-Cookie", "token=; Max-Age=0; Path=/")
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b"{}")))
        self.end_headers()
        self.wfile.write(b"{}")

    def api_spots(self, query):
        viewer = get_user_by_token(self._get_token())
        viewer_id = viewer["id"] if viewer else None
        try:
            lat = float(query.get("lat", [""])[0]) if query.get("lat") else None
            lng = float(query.get("lng", [""])[0]) if query.get("lng") else None
        except (ValueError, IndexError):
            raise ValueError("lat/lng inválidos")
        conn = get_db()
        rows = conn.execute("SELECT * FROM spots ORDER BY created_at DESC").fetchall()
        conn.close()
        spots = [public_spot(r, viewer_id, lat, lng) for r in rows]
        if lat is None or lng is None:
            spots = [dict(s, unlocked=None, distance_m=None) for s in spots]
        self._send(200, {"spots": spots, "radius_m": DEFAULT_RADIUS_M})

    def api_create_spot(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        data = self._read_json()
        name = (data.get("name") or "").strip()
        description = (data.get("description") or "").strip()
        lat = data.get("lat")
        lng = data.get("lng")
        photo_b64 = data.get("photo") or ""
        radius = data.get("radius_m") or DEFAULT_RADIUS_M
        if not name:
            raise ValueError("dê um nome ao lugar")
        if lat is None or lng is None:
            raise ValueError("posição não informada")
        try:
            lat = float(lat)
            lng = float(lng)
            radius = int(radius)
        except (TypeError, ValueError):
            raise ValueError("coordenadas inválidas")
        if not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            raise ValueError("coordenadas fora do intervalo")
        if not photo_b64.startswith("data:image"):
            raise ValueError("foto inválida (use uma imagem)")
        meta, payload = photo_b64.split(",", 1)
        ext = "png" if "png" in meta else "jpg"
        try:
            raw = base64.b64decode(payload, validate=True)
        except Exception:
            raise ValueError("foto inválida (base64 quebrado)")
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("foto muito grande (máx 6MB)")
        filename = f"{secrets.token_hex(12)}.{ext}"
        with open(os.path.join(UPLOAD_DIR, filename), "wb") as f:
            f.write(raw)
        conn = get_db()
        cur = conn.execute(
            """INSERT INTO spots (user_id, name, description, lat, lng, photo, radius_m)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], name, description, lat, lng, f"/uploads/{filename}", radius),
        )
        conn.commit()
        spot = conn.execute("SELECT * FROM spots WHERE id = ?", (cur.lastrowid,)).fetchone()
        conn.close()
        self._send(201, {"spot": public_spot(spot, user["id"])})

    def _spot_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        return int(parts[-2])

    def api_like(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        spot_id = self._spot_id_from_path()
        conn = get_db()
        if not conn.execute("SELECT 1 FROM spots WHERE id = ?", (spot_id,)).fetchone():
            conn.close()
            raise ValueError("spot não existe")
        existing = conn.execute(
            "SELECT 1 FROM likes WHERE spot_id = ? AND user_id = ?",
            (spot_id, user["id"]),
        ).fetchone()
        if existing:
            conn.execute(
                "DELETE FROM likes WHERE spot_id = ? AND user_id = ?",
                (spot_id, user["id"]),
            )
            liked = False
        else:
            conn.execute(
                "INSERT INTO likes (spot_id, user_id) VALUES (?, ?)",
                (spot_id, user["id"]),
            )
            liked = True
        conn.commit()
        count = conn.execute(
            "SELECT COUNT(*) FROM likes WHERE spot_id = ?", (spot_id,)
        ).fetchone()[0]
        conn.close()
        self._send(200, {"liked": liked, "like_count": count})

    def api_comment(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        spot_id = self._spot_id_from_path()
        data = self._read_json()
        text = (data.get("text") or "").strip()
        if not text:
            raise ValueError("comentário vazio")
        if len(text) > 500:
            raise ValueError("comentário muito longo")
        conn = get_db()
        if not conn.execute("SELECT 1 FROM spots WHERE id = ?", (spot_id,)).fetchone():
            conn.close()
            raise ValueError("spot não existe")
        conn.execute(
            "INSERT INTO comments (spot_id, user_id, text) VALUES (?, ?, ?)",
            (spot_id, user["id"], text),
        )
        conn.commit()
        conn.close()
        self._send(201, {"ok": True})

    def serve_static(self, path):
        if path == "/":
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC_DIR, path.lstrip("/")))
        if not full.startswith(os.path.normpath(STATIC_DIR)):
            self._send(403, b"forbidden", "text/plain")
            return
        if not os.path.isfile(full):
            self._send(404, b"not found", "text/plain")
            return
        ext = os.path.splitext(full)[1].lower()
        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
        }.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    init_db()
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"NearGram rodando em http://{host}:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
