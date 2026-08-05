#!/usr/bin/env python3
"""
Script to create realistic bot users with photos for NearGram.

Este script cria contas de bots realistas (nomes, fotos, bios) em várias regiões do mundo
(eua, europa, asia, america latina, oceania, africa), gera fotos aleatórias via Cloudinary/Gravatar
ou usa placeholders, e publica fotos geolocalizadas para que os usuários possam seguir, curtir e interagir.

Uso: python generate_bots.py [opções]

Opções:
  --count N          Número de bots a serem criados (padrão: 50)
  --password PASS    Senha para as contas dos bots (padrão: botpass)
  --dry-run          Apenas imprime o que seria feito, não executa
  --help             Mostra esta ajuda

O script detecta DATABASE_URL para Postgres, senão usa SQLite.
"""

import os
import sys
import json
import random
import base64
from pathlib import Path
from datetime import datetime, timedelta

import db
import server
from server import hash_password

# Importante: este script deve ser executado após db.init() e com a tabela users criada.

# Nomes realistas e diversificados por região
REGIONAL_NAMES = {
    "US": [
        "alex", "jordan", "taylor", "morgan", "casey", "dakota", "lea", "riley",
        "skyler", "quinn", "christian", "jamie", "riley", "colin", "rowan"
    ],
    "EU": [
        "luca", "sofia", "giovanni", "emma", "leo", "mia", "noah", "olivia",
        "lukas", "hanna", "liam", "sophie", "jannis", "elena", "thomas"
    ],
    "Asia": [
        "yuki", "kenji", "mei", "li", "sophia", "raj", "ming", "akira", "arjun",
        "ana", "dave", "priya", "ken", "sarah", "jean"
    ],
    "LatAm": [
        "juan", "maria", "carlos", "ana", "luis", "sofia", "pedro", "camila",
        "diego", "valentina", "rodrigo", "natalia", "felipe", "isabella"
    ],
    "Africa": [
        "kwame", "amar", "fatima", "nous", "tunde", "adeleke", "khaled", "zena",
        "mulenga", "sarah", "motsoaki", "okoro", "juma"
    ],
    "Oceania": [
        "emma", "liam", "noah", "olivia", "charlie", "ava", "alex", "mia",
        "ethan", "isla", "jack", "ruby"
    ]
}

# Bios realistas e curtos
BIOS = {
    "travel": [
        "Explorando o mundo, uma foto de cada vez. Cada lugar tem uma história para contar.",
        "Fotógrafo amador em tempo parcial, amante de café e mochilão.",
        "Vi mais coisas do que a maioria das pessoas veem em uma vida inteira. 🌍📸",
        "Caçando momentos perdidos em estradas desconhecidas. 🚗✈️",
        "Cacadora de fotos e observadora de pessoas. 🌆📷",
    ],
    "nightlife": [
        "Baladas, bares e festas — cidade que eu morro. 🎵🥂",
        "DJ trainee, amante de bares escondidos e jogos de luz. 💃🕺",
        "Caçando o melhor hash nos bares da cidade. 🍂🎲",
        "Beathead em tempo parcial, amante de Friday nights. 🌙🎶",
        "Rotisseur amador, viciado em comida picante e sushi. 🍣🔥",
    ],
    "food": [
        "Gourmet em tempo parcial, explorando recepções e chefs escondidos. 👨‍🍳🥄",
        "Viciado em comida, amante de street food e chás de sábado à tarde. ☕🌶️",
        "Caçando o melhor ramen, taco e pastel. 🍜🥟🍰",
        "Rotisseur amador, viciado em comida picante e sushi. 🍣🔥",
        "Foodie em tempo parcial, amante de brunch, cerveja artesanal e cafés specialty. ☕🥐",
    ],
    "nature": [
        "Observador de aves, ávido por trilhas florestais, montanhas e pôr do sol. 🦅🌲",
        "Fotógrafo de natureza e randonneur. 🏔️📸",
        "Cacando aurora boreal, cachoeiras e desertos. 🌌🏜️",
        "Fotógrafo de vida selvagem, amante de safáris, cânions, recifes de coral. 🐘🌊",
        "Escultor em madeira e natureza, apaixonado por montanhas cobertas de neve. 🏔️🪵",
    ],
    "tech": [
        "Desenvolvedor de software à noite, entusiasta de gadgets. 💻🤖",
        "Codificando, prototipando e aprendendo sobre criptomoedas. 🪙📱",
        "Computação em nuvem, cafés geeks, meetups. ☁️🥐",
        "Web dev com laptop sempre na mão, apaixonado por API de localização. 🌐📍",
        "Programador de stack full, viciado em notebooks, buzzwords e tecnologia emergente. 💻🚀",
    ],
    "arts": [
        "Estudante de arte, apreciador de museus, entusiasta de grafite. 🎨🚶",
        "Estudante de design gráfico, apaixonado por instalações de arte contemporânea. 🎭🖼️",
        "Amante de cinema, viciado em festivais de cinema independentes. 🎬🍿",
        "Fotógrafo e designer gráfico, artista de collage. 📐📸",
        "Pintor e escultor, viciado em arte urbana e galerias de rua. 🖌️🎨",
    ]
}

# Função auxiliar para pegar coordenadas aleatórias por região
def pick_random(region_key):
    region = REGION_COORDS.get(region_key, [])
    if not region:
        return None
    return random.choice(region)

# Temas realistas de fotos para os bots (placeholders da internet)
PHOTO_THEMES = [
    "https://picsum.photos/seed/travel/400/400",
    "https://picsum.photos/seed/nightlife/400/400",
    "https://picsum.photos/seed/food/400/400",
    "https://picsum.photos/seed/nature/400/400",
    "https://picsum.photos/seed/tech/400/400",
    "https://picsum.photos/seed/arts/400/400",
    "https://picsum.photos/seed/portrait/400/400",
    "https://picsum.photos/seed/landscape/400/400"
]

# Coordenadas realistas por região (centros de grandes cidades)
REGION_COORDS = {
    "US": [
        (37.7749, -122.4194),  # São Francisco
        (40.7128, -74.0060),   # Nova York
        (34.0522, -118.2437),  # Los Angeles
        (41.8781, -87.6298),   # Chicago
        (29.7604, -95.3698),   # Houston
    ],
    "EU": [
        (48.8566, 2.3522),     # Paris
        (51.5074, -0.1278),    # Londres
        (52.5200, 13.4050),    # Berlim
        (45.4642, 9.1900),     # Milão
        (41.8955, 12.4823),    # Roma
    ],
    "Asia": [
        (35.6762, 139.6503),   # Tóquio
        (31.2304, 121.4737),   # Xangai
        (19.0760, 72.8777),    # Mumbai
        (28.6139, 77.2090),    # Nova Deli
        (1.3521, 103.8198),    # Singapura
    ],
    "LatAm": [
        (-23.5505, -46.6333),  # São Paulo
        (-34.6037, -58.3816),  # Buenos Aires
        (-33.4489, -70.6693),  # Santiago
        (-22.9068, -43.1729),  # Rio de Janeiro
        (-12.9714, -38.5014),  # Salvador
    ],
    "Africa": [
        (-26.2041, 28.0473),   # Joanesburgo
        (6.5244, 3.3792),      # Lagos
        (-33.9249, 18.4241),   # Cidade do Cabo
    ],
    "Oceania": [
        (-33.8688, 151.2093),  # Sydney
        (-36.8485, 174.7633),  # Auckland
        (-27.4698, 153.0251),  # Brisbane
    ]
}

# Temas de perfil para os bots
PROFILE_THEMES = {
    "travel": {"avatar": "https://picsum.photos/seed/travel_avatar/100/100", "bio": BIOS["travel"][0]},
    "nightlife": {"avatar": "https://picsum.photos/seed/nightlife_avatar/100/100", "bio": BIOS["nightlife"][0]},
    "food": {"avatar": "https://picsum.photos/seed/food_avatar/100/100", "bio": BIOS["food"][0]},
    "nature": {"avatar": "https://picsum.photos/seed/nature_avatar/100/100", "bio": BIOS["nature"][0]},
    "tech": {"avatar": "https://picsum.photos/seed/tech_avatar/100/100", "bio": BIOS["tech"][0]},
    "arts": {"avatar": "https://picsum.photos/seed/arts_avatar/100/100", "bio": BIOS["arts"][0]},
}

# Temas de fotos de spots para os bots
SPOT_THEMES = {
    "travel": ["https://picsum.photos/seed/travel_spot/800/600", "https://picsum.photos/seed/travel_spot2/800/600"],
    "nightlife": ["https://picsum.photos/seed/nightlife_spot/800/600"],
    "food": ["https://picsum.photos/seed/food_spot/800/600", "https://picsum.photos/seed/food_spot2/800/600"],
    "nature": ["https://picsum.photos/seed/nature_spot/800/600", "https://picsum.photos/seed/nature_spot2/800/600"],
    "tech": ["https://picsum.photos/seed/tech_spot/800/600"],
    "arts": ["https://picsum.photos/seed/arts_spot/800/600", "https://picsum.photos/seed/arts_spot2/800/600"],
}

import re
import math

class BotGenerator:
    def __init__(self, password, dry_run=False):
        self.password = password
        self.dry_run = dry_run
        self.created_users = []
        self.created_spots = []
        self.created_follows = []

    def run(self, count=50):
        if not self.dry_run:
            # Initialize the database if needed
            try:
                conn = db.connect()
                conn.close()
                db.init()
                print("Banco de dados SQLite inicializado com sucesso.")
            except Exception as e:
                print(f"Aviso: não foi possível inicializar o banco de dados: {e}")
                print("Continuando sem a capacidade de persistir os bots...")
                self.dry_run = True

        regions = list(REGION_COORDS.keys())

        for i in range(count):
            region = random.choice(regions)
            theme = random.choice(list(PROFILE_THEMES.keys()))
            region_names = REGIONAL_NAMES.get(region, [])
            if not region_names:
                continue
            username = f"{random.choice(region_names)}_{i+1:03d}"
            if not re.fullmatch(r"[A-Za-z0-9_]{4,24}", username):
                continue

            print(f"Criando bot {i+1}/{count}: @{username} ({region}) tema={theme}")

            if self.dry_run:
                self.created_users.append(username)
                print(f"  -> Dry-run: usuário @{username} seria criado")
                # Simulate spots
                for j in range(random.randint(1, 3)):
                    self.created_spots.append((username, f"{theme.title()} Spot #{j+1}", pick_random(region)))
                continue

            # Create user via database
            user_id = self._insert_user(username, self.password, theme)
            if not user_id:
                continue

            # Generate and insert spots
            spots = self._generate_spots(user_id, theme, region, 3)
            for spot in spots:
                self.created_spots.append((user_id, spot['name'], (spot['lat'], spot['lng'])))

            # Follow some other random users (30% chance)
            if random.random() < 0.3 and self.created_users:
                target_user_id = random.choice(self.created_users)
                if target_user_id != user_id:
                    self._insert_follow(user_id, target_user_id)
                    self.created_follows.append((user_id, target_user_id))

            self.created_users.append(user_id)

        self._summary()

    def _insert_user(self, username, password, theme):
        conn = db.connect()
        try:
            row = db.execute(conn, "SELECT 1 FROM users WHERE LOWER(username) = LOWER(?)", (username,)).fetchone()
            if row:
                print(f"  -> Usuário @{username} já existe, ignorando")
                return None
            password_hash = hash_password(password)
            user_id = db.insert_id(conn, "INSERT INTO users (username, password_hash, bio, avatar) VALUES (?, ?, ?, ?)",
                                   (username, password_hash, PROFILE_THEMES[theme]["bio"], PROFILE_THEMES[theme]["avatar"]))
            conn.commit()
            print(f"  -> Criado usuário ID {user_id}")
            return user_id
        except Exception as e:
            print(f"  -> Erro ao criar usuário {username}: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def _generate_spots(self, user_id, theme, region, count=3):
        spots = []
        base_lat, base_lng = pick_random(region)
        for i in range(count):
            lat = base_lat + random.uniform(-0.1, 0.1)
            lng = base_lng + random.uniform(-0.1, 0.1)
            distance = random.randint(200, 2000)
            spot_name = f"{theme.title()} Spot #{i+1}"
            desc = f"Um {theme} autêntico spot capturado neste lugar.".replace("_", "")
            photo = random.choice(SPOT_THEMES.get(theme, PHOTO_THEMES))
            # Mock insert of spot via API
            spot_id = self._insert_spot(user_id, spot_name, desc, lat, lng, photo, distance)
            if spot_id:
                spots.append({
                    "id": spot_id,
                    "lat": lat,
                    "lng": lng,
                    "name": spot_name,
                    "photo": photo,
                    "author": user_id,
                    "distance_m": distance
                })
        return spots

    def _insert_spot(self, user_id, name, description, lat, lng, photo, radius_m):
        conn = db.connect()
        try:
            # Determine photo_mime based on extension (simplified)
            if photo.endswith(".png"):
                mime = "image/png"
            elif photo.endswith(".jpg") or photo.endswith(".jpeg"):
                mime = "image/jpeg"
            elif photo.endswith(".webp"):
                mime = "image/webp"
            else:
                mime = "image/jpeg"
            spot_id = db.insert_id(conn, """
                INSERT INTO spots (user_id, name, description, lat, lng, photo_b64, photo_mime, radius_m)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (user_id, name, description, lat, lng, photo, mime, radius_m))
            conn.commit()
            print(f"    -> Criado spot ID {spot_id}")
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
        print(f"Relaciones criadas: {len(self.created_follows)}")
        if self.dry_run:
            print("\nAtenção: Este foi um dry-run. Nenhum dado foi realmente inserido no banco de dados.")
            print("Para executar realmente, remova o sinalizador --dry-run.")
            print("\nIDs dos usuários:", self.created_users)
        else:
            print("\nIDs dos usuários:", self.created_users)
        print("Spots:")
        for uid, name, (lat, lng) in self.created_spots:
            print(f"  - Spot por usuário {uid}: '{name}' ({lat:.4f}, {lng:.4f})")
        if self.created_follows:
            print("Relaciones:")
            for fid, fid2 in self.created_follows:
                print(f"  - {fid} segue {fid2}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Gera contas de bots realistas para NearGram.")
    parser.add_argument("--count", type=int, default=50, help="Número de bots a serem criados (padrão: 50)")
    parser.add_argument("--password", type=str, default="botpass", help="Senha para as contas dos bots (padrão: botpass)")
    parser.add_argument("--dry-run", action="store_true", help="Apenas imprime o que seria feito")
    args = parser.parse_args()

    generator = BotGenerator(password=args.password, dry_run=args.dry_run)
    generator.run(count=args.count)

def pick_random(region_key):
    region = REGION_COORDS.get(region_key, [])
    if not region:
        return None
    return random.choice(region)