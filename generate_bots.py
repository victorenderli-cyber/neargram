#!/usr/bin/env python3
"""
Script to create realistic bot users with photos for NearGram.

Cria bots que parecem usuários comuns: avatar de pessoa real (pravatar.cc), nome de
usuário realista (nome + sobrenome + dígitos), bio variada, e fotos de paisagens do
lugar onde "estão" (LoremFlickr com palavra-chave do ponto turístico da cidade).

Uso: python generate_bots.py [opções]

Opções:
  --count N          Número de bots a serem criados (padrão: 20)
  --password PASS    Senha para as contas dos bots (padrão: botpass)
  --dry-run          Apenas imprime o que seria feito, não executa
  --help             Mostra esta ajuda

O script detecta DATABASE_URL para Postgres, senão usa SQLite.
"""

import os
import sys
import json
import random
import re
import math
import base64
import urllib.request
from datetime import datetime, timedelta

import db
import server
from server import hash_password

# ---------------------------------------------------------------------------
# Dados realistas
# ---------------------------------------------------------------------------

FIRST_NAMES = {
    "US": ["alex", "jordan", "taylor", "morgan", "casey", "dakota", "riley", "lea", "skyler", "quinn", "chloe", "nathan", "emma", "lucas"],
    "EU": ["luca", "sofia", "giovanni", "emma", "leo", "mia", "noah", "olivia", "lukas", "hanna", "liam", "sophie", "jannis", "elena", "thomas"],
    "Asia": ["yuki", "kenji", "mei", "sophia", "raj", "ming", "akira", "arjun", "priya", "kenji", "mei", "hana", "li", "taro", "aki"],
    "LatAm": ["juan", "maria", "carlos", "ana", "luis", "sofia", "pedro", "camila", "diego", "valentina", "isabella", "mateo", "luciana", "gabriel"],
    "Africa": ["kwame", "amar", "fatima", "nous", "tunde", "adelak", "namba", "zena", "mulenga", "sarah", "motsoa", "okoro", "juma", "amara"],
    "Oceania": ["jack", "ruby", "liam", "charlie", "ava", "ethan", "isla", "noah", "ollie", "paisley", "mako"],
}

LAST_NAMES = {
    "US": ["smith", "johnson", "williams", "brown", "jones", "miller", "davis", "garcia", "rodriguez", "wilson", "martinez", "anderson"],
    "EU": ["rossi", "muller", "silva", "schmidt", "garcia", "martin", "klein", "wagner", "bernard", "moreau", "petit"],
    "Asia": ["tanaka", "sato", "suzuki", "takahashi", "chen", "li", "wang", "zhang", "kumar", "singh", "lim", "ng", "kim"],
    "LatAm": ["gomez", "torres", "ramirez", "flores", "gonzalez", "pereira", "souza", "oliveira", "castro", "ferreira", "ruiz", "vega"],
    "Oceania": ["smith", "jones", "williams", "mcewan", "walker", "roberts", "clarke", "hughes", "murray", "reed"],
    "Africa": ["mensah", "okafor", "ouattara", "sow", "ahmed", "diallo", "mohammed", "kamara", "wambui", "adeyemi"],
}

# bios variadas por tema
BIOS = {
    "travel": [
        "Explorando o mundo, uma foto de cada vez. Cada lugar tem uma história para contar.",
        "Fotógrafo amador em tempo parcial, amante de café e mochilão.",
        "Vi mais coisas do que a maioria vê em uma vida. Uma câmera na mão por aí.",
        "Caçando momentos perdidos em estradas desconhecidas.",
        "Cada cidade nova é uma página em branco. Vou preenchendo com luz.",
    ],
    "nightlife": [
        "Baladas, bares e festas — a cidade que moro. Amo uma pista de dança.",
        "Caçando os melhores som e bares escondidos pela noite.",
        "Viciado em música, comida e noitadas bem vividas.",
        "Do pôr do sol ao amanhecer, sempre tem um bom rolê.",
        "Vivendo a vida uma festa de cada vez.",
    ],
    "food": [
        "Gourmet em tempo parcial, atrás dos melhores chefs e recepções escondidas.",
        "Viciado em comida, amante de street food e cafés de sábado.",
        "Caçando o melhor ramen, taco, pastel e sobremesa da cidade.",
        "Foodie: brunch, cerveja artesanal e cafés especiais são meu fraco.",
        "Se tem comida boa, eu acho. Se não tem, eu invento.",
    ],
    "nature": [
        "Observador de aves, ávido por trilhas, montanhas e pôr do sol.",
        "Fotógrafo de natureza em busca de luz e silêncio.",
        "Caçando aurora boreal, cachoeiras e desertos.",
        "Fotógrafo de vida selvagem, amante de safáris, cânions e recifes.",
        "O ar livre é minha galeria. Natureza sempre tem a melhor foto.",
    ],
    "tech": [
        "Desenvolvedor à noite, entusiasta de gadgets e viagens.",
        "Codifico, prototipo e aprendo sobre IA o tempo todo.",
        "Computação em nuvem e cafés geek. Meetups são meu passeio.",
        "Web dev de laptop na mão, apaixonado por mapas e APIs de localização.",
        "Programador full stack, viciado em tecnologia e startups.",
    ],
    "arts": [
        "Estudante de arte, apreciador de museus e grafite.",
        "Design gráfico, apaixonado por instalações contemporâneas.",
        "Amante de cinema e festivais independentes.",
        "Fotógrafo e designer, artista de collage.",
        "Pintor e escultor, viciado em arte urbana e galerias de rua.",
    ],
    "local": [
        "Vivo aqui há anos e ainda me surpreendo com cada esquina.",
        "Creículo da cidade — peço street pra todo mundo só ir.",
        "Amo lugares que só quem mora aqui conhecer.",
        "Exploro minha própria cidade como se fosse turista.",
    ],
}

# Cidades com pontos turísticos REAIS (palavras-chave do LoremFlickr)
CITIES = [
    # US
    {"region": "US", "city": "São Francisco", "lat": 37.7749, "lng": -122.4194, "spots": [
        ("Golden Gate", "golden-gate-bridge"), ("Fisherman's Wharf", "san-francisco"), ("Alcatraz", "alcatraz-island")]},
    {"region": "US", "city": "Nova York", "lat": 40.7128, "lng": -74.0060, "spots": [
        ("Central Park", "central-park-new-york"), ("Brooklyn Bridge", "brooklyn-bridge"), ("Times Square", "times-square")]},
    {"region": "US", "city": "Los Angeles", "lat": 34.0522, "lng": -118.2437, "spots": [
        ("Santa Monica Pier", "santa-monica-pier"), ("Hollywood", "hollywood-boulevard"), ("Venice Beach", "venice-beach")]},
    {"region": "US", "city": "Chicago", "lat": 41.8781, "lng": -87.6298, "spots": [
        ("Millennium Park", "millennium-park"), ("Navy Pier", "navy-pier"), ("Chicago River", "chicago-river")]},
    # EU
    {"region": "EU", "city": "Paris", "lat": 48.8566, "lng": 2.3522, "spots": [
        ("Torre Eiffel", "eiffel-tower"), ("Sena", "seine-river"), ("Montmartre", "montmartre-paris")]},
    {"region": "EU", "city": "Londres", "lat": 51.5074, "lng": -0.1278, "spots": [
        ("Big Ben", "big-ben"), ("London Eye", "london-eye"), ("Tower Bridge", "tower-bridge")]},
    {"region": "EU", "city": "Berlim", "lat": 52.5200, "lng": 13.4050, "spots": [
        ("Portão de Brandemburgo", "brandenburg-gate"), ("Muro de Berlin", "berlin-wall"), ("Reichstag", "reichstag")]},
    {"region": "EU", "city": "Roma", "lat": 41.8955, "lng": 12.4823, "spots": [
        ("Coliseu", "colosseum-rome"), ("Panteão", "pantheon-rome"), ("Fonte de Trevi", "trevi-fountain")]},
    {"region": "EU", "city": "Amsterdã", "lat": 52.3676, "lng": 4.9041, "spots": [
        ("Vondelpark", "vondelpark"), ("Canais de Amsterdam", "amsterdam-canals"), ("Museu Van Gogh", "van-gogh-museum")]},
    # Asia
    {"region": "Asia", "city": "Tóquio", "lat": 35.6762, "lng": 139.6503, "spots": [
        ("Torre de Tóquio", "tokyo-tower"), ("Shibuya", "shibuya-crossing"), ("Templo Sensoji", "sensoji-temple")]},
    {"region": "Asia", "city": "Xangai", "lat": 31.2304, "lng": 121.4737, "spots": [
        ("Bund", "the-bund-shanghai"), ("Torre de Xangai", "shanghai-tower"), ("Jardim Yu", "yu-garden")]},
    {"region": "Asia", "city": "Mumbai", "lat": 19.0760, "lng": 72.8777, "spots": [
        ("Gateway of India", "gateway-of-india"), ("Marine Drive", "marine-drive"), ("Taj Mahal Palace", "taj-mahal-palace")]},
    {"region": "Asia", "city": "Singapura", "lat": 1.3521, "lng": 103.8198, "spots": [
        ("Gardens by the Bay", "gardens-by-the-bay"), ("Marina Bay", "marina-bay-singapore"), ("Sentosa", "sentosa-island")]},
    {"region": "Asia", "city": "Seul", "lat": 37.5665, "lng": 126.9780, "spots": [
        ("Palacio Gyeongbokgung", "gyeongbokgung"), ("Torre N Seoul", "n-seoul-tower"), ("Rio Han", "han-river-seoul")]},
    # LatAm
    {"region": "LatAm", "city": "São Paulo", "lat": -23.5505, "lng": -46.6333, "spots": [
        ("Av. Paulista", "paulista-avenue"), ("Parque do Ibirapuera", "ibirapuera-park"), ("Mercadão", "mercado-municipal-sao-paulo")]},
    {"region": "LatAm", "city": "Buenos Aires", "lat": -34.6037, "lng": -58.3816, "spots": [
        ("Obelisco", "obelisco-buenos-aires"), ("Caminho La Boca", "la-boca-buenos-aires"), ("Recoleta", "recoleta-buenos-aires")]},
    {"region": "LatAm", "city": "Santiago", "lat": -33.4489, "lng": -70.6693, "spots": [
        ("Cerro San Cristóbal", "cerro-san-cristobal"), ("Plaza de Armas", "plaza-de-armas-santiago"), ("Costanera", "costanera-center")]},
    {"region": "LatAm", "city": "Rio de Janeiro", "lat": -22.9068, "lng": -43.1729, "spots": [
        ("Cristo Redentor", "cristo-redentor"), ("Pão de Açúcar", "pao-de-acucar"), ("Praia de Copacabana", "copacabana-beach")]},
    {"region": "LatAm", "city": "Salvador", "lat": -12.9714, "lng": -38.5014, "spots": [
        ("Pelourinho", "pelourinho-salvador"), ("Praia da Barra", "barra-beach"), ("Faro da Barra", "faro-da-barra")]},
    # Africa
    {"region": "Africa", "city": "Cidade do Cabo", "lat": -33.9249, "lng": 18.4241, "spots": [
        ("Table Mountain", "table-mountain"), ("Cabo da Boa Esperança", "cape-of-good-hope"), ("V&A Waterfront", "va-waterfront")]},
    {"region": "Africa", "city": "Lagos", "lat": 6.5244, "lng": 3.3792, "spots": [
        ("Ilha Vitoria", "victoria-island-lagos"), ("Lekki", "lekki-lagos"), ("Porto de Lagos", "lagos-harbor")]},
    # Oceania
    {"region": "Oceania", "city": "Sydney", "lat": -33.8688, "lng": 151.2093, "spots": [
        ("Ópera de Sydney", "sydney-opera-house"), ("Bondi Beach", "bondi-beach"), ("Harbour Bridge", "sydney-harbour-bridge")]},
    {"region": "Oceania", "city": "Auckland", "lat": -36.8485, "lng": 174.7633, "spots": [
        ("Sky Tower", "sky-tower-auckland"), ("Devonport", "devonport-auckland"), ("Viaduct Harbour", "viaduct-harbour")]},
{"region": "Oceania", "city": "Brisbane", "lat": -27.4698, "lng": 153.0251, "spots": [
        ("South Bank", "south-bank-brisbane"), ("Centro de Brisbane", "brisbane-city"), ("Rio Brisbane", "brisbane-river")]},
]
# Palavras-chave extras por tema para variar as fotos
THEME_KEYWORDS = {
    "travel": ["landscape", "travel", "skyline"],
    "nightlife": ["night", "neon", "city-lights"],
    "food": ["street-food", "restaurant", "coffee"],
    "nature": ["park", "nature", "sunset"],
    "tech": ["architecture", "city", "skyline"],
    "arts": ["street-art", "museum", "gallery"],
    "local": ["city", "street", "neighborhood"],
}

DESCRIPTIONS = [
    "Um lugar incrível que precisava dividir por aqui.",
    "Passei por aqui hoje e não deu para não registrar.",
    "Essa vista é a minha favorita da cidade.",
    "Encontrei esse cantinho por acaso, recomendo demais.",
    "Registro do dia por aqui. Vale a visita.",
    "Depois de muito andar, achei esse lugar perfeito.",
    "Fica logo ali, mas muita gente nunca reparou.",
    "A luz estava perfeita, tive que fotografar.",
]


def _unique_username(region):
    """Gera um username realista e único (nome.sobrenome + dígitos)."""
    for _ in range(100):
        first = random.choice(FIRST_NAMES[region])
        last = random.choice(LAST_NAMES[region]).replace(" ", "")
        base = f"{first}_{last}"
        suffix = str(random.randint(10, 999))
        candidate = f"{base}_{suffix}"[:24]
        if re.fullmatch(r"[A-Za-z0-9_]{4,24}", candidate):
            return candidate
    return f"user_{random.randint(100000, 999999)}"


def _avatar_url(username):
    """Avatar de pessoa real, determinístico por username (pravatar.cc)."""
    seed = abs(hash(username)) % 70
    return f"https://i.pravatar.cc/256?img={seed}"


def _spot_photo_url(city_entry, landmark_keyword, theme):
    """Foto real de paisagem do lugar específico (LoremFlickr)."""
    parts = [landmark_keyword]
    extra = random.choice(THEME_KEYWORDS.get(theme, ["city"]))
    if extra not in parts:
        parts.append(extra)
    query = ",".join(parts)
    lock = abs(hash(landmark_keyword + theme)) % 2000
    return f"https://loremflickr.com/800/600/{query}?lock={lock}"


class BotGenerator:
    def __init__(self, password, dry_run=False):
        self.password = password
        self.dry_run = dry_run
        self.created_users = []
        self.created_spots = []
        self.created_follows = []

    def run(self, count=20):
        if not self.dry_run:
            try:
                conn = db.connect()
                conn.close()
                db.init()
                print("Banco de dados inicializado com sucesso.")
            except Exception as e:
                print(f"Aviso: não foi possível inicializar o banco de dados: {e}")
                print("Continuando sem persistir os bots...")
                self.dry_run = True

        for i in range(count):
            city = random.choice(CITIES)
            region = city["region"]
            theme = random.choice(list(BIOS.keys()))
            username = _unique_username(region)
            if self.dry_run:
                self.created_users.append(username)
                print(f"Dry-run {i+1}/{count}: @{username} ({city['city']}) tema={theme}")
                for name, kw in random.sample(city["spots"], 2):
                    self.created_spots.append((username, name, (city["lat"], city["lng"])))
                continue

            user_id = self._insert_user(username, self.password, theme)
            if not user_id:
                continue

            spots = self._generate_spots(user_id, city, theme, count=random.randint(2, 3))
            for spot in spots:
                self.created_spots.append((user_id, spot["name"], (spot["lat"], spot["lng"])))

            if random.random() < 0.4 and self.created_users:
                target = random.choice([u for u in self.created_users if u != user_id] or [None])
                if target is not None:
                    self._insert_follow(user_id, target)
                    self.created_follows.append((user_id, target))

            self.created_users.append(user_id)

        self._summary()

    def _insert_user(self, username, password, theme):
        conn = db.connect()
        try:
            row = db.execute(conn, "SELECT 1 FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()
            if row:
                print(f"  -> @{username} já existe, ignorando")
                return None
            password_hash = hash_password(password)
            bio = random.choice(BIOS[theme])
            avatar = _avatar_url(username)
            user_id = db.insert_id(
                conn,
                "INSERT INTO users (username, password_hash, bio, avatar) VALUES (?, ?, ?, ?)",
                (username, password_hash, bio, avatar),
            )
            conn.commit()
            print(f"  -> Criado usuário ID {user_id}: @{username} ({theme}) avatar={avatar}")
            return user_id
        except Exception as e:
            print(f"  -> Erro ao criar usuário {username}: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def _generate_spots(self, user_id, city, theme, count=2):
        spots = []
        chosen = random.sample(city["spots"], min(count, len(city["spots"])))
        for name, kw in chosen:
            lat = city["lat"] + random.uniform(-0.02, 0.02)
            lng = city["lng"] + random.uniform(-0.02, 0.02)
            photo = _spot_photo_url(city, kw, theme)
            desc = random.choice(DESCRIPTIONS)
            radius = random.randint(200, 2000)
            spot_id = self._insert_spot(user_id, name, desc, lat, lng, photo, radius)
            if spot_id:
                spots.append({"id": spot_id, "lat": lat, "lng": lng, "name": name, "photo": photo})
        return spots

    def _insert_spot(self, user_id, name, description, lat, lng, photo, radius_m):
        conn = db.connect()
        try:
            mime = "jpeg"
            spot_id = db.insert_id(
                conn,
                """INSERT INTO spots (user_id, name, description, lat, lng, photo_b64, photo_mime, radius_m)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (user_id, name, description, lat, lng, photo, mime, radius_m),
            )
            conn.commit()
            print(f"    -> Spot ID {spot_id}: {name}")
            return spot_id
        except Exception as e:
            print(f"    -> Erro ao criar spot: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def _insert_follow(self, follower_id, followee_id):
        conn = db.connect()
        try:
            db.execute(conn, "INSERT INTO follows (follower_id, followee_id) VALUES (?, ?)", (follower_id, followee_id))
            conn.commit()
            print(f"    -> {follower_id} segue {followee_id}")
        except Exception as e:
            print(f"    -> Erro ao criar follow: {e}")
            conn.rollback()
        finally:
            conn.close()

    def _summary(self):
        print("\n=== RESUMO ===")
        print(f"Usuários criados: {len(self.created_users)}")
        print(f"Spots criados: {len(self.created_spots)}")
        print(f"Follows criados: {len(self.created_follows)}")
        for uid, name, (lat, lng) in self.created_spots:
            print(f"  - Spot por {uid}: '{name}' ({lat:.4f}, {lng:.4f})")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gera contas de bots realistas para NearGram.")
    parser.add_argument("--count", type=int, default=20, help="Número de bots a serem criados (padrão: 20)")
    parser.add_argument("--password", type=str, default="botpass", help="Senha para as contas dos bots (padrão: botpass)")
    parser.add_argument("--dry-run", action="store_true", help="Apenas imprime o que seria feito")
    args = parser.parse_args()

    generator = BotGenerator(password=args.password, dry_run=args.dry_run)
    generator.run(count=args.count)
