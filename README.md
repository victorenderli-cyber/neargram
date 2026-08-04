# NearGram 📍

Rede social estilo Instagram baseada em **geolocalização**: cada foto fica "presa" no lugar onde foi tirada e **só pode ser vista por quem está perto do local** (geo-fence). Explore pontos turísticos e lugares legais de verdade — ou use o modo de simulação para testar.

## Como funciona

- **Publique** uma foto de um lugar, junto com sua posição atual e um "raio de desbloqueio" (padrão 500 m).
- **Descubra** lugares no mapa: de longe aparecem **🔒 bloqueados**; ao se aproximar do raio, a foto é **revelada**.
- **Curtir** e **comentar** fotos desbloqueadas.
- Localização real via GPS do navegador, com **modo de simulação** (clique no mapa) para quem não quer sair de casa.

## Stack

- **Backend**: Python 3.12 (biblioteca padrão — servidor HTTP próprio, sem frameworks)
- **Banco**: PostgreSQL (produção) ou SQLite (desenvolvimento) — camada `db.py` agnóstica
- **Frontend**: HTML/CSS/JS + Leaflet + OpenStreetMap
- **Segurança**: senhas com PBKDF2 (120k iterações), sessões via cookie `HttpOnly` + `SameSite=Lax` + `Secure` atrás de HTTPS

## Rodar localmente

```bash
# sem dependências instaladas (usa SQLite)
python server.py
# abra http://127.0.0.1:8000
```

Com PostgreSQL:

```bash
pip install -r requirements.txt
set DATABASE_URL=postgres://user:pass@host:5432/db
python server.py
```

O banco é criado automaticamente na primeira execução (`db.init()`).

## Deploy no Render

O arquivo [`render.yaml`](render.yaml) provisiona automaticamente:

1. um **web service** (plano free) rodando `python server.py`
2. um **banco PostgreSQL** (plano free) conectado via `DATABASE_URL`

Para subir:

- **Via dashboard**: crie o app em `render.com` → **New + → Blueprint** e conecte este repositório (público: `victorenderli-cyber/neargram`).
- **Via API**: use a [Blueprint Deploy API](https://render.com/docs/blueprint-spec) com uma API key.

> ⚠️ No plano free do Render, o serviço "dorme" após 15 min sem uso (primeiro acesso pode demorar alguns segundos). Os dados ficam no PostgreSQL (persistem); se não quiser banco, remova o bloco `databases` do `render.yaml` (aí os dados voltam a ser efêmeros).

## API

| Método | Rota | Descrição |
|---|---|---|
| POST | `/api/register` | Cria conta |
| POST | `/api/login` | Login (cookie de sessão) |
| POST | `/api/logout` | Encerra sessão |
| GET | `/api/me` | Usuário atual |
| GET | `/api/spots?lat=&lng=` | Lista lugares com distância/bloqueio |
| POST | `/api/spots` | Publica foto (JSON com base64) |
| GET | `/api/spots/:id/photo?lat=&lng=` | Foto (só se estiver no raio) |
| POST | `/api/spots/:id/like` | Curtir/descurtir |
| POST | `/api/spots/:id/comments` | Comentar |

## Estrutura

```
server.py      # servidor HTTP + rotas + regras de negócio
db.py          # camada de banco (PostgreSQL/SQLite)
static/        # frontend (mapa, feed, modais)
render.yaml    # blueprint de deploy (web + postgres)
requirements.txt
```
