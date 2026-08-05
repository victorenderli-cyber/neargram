import base64
import hashlib
import json
import math
import os
import secrets
import sys
import threading
import time
import traceback
from collections import deque
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import db

STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DEFAULT_RADIUS_M = 500
MAX_IMAGE_BYTES = 6 * 1024 * 1024
SESSION_MAX_DAYS = 30
RATE_LIMIT_MAX = 10
RATE_LIMIT_WINDOW = 60
DEFAULT_SPOT_LIMIT = 100
MAX_SPOT_LIMIT = 500


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


_rate_limit_lock = threading.Lock()
_rate_limit_buckets = {}


def _rate_limited(key):
    now = time.monotonic()
    with _rate_limit_lock:
        bucket = _rate_limit_buckets.get(key)
        if bucket is None:
            bucket = deque()
            _rate_limit_buckets[key] = bucket
        while bucket and now - bucket[0] > RATE_LIMIT_WINDOW:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX:
            return True
        bucket.append(now)
        return False


def _session_cutoff():
    return (datetime.now(timezone.utc) - timedelta(days=SESSION_MAX_DAYS)).strftime("%Y-%m-%d %H:%M:%S")


def _prune_sessions(conn, user_id):
    db.execute(conn, "DELETE FROM sessions WHERE user_id = ? AND created_at < ?", (user_id, _session_cutoff()))


def get_user_by_token(token):
    if not token:
        return None
    conn = db.connect()
    row = db.execute(
        conn,
        "SELECT u.* FROM users u JOIN sessions s ON s.user_id = u.id "
        "WHERE s.token = ? AND s.created_at >= ?",
        (token, _session_cutoff()),
    ).fetchone()
    conn.close()
    return row


def public_spot(spot, viewer_id=None, viewer_lat=None, viewer_lng=None, as_author=False):
    conn = db.connect()
    user = db.execute(conn, "SELECT username FROM users WHERE id = ?", (spot["user_id"],)).fetchone()
    like_count = db.execute(conn, "SELECT COUNT(*) FROM likes WHERE spot_id = ?", (spot["id"],)).fetchone()[0]
    liked = False
    if viewer_id:
        liked = db.execute(
            conn, "SELECT 1 FROM likes WHERE spot_id = ? AND user_id = ?", (spot["id"], viewer_id)
        ).fetchone() is not None
    comments = db.execute(
        conn,
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

    photo = None
    if as_author:
        unlocked = True
        photo = f"/api/spots/{spot['id']}/photo"
    elif unlocked:
        photo = f"/api/spots/{spot['id']}/photo?lat={viewer_lat}&lng={viewer_lng}"

    return {
        "id": spot["id"],
        "name": spot["name"],
        "description": spot["description"],
        "lat": spot["lat"],
        "lng": spot["lng"],
        "photo": photo,
        "radius_m": spot["radius_m"],
        "author": user["username"] if user else "unknown",
        "mine": bool(viewer_id and viewer_id == spot["user_id"]),
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


def _bulk_public(rows, viewer_id, viewer_lat, viewer_lng, as_author=False):
    if not rows:
        return []
    conn = db.connect()
    try:
        ids = tuple(r["id"] for r in rows)
        ph = ",".join(["?"] * len(ids))

        user_ids = tuple({r["user_id"] for r in rows})
        users = {}
        if user_ids:
            uph = ",".join(["?"] * len(user_ids))
            for row in db.execute(
                conn, f"SELECT id, username, avatar FROM users WHERE id IN ({uph})", user_ids
            ):
                users[row["id"]] = {"username": row["username"], "avatar": row["avatar"] or ""}

        like_counts = {}
        for row in db.execute(
            conn,
            f"SELECT spot_id, COUNT(*) AS c FROM likes WHERE spot_id IN ({ph}) GROUP BY spot_id",
            ids,
        ):
            like_counts[row["spot_id"]] = row["c"]

        liked_ids = set()
        if viewer_id:
            for row in db.execute(
                conn,
                f"SELECT spot_id FROM likes WHERE user_id = ? AND spot_id IN ({ph})",
                (viewer_id,) + ids,
            ):
                liked_ids.add(row["spot_id"])

        comments = {}
        for row in db.execute(
            conn,
            f"""SELECT c.spot_id, c.id, c.text, c.created_at, u.username
                FROM comments c JOIN users u ON u.id = c.user_id
                WHERE c.spot_id IN ({ph}) ORDER BY c.created_at ASC""",
            ids,
        ):
            comments.setdefault(row["spot_id"], []).append(
                {"id": row["id"], "text": row["text"], "author": row["username"], "created_at": row["created_at"]}
            )
    finally:
        conn.close()

    out = []
    for s in rows:
        distance_m = None
        unlocked = None
        if viewer_lat is not None and viewer_lng is not None:
            distance_m = round(haversine_m(viewer_lat, viewer_lng, s["lat"], s["lng"]), 1)
            unlocked = distance_m <= s["radius_m"]
        is_author = bool(viewer_id and viewer_id == s["user_id"])
        photo = None
        if as_author or is_author:
            unlocked = True
            photo = f"/api/spots/{s['id']}/photo"
        elif unlocked:
            photo = f"/api/spots/{s['id']}/photo?lat={viewer_lat}&lng={viewer_lng}"
        out.append({
            "id": s["id"],
            "name": s["name"],
            "description": s["description"],
            "lat": s["lat"],
            "lng": s["lng"],
            "photo": photo,
            "radius_m": s["radius_m"],
            "author": (users.get(s["user_id"]) or {}).get("username", "unknown"),
            "author_avatar": (users.get(s["user_id"]) or {}).get("avatar", ""),
            "mine": is_author,
            "created_at": s["created_at"],
            "like_count": like_counts.get(s["id"], 0),
            "liked": s["id"] in liked_ids,
            "comments": comments.get(s["id"], []),
            "distance_m": distance_m,
            "unlocked": unlocked,
        })
    return out


def _public_user(user, viewer_id):
    conn = db.connect()
    followers = db.execute(conn, "SELECT COUNT(*) FROM follows WHERE followee_id = ?", (user["id"],)).fetchone()[0]
    following = db.execute(conn, "SELECT COUNT(*) FROM follows WHERE follower_id = ?", (user["id"],)).fetchone()[0]
    spots_n = db.execute(conn, "SELECT COUNT(*) FROM spots WHERE user_id = ?", (user["id"],)).fetchone()[0]
    is_following = False
    follows_me = False
    if viewer_id:
        is_following = db.execute(
            conn, "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?", (viewer_id, user["id"])
        ).fetchone() is not None
        follows_me = db.execute(
            conn, "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?", (user["id"], viewer_id)
        ).fetchone() is not None
    conn.close()
    return {
        "id": user["id"],
        "username": user["username"],
        "bio": user["bio"] or "",
        "avatar": user["avatar"] or "",
        "stats": {"spots": spots_n, "followers": followers, "following": following},
        "is_following": is_following,
        "follows_me": follows_me,
    }


class Handler(BaseHTTPRequestHandler):
    server_version = "NearGram/1.0"
    pending_cookie = None

    def log_message(self, format, *args):
        sys.stderr.write(
            f"{self.log_date_time_string()} {self.client_address[0]} \"{format % args}\"\n"
        )

    def _client_ip(self):
        forwarded = self.headers.get("X-Forwarded-For", "")
        if forwarded:
            return forwarded.split(",")[0].strip() or self.client_address[0]
        return self.client_address[0]

    def _secure(self):
        return self.headers.get("X-Forwarded-Proto", "http") == "https"

    def _send(self, status, data, content_type="application/json"):
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode("utf-8")
        elif isinstance(data, bytes):
            body = data
        else:
            body = str(data).encode("utf-8")
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

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/"):
            self.handle_api("DELETE")
            return
        self._send(404, {"error": "not found"})

    def handle_api(self, method):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        try:
            if method == "GET" and path == "/api/me":
                self.api_me()
            elif method == "GET" and path == "/api/profile":
                self.api_profile()
            elif method == "POST" and path == "/api/profile":
                self.api_update_profile()
            elif method == "GET" and path == "/api/search":
                self.api_search(query)
            elif method == "GET" and path == "/api/notifications":
                self.api_notifications()
            elif method == "POST" and path == "/api/notifications/read":
                self.api_notifications_read()
            elif method == "GET" and path.startswith("/api/users/"):
                self.api_user_profile(query)
            elif method == "POST" and path.startswith("/api/users/") and path.endswith("/follow"):
                self.api_follow()
            elif method == "GET" and path == "/api/spots":
                self.api_spots(query)
            elif method == "GET" and path.startswith("/api/spots/") and path.endswith("/photo"):
                self.api_spot_photo(query)
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
            elif method == "POST" and path.startswith("/api/spots/") and path.endswith("/report"):
                self.api_report()
            elif method == "DELETE" and path.startswith("/api/spots/"):
                self.api_delete_spot()
            else:
                self._send(404, {"error": "endpoint not found"})
        except ValueError as e:
            self._send(400, {"error": str(e)})
        except Exception:
            traceback.print_exc()
            self._send(500, {"error": "erro interno"})

    def api_me(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(200, {"user": None})
            return
        self._send(200, {"user": {"id": user["id"], "username": user["username"],
                                  "bio": user["bio"] or "", "avatar": user["avatar"] or ""}})

    def api_update_profile(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        data = self._read_json()
        bio = (data.get("bio") or "").strip()
        avatar = data.get("avatar")
        if len(bio) > 200:
            raise ValueError("bio muito longa (máx 200 caracteres)")
        if avatar is not None and avatar != "":
            if not avatar.startswith("data:image"):
                raise ValueError("avatar inválido")
            try:
                _, payload = avatar.split(",", 1)
                raw = base64.b64decode(payload, validate=True)
            except Exception:
                raise ValueError("avatar inválido (base64 quebrado)")
            if len(raw) > 1_500_000:
                raise ValueError("avatar muito grande (máx 1.5MB)")
        conn = db.connect()
        db.execute(conn, "UPDATE users SET bio = ? WHERE id = ?", (bio, user["id"]))
        if avatar is not None:
            db.execute(conn, "UPDATE users SET avatar = ? WHERE id = ?", (avatar, user["id"]))
        conn.commit()
        row = db.execute(conn, "SELECT username, bio, avatar FROM users WHERE id = ?", (user["id"],)).fetchone()
        conn.close()
        self._send(200, {"username": row["username"], "bio": row["bio"] or "", "avatar": row["avatar"] or ""})

    def api_profile(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        conn = db.connect()
        rows = db.execute(
            conn, "SELECT * FROM spots WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
        followers = db.execute(conn, "SELECT COUNT(*) FROM follows WHERE followee_id = ?", (user["id"],)).fetchone()[0]
        following = db.execute(conn, "SELECT COUNT(*) FROM follows WHERE follower_id = ?", (user["id"],)).fetchone()[0]
        conn.close()
        spots = _bulk_public(rows, user["id"], None, None, as_author=True)
        spots_count = len(spots)
        likes_received = sum(s["like_count"] for s in spots)
        comments_received = sum(len(s["comments"]) for s in spots)
        self._send(200, {
            "user": {"id": user["id"], "username": user["username"],
                     "bio": user["bio"] or "", "avatar": user["avatar"] or ""},
            "stats": {"spots": spots_count, "likes": likes_received,
                      "comments": comments_received, "followers": followers, "following": following},
            "spots": spots,
        })

    def api_user_profile(self, query):
        viewer = get_user_by_token(self._get_token())
        username = urlparse(self.path).path.strip("/").split("/")[-1]
        conn = db.connect()
        user = db.execute(conn, "SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user:
            conn.close()
            self._send(404, {"error": "usuário não existe"})
            return
        rows = db.execute(
            conn, "SELECT * FROM spots WHERE user_id = ? ORDER BY created_at DESC", (user["id"],)
        ).fetchall()
        conn.close()
        try:
            lat = float(query.get("lat", [""])[0]) if query.get("lat") else None
            lng = float(query.get("lng", [""])[0]) if query.get("lng") else None
        except (ValueError, IndexError):
            raise ValueError("lat/lng inválidos")
        spots = _bulk_public(rows, viewer["id"] if viewer else None, lat, lng)
        pub = _public_user(user, viewer["id"] if viewer else None)
        pub["spots"] = spots
        self._send(200, pub)

    def api_follow(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        try:
            target = int(urlparse(self.path).path.strip("/").split("/")[-2])
        except ValueError:
            raise ValueError("id inválido")
        if target == user["id"]:
            raise ValueError("você não pode seguir a si mesmo")
        conn = db.connect()
        if not db.execute(conn, "SELECT 1 FROM users WHERE id = ?", (target,)).fetchone():
            conn.close()
            raise ValueError("usuário não existe")
        existing = db.execute(
            conn, "SELECT 1 FROM follows WHERE follower_id = ? AND followee_id = ?", (user["id"], target)
        ).fetchone()
        if existing:
            db.execute(
                conn, "DELETE FROM follows WHERE follower_id = ? AND followee_id = ?", (user["id"], target)
            )
            following = False
        else:
            db.execute(
                conn, "INSERT INTO follows (follower_id, followee_id) VALUES (?, ?)", (user["id"], target)
            )
            following = True
            db.execute(
                conn,
                "INSERT INTO notifications (user_id, actor_id, type, text) VALUES (?, ?, 'follow', 'começou a seguir você')",
                (target, user["id"]),
            )
        conn.commit()
        count = db.execute(conn, "SELECT COUNT(*) FROM follows WHERE followee_id = ?", (target,)).fetchone()[0]
        conn.close()
        self._send(200, {"following": following, "followers": count})

    def api_search(self, query):
        q = (query.get("q", [""])[0] or "").strip()
        if len(q) < 1:
            raise ValueError("busca vazia")
        if len(q) > 60:
            raise ValueError("busca muito longa")
        viewer = get_user_by_token(self._get_token())
        try:
            lat = float(query.get("lat", [""])[0]) if query.get("lat") else None
            lng = float(query.get("lng", [""])[0]) if query.get("lng") else None
        except (ValueError, IndexError):
            raise ValueError("lat/lng inválidos")
        like = f"%{q}%"
        conn = db.connect()
        urows = db.execute(
            conn, "SELECT * FROM users WHERE lower(username) LIKE lower(?) LIMIT 10", (like,)
        ).fetchall()
        srows = db.execute(
            conn,
            "SELECT * FROM spots WHERE lower(name) LIKE lower(?) OR lower(description) LIKE lower(?) LIMIT 10",
            (like, like),
        ).fetchall()
        conn.close()
        users = [
            {"id": r["id"], "username": r["username"], "bio": r["bio"] or "", "avatar": r["avatar"] or ""}
            for r in urows
        ]
        spots = _bulk_public(srows, viewer["id"] if viewer else None, lat, lng)
        self._send(200, {"users": users, "spots": spots})

    def api_notifications(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        conn = db.connect()
        rows = db.execute(
            conn,
            """SELECT n.id, n.type, n.text, n.read, n.created_at, n.spot_id,
                      u.username AS actor, s.name AS spot_name
               FROM notifications n
               LEFT JOIN users u ON u.id = n.actor_id
               LEFT JOIN spots s ON s.id = n.spot_id
               WHERE n.user_id = ?
               ORDER BY n.created_at DESC, n.id DESC LIMIT 50""",
            (user["id"],),
        ).fetchall()
        unread = db.execute(
            conn, "SELECT COUNT(*) FROM notifications WHERE user_id = ? AND read = 0", (user["id"],)
        ).fetchone()[0]
        conn.close()
        notifs = [
            {
                "id": r["id"], "type": r["type"], "text": r["text"], "read": bool(r["read"]),
                "created_at": r["created_at"], "spot_id": r["spot_id"],
                "actor": r["actor"] or "?", "spot_name": r["spot_name"],
            }
            for r in rows
        ]
        self._send(200, {"notifications": notifs, "unread": unread})

    def api_notifications_read(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        conn = db.connect()
        db.execute(conn, "UPDATE notifications SET read = 1 WHERE user_id = ?", (user["id"],))
        conn.commit()
        conn.close()
        self._send(200, {"ok": True})

    def api_report(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        if _rate_limited(f"rep:{self._client_ip()}"):
            self._send(429, {"error": "muitas denúncias, aguarde um pouco"})
            return
        spot_id = self._spot_id_from_path()
        data = self._read_json()
        reason = (data.get("reason") or "").strip()
        if not reason:
            raise ValueError("informe um motivo")
        if len(reason) > 500:
            raise ValueError("motivo muito longo")
        conn = db.connect()
        if not db.execute(conn, "SELECT 1 FROM spots WHERE id = ?", (spot_id,)).fetchone():
            conn.close()
            raise ValueError("spot não existe")
        db.execute(conn, "INSERT INTO reports (reporter_id, spot_id, reason) VALUES (?, ?, ?)", (user["id"], spot_id, reason))
        conn.commit()
        conn.close()
        self._send(201, {"ok": True})

    def api_delete_spot(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        try:
            spot_id = int(urlparse(self.path).path.strip("/").split("/")[-1])
        except ValueError:
            raise ValueError("id inválido")
        conn = db.connect()
        spot = db.execute(conn, "SELECT id, user_id FROM spots WHERE id = ?", (spot_id,)).fetchone()
        if not spot:
            conn.close()
            raise ValueError("spot não existe")
        if spot["user_id"] != user["id"]:
            conn.close()
            self._send(403, {"error": "você só pode excluir suas próprias fotos"})
            return
        db.execute(conn, "DELETE FROM spots WHERE id = ?", (spot_id,))
        conn.commit()
        conn.close()
        self._send(200, {"ok": True})

    def _parse_credentials(self):
        data = self._read_json()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        return username, password, data

    def api_register(self):
        if _rate_limited(f"reg:{self._client_ip()}"):
            self._send(429, {"error": "muitas tentativas, aguarde um pouco"})
            return
        data = self._read_json()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        if not (4 <= len(username) <= 24):
            raise ValueError("username deve ter entre 4 e 24 caracteres")
        if len(password) < 4:
            raise ValueError("senha deve ter pelo menos 4 caracteres")
        conn = db.connect()
        if db.execute(conn, "SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            conn.close()
            raise ValueError("username já existe")
        user_id = db.insert_id(
            conn,
            "INSERT INTO users (username, password_hash) VALUES (?, ?)",
            (username, hash_password(password)),
        )
        _prune_sessions(conn, user_id)
        token = secrets.token_hex(32)
        db.execute(conn, "INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user_id))
        conn.commit()
        conn.close()
        self.pending_cookie = f"token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_MAX_DAYS * 86400}"
        if self._secure():
            self.pending_cookie += "; Secure"
        self._send(201, {"token": token, "username": username})

    def api_login(self):
        if _rate_limited(f"login:{self._client_ip()}"):
            self._send(429, {"error": "muitas tentativas, aguarde um pouco"})
            return
        data = self._read_json()
        username = (data.get("username") or "").strip()
        password = data.get("password") or ""
        conn = db.connect()
        user = db.execute(conn, "SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        if not user or not verify_password(password, user["password_hash"]):
            conn.close()
            raise ValueError("credenciais inválidas")
        _prune_sessions(conn, user["id"])
        token = secrets.token_hex(32)
        db.execute(conn, "INSERT INTO sessions (token, user_id) VALUES (?, ?)", (token, user["id"]))
        conn.commit()
        conn.close()
        self.pending_cookie = f"token={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={SESSION_MAX_DAYS * 86400}"
        if self._secure():
            self.pending_cookie += "; Secure"
        self._send(200, {"token": token, "username": username})

    def api_logout(self):
        token = self._get_token()
        if token:
            conn = db.connect()
            db.execute(conn, "DELETE FROM sessions WHERE token = ?", (token,))
            conn.commit()
            conn.close()
        self.pending_cookie = "token=; Max-Age=0; Path=/"
        self._send(200, {})

    def api_spots(self, query):
        viewer = get_user_by_token(self._get_token())
        viewer_id = viewer["id"] if viewer else None
        try:
            lat = float(query.get("lat", [""])[0]) if query.get("lat") else None
            lng = float(query.get("lng", [""])[0]) if query.get("lng") else None
        except (ValueError, IndexError):
            raise ValueError("lat/lng inválidos")
        limit = DEFAULT_SPOT_LIMIT
        if query.get("limit"):
            try:
                limit = max(1, min(int(query["limit"][0]), MAX_SPOT_LIMIT))
            except ValueError:
                raise ValueError("limit inválido")
        feed_following = (query.get("feed") or [""])[0] == "following"
        conn = db.connect()
        if feed_following and viewer_id:
            rows = db.execute(
                conn,
                """SELECT sp.* FROM spots sp
                   JOIN follows f ON f.followee_id = sp.user_id AND f.follower_id = ?
                   ORDER BY sp.created_at DESC LIMIT ?""",
                (viewer_id, limit),
            ).fetchall()
        else:
            rows = db.execute(
                conn, "SELECT * FROM spots ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        conn.close()
        spots = _bulk_public(rows, viewer_id, lat, lng)
        if lat is None or lng is None:
            spots = [dict(s, unlocked=None, distance_m=None) for s in spots]
        self._send(200, {"spots": spots, "radius_m": DEFAULT_RADIUS_M, "has_more": False})

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
        photo = data.get("photo") or ""
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
        if not photo.startswith("data:image"):
            raise ValueError("foto inválida (use uma imagem)")
        meta, payload = photo.split(",", 1)
        mime = "png" if "png" in meta else ("webp" if "webp" in meta else "jpeg")
        try:
            raw = base64.b64decode(payload, validate=True)
        except Exception:
            raise ValueError("foto inválida (base64 quebrado)")
        if len(raw) > MAX_IMAGE_BYTES:
            raise ValueError("foto muito grande (máx 6MB)")
        conn = db.connect()
        spot_id = db.insert_id(
            conn,
            """INSERT INTO spots (user_id, name, description, lat, lng, photo_b64, photo_mime, radius_m)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user["id"], name, description, lat, lng, payload, mime, radius),
        )
        spot = db.execute(conn, "SELECT * FROM spots WHERE id = ?", (spot_id,)).fetchone()
        conn.close()
        self._send(201, {"spot": public_spot(spot, user["id"])})

    def _spot_id_from_path(self):
        parts = urlparse(self.path).path.strip("/").split("/")
        return int(parts[-2])

    def api_spot_photo(self, query):
        viewer = get_user_by_token(self._get_token())
        try:
            spot_id = self._spot_id_from_path()
            lat = float(query.get("lat", [""])[0]) if query.get("lat") else None
            lng = float(query.get("lng", [""])[0]) if query.get("lng") else None
        except (ValueError, IndexError):
            raise ValueError("lat/lng inválidos")
        conn = db.connect()
        spot = db.execute(conn, "SELECT * FROM spots WHERE id = ?", (spot_id,)).fetchone()
        conn.close()
        if not spot:
            self._send(404, {"error": "não existe"})
            return
        is_author = viewer is not None and viewer["id"] == spot["user_id"]
        if not is_author:
            if lat is None or lng is None:
                self._send(403, {"error": "locked"})
                return
            if haversine_m(lat, lng, spot["lat"], spot["lng"]) > spot["radius_m"]:
                self._send(403, {"error": "locked"})
                return
        try:
            raw = base64.b64decode(spot["photo_b64"])
        except Exception:
            raw = b""
        self._send(200, raw, content_type=f"image/{spot['photo_mime']}")

    def api_like(self):
        user = get_user_by_token(self._get_token())
        if not user:
            self._send(401, {"error": "faça login primeiro"})
            return
        spot_id = self._spot_id_from_path()
        conn = db.connect()
        spot = db.execute(conn, "SELECT id, user_id FROM spots WHERE id = ?", (spot_id,)).fetchone()
        if not spot:
            conn.close()
            raise ValueError("spot não existe")
        existing = db.execute(
            conn, "SELECT 1 FROM likes WHERE spot_id = ? AND user_id = ?", (spot_id, user["id"])
        ).fetchone()
        if existing:
            db.execute(conn, "DELETE FROM likes WHERE spot_id = ? AND user_id = ?", (spot_id, user["id"]))
            liked = False
        else:
            db.execute(conn, "INSERT INTO likes (spot_id, user_id) VALUES (?, ?)", (spot_id, user["id"]))
            liked = True
            if spot["user_id"] != user["id"]:
                db.execute(
                    conn,
                    "INSERT INTO notifications (user_id, actor_id, type, spot_id, text) VALUES (?, ?, 'like', ?, 'curtiu sua foto')",
                    (spot["user_id"], user["id"], spot_id),
                )
        conn.commit()
        count = db.execute(conn, "SELECT COUNT(*) FROM likes WHERE spot_id = ?", (spot_id,)).fetchone()[0]
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
        conn = db.connect()
        spot = db.execute(conn, "SELECT id, user_id FROM spots WHERE id = ?", (spot_id,)).fetchone()
        if not spot:
            conn.close()
            raise ValueError("spot não existe")
        db.execute(conn, "INSERT INTO comments (spot_id, user_id, text) VALUES (?, ?, ?)", (spot_id, user["id"], text))
        if spot["user_id"] != user["id"]:
            snippet = (text[:100] + "…") if len(text) > 100 else text
            db.execute(
                conn,
                "INSERT INTO notifications (user_id, actor_id, type, spot_id, text) VALUES (?, ?, 'comment', ?, ?)",
                (spot["user_id"], user["id"], spot_id, f"comentou: {snippet}"),
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
            ".json": "application/json; charset=utf-8",
            ".webmanifest": "application/manifest+json; charset=utf-8",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".webp": "image/webp",
        }.get(ext, "application/octet-stream")
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main():
    db.init()
    port = int(os.environ.get("PORT", 8000))
    host = os.environ.get("HOST", "0.0.0.0")
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"NearGram rodando em http://{host}:{port} (db: {'postgres' if db.PG else 'sqlite'})")
    server.serve_forever()


if __name__ == "__main__":
    main()
