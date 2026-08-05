import json
import os
import shutil
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request

import db
import server

PNG = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="


class ApiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._tmp = tempfile.mkdtemp()
        db.DB_PATH = os.path.join(cls._tmp, "test.db")
        db.PG = False
        db.init()
        cls.srv = server.ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.srv.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        cls.srv.server_close()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self):
        with server._rate_limit_lock:
            server._rate_limit_buckets.clear()

    def call(self, path, method="GET", body=None, cookie=None):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if cookie:
            req.add_header("Cookie", cookie)
        try:
            r = urllib.request.urlopen(req, timeout=10)
            return r.status, dict(r.headers), self._parse(r.headers, r.read())
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), self._parse(e.headers, e.read())

    @staticmethod
    def _parse(headers, raw):
        ct = headers.get("Content-Type", "")
        if "application/json" in ct:
            try:
                return json.loads(raw or b"{}")
            except ValueError:
                return {}
        return raw

    def cookie_of(self, headers):
        set_cookie = headers.get("Set-Cookie", "")
        return set_cookie.split(";")[0]

    def register(self, username, password="senha123"):
        status, headers, data = self.call("/api/register", "POST", {"username": username, "password": password})
        self.assertEqual(status, 201)
        return self.cookie_of(headers)

    def test_01_register_and_me(self):
        cookie = self.register("alice")
        status, _, data = self.call("/api/me", cookie=cookie)
        self.assertEqual(status, 200)
        self.assertEqual(data["user"]["username"], "alice")

    def test_02_duplicate_username(self):
        self.register("bobby")
        status, _, data = self.call("/api/register", "POST", {"username": "bobby", "password": "senha123"})
        self.assertEqual(status, 400)
        self.assertIn("já existe", data["error"])

    def test_03_wrong_password(self):
        self.register("carol")
        status, _, data = self.call("/api/login", "POST", {"username": "carol", "password": "errada"})
        self.assertEqual(status, 400)
        self.assertIn("credenciais", data["error"])

    def test_04_login_ok(self):
        self.register("dave")
        status, headers, data = self.call("/api/login", "POST", {"username": "dave", "password": "senha123"})
        self.assertEqual(status, 200)
        self.assertIn("Max-Age", headers.get("Set-Cookie", ""))
        self.assertEqual(data["username"], "dave")

    def test_05_create_and_list_spot(self):
        cookie = self.register("erin")
        status, _, data = self.call(
            "/api/spots", "POST",
            {"name": "Cristo", "lat": -22.9519, "lng": -43.2105, "photo": PNG, "radius_m": 500},
            cookie,
        )
        self.assertEqual(status, 201)
        spot_id = data["spot"]["id"]
        status, _, data = self.call("/api/spots?lat=-22.9519&lng=-43.2105")
        self.assertEqual(status, 200)
        spot = next((s for s in data["spots"] if s["id"] == spot_id), None)
        self.assertIsNotNone(spot)
        self.assertIs(spot["unlocked"], True)
        status, _, data = self.call("/api/spots?lat=0&lng=0")
        far = next((s for s in data["spots"] if s["id"] == spot_id), None)
        self.assertIs(far["unlocked"], False)

    def test_06_photo_locked_for_strangers(self):
        cookie = self.register("fiona")
        _, _, create = self.call(
            "/api/spots", "POST",
            {"name": "Torre", "lat": -22.9519, "lng": -43.2105, "photo": PNG, "radius_m": 500},
            cookie,
        )
        spot_id = create["spot"]["id"]
        status, _, _ = self.call(f"/api/spots/{spot_id}/photo?lat=0&lng=0")
        self.assertEqual(status, 403)
        status, _, _ = self.call(f"/api/spots/{spot_id}/photo?lat=-22.9519&lng=-43.2105")
        self.assertEqual(status, 200)

    def test_07_like_comment_profile_delete(self):
        author = self.register("frank")
        _, _, create = self.call(
            "/api/spots", "POST",
            {"name": "Praia", "lat": -23.0, "lng": -44.0, "photo": PNG, "radius_m": 500},
            author,
        )
        spot_id = create["spot"]["id"]
        fan = self.register("grace")
        status, _, data = self.call(f"/api/spots/{spot_id}/like", "POST", {}, fan)
        self.assertEqual(status, 200)
        self.assertTrue(data["liked"])
        self.assertEqual(data["like_count"], 1)
        status, _, data = self.call(f"/api/spots/{spot_id}/comments", "POST", {"text": "massa!"}, fan)
        self.assertEqual(status, 201)
        status, _, data = self.call(f"/api/spots/{spot_id}/comments", "POST", {"text": "a" * 501}, fan)
        self.assertEqual(status, 400)
        status, _, profile = self.call("/api/profile", cookie=author)
        self.assertEqual(status, 200)
        self.assertEqual(profile["stats"]["spots"], 1)
        self.assertEqual(profile["stats"]["likes"], 1)
        self.assertEqual(profile["stats"]["comments"], 1)
        self.assertEqual(len(profile["spots"][0]["comments"]), 1)
        intruder = self.register("heidi")
        status, _, data = self.call(f"/api/spots/{spot_id}", "DELETE", cookie=intruder)
        self.assertEqual(status, 403)
        status, _, data = self.call(f"/api/spots/{spot_id}", "DELETE", cookie=author)
        self.assertEqual(status, 200)
        status, _, data = self.call(f"/api/spots/{spot_id}/photo?lat=-23.0&lng=-44.0")
        self.assertEqual(status, 404)

    def test_08_expired_session_is_ignored(self):
        cookie = self.register("ivyrose")
        status, _, data = self.call("/api/me", cookie=cookie)
        uid = data["user"]["id"]
        conn = db.connect()
        db.execute(
            conn,
            "INSERT INTO sessions (token, user_id, created_at) VALUES (?, ?, ?)",
            ("veryoldtoken", uid, "2000-01-01 00:00:00"),
        )
        conn.commit()
        conn.close()
        status, _, data = self.call("/api/me", cookie="token=veryoldtoken")
        self.assertEqual(status, 200)
        self.assertIsNone(data["user"])

    def test_09_rate_limit_login(self):
        self.register("mallory")
        blocked = False
        for _ in range(12):
            status, _, _ = self.call("/api/login", "POST", {"username": "mallory", "password": "errada"})
            if status == 429:
                blocked = True
        self.assertTrue(blocked)

    def test_10_profile_bio_and_avatar(self):
        cookie = self.register("natasha")
        status, _, data = self.call("/api/profile", "POST", {"bio": "Amo fotografar praias", "avatar": PNG}, cookie)
        self.assertEqual(status, 200)
        self.assertEqual(data["bio"], "Amo fotografar praias")
        self.assertEqual(data["avatar"], PNG)
        status, _, me = self.call("/api/me", cookie=cookie)
        self.assertEqual(me["user"]["bio"], "Amo fotografar praias")
        self.assertEqual(me["user"]["avatar"], PNG)
        status, _, data = self.call("/api/profile", "POST", {"bio": "x" * 201}, cookie)
        self.assertEqual(status, 400)

    def test_11_follow_and_public_profile(self):
        a = self.register("olivia")
        b = self.register("paulo")
        status, _, me_a = self.call("/api/me", cookie=a)
        status, _, me_b = self.call("/api/me", cookie=b)
        paulo_id = me_b["user"]["id"]
        status, _, data = self.call(f"/api/users/{paulo_id}/follow", "POST", {}, a)
        self.assertEqual(status, 200)
        self.assertTrue(data["following"])
        self.assertEqual(data["followers"], 1)
        status, _, pub = self.call("/api/users/paulo", cookie=b)
        self.assertEqual(status, 200)
        self.assertEqual(pub["username"], "paulo")
        self.assertEqual(pub["stats"]["followers"], 1)
        status, _, pub2 = self.call("/api/users/paulo", cookie=a)
        self.assertTrue(pub2["is_following"])
        status, _, data = self.call(f"/api/users/{me_a['user']['id']}/follow", "POST", {}, a)
        self.assertEqual(status, 400)

    def test_12_notifications_flow(self):
        a = self.register("raquel")
        b = self.register("samuel")
        _, _, me_a = self.call("/api/me", cookie=a)
        _, _, spot = self.call(
            "/api/spots", "POST",
            {"name": "Jardim", "lat": -22.9, "lng": -43.2, "photo": PNG, "radius_m": 500},
            a,
        )
        spot_id = spot["spot"]["id"]
        self.call(f"/api/users/{me_a['user']['id']}/follow", "POST", {}, b)
        self.call(f"/api/spots/{spot_id}/like", "POST", {}, b)
        self.call(f"/api/spots/{spot_id}/comments", "POST", {"text": "lindo"}, b)
        status, _, notifs = self.call("/api/notifications", cookie=a)
        self.assertEqual(status, 200)
        self.assertEqual(notifs["unread"], 3)
        types = [n["type"] for n in notifs["notifications"]]
        self.assertEqual(sorted(types), ["comment", "follow", "like"])
        status, _, _ = self.call("/api/notifications/read", "POST", {}, a)
        self.assertEqual(status, 200)
        status, _, notifs = self.call("/api/notifications", cookie=a)
        self.assertEqual(notifs["unread"], 0)

    def test_13_feed_following(self):
        a = self.register("tereza")
        b = self.register("ulisses")
        _, _, me_b = self.call("/api/me", cookie=b)
        self.call(f"/api/users/{me_b['user']['id']}/follow", "POST", {}, a)
        _, _, spot_b = self.call(
            "/api/spots", "POST",
            {"name": "Parque", "lat": -22.95, "lng": -43.21, "photo": PNG, "radius_m": 500},
            b,
        )
        _, _, spot_a = self.call(
            "/api/spots", "POST",
            {"name": "Praça", "lat": -22.95, "lng": -43.21, "photo": PNG, "radius_m": 500},
            a,
        )
        status, _, data = self.call("/api/spots?lat=-22.95&lng=-43.21&feed=following", cookie=a)
        self.assertEqual(status, 200)
        ids = {s["id"] for s in data["spots"]}
        self.assertIn(spot_b["spot"]["id"], ids)
        self.assertNotIn(spot_a["spot"]["id"], ids)
        status, _, data = self.call("/api/spots?lat=-22.95&lng=-43.21&feed=following")
        self.assertEqual(status, 200)

    def test_14_report_and_author_avatar_in_feed(self):
        a = self.register("vania")
        b = self.register("wagner")
        _, _, spot = self.call(
            "/api/spots", "POST",
            {"name": "Mirante", "lat": -22.95, "lng": -43.21, "photo": PNG, "radius_m": 500},
            a,
        )
        spot_id = spot["spot"]["id"]
        status, _, _ = self.call(f"/api/spots/{spot_id}/report", "POST", {"reason": "Foto imprópria"}, b)
        self.assertEqual(status, 201)
        status, _, _ = self.call(f"/api/spots/{spot_id}/report", "POST", {"reason": ""}, b)
        self.assertEqual(status, 400)
        status, _, data = self.call("/api/spots?lat=-22.95&lng=-43.21")
        item = next((s for s in data["spots"] if s["id"] == spot_id), None)
        self.assertIn("author_avatar", item)

    def test_15_search(self):
        a = self.register("xavier")
        self.call("/api/profile", "POST", {"bio": "Explorador urbano"}, a)
        self.call(
            "/api/spots", "POST",
            {"name": "Aquário", "lat": -22.95, "lng": -43.21, "photo": PNG, "radius_m": 500},
            a,
        )
        status, _, data = self.call("/api/search?q=" + urllib.parse.quote("aquá"))
        self.assertEqual(status, 200)
        self.assertTrue(any(s["name"] == "Aquário" for s in data["spots"]))
        status, _, data = self.call("/api/search?q=xavi")
        self.assertTrue(any(u["username"] == "xavier" for u in data["users"]))
        status, _, data = self.call("/api/search?q=zzzznada")
        self.assertEqual(data["spots"], [])
        self.assertEqual(data["users"], [])


if __name__ == "__main__":
    unittest.main()
