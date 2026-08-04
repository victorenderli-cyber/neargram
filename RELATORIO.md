# Relatório do Projeto — NearGram 📍

## 1. Visão geral

**NearGram** é uma rede social de fotos por **geolocalização**, estilo Instagram, onde cada foto fica "presa" ao lugar onde foi tirada e **só pode ser visualizada por quem está perto do local** (geo-fence / raio de desbloqueio). O objetivo é incentivar o usuário a visitar pontos turísticos e lugares reais — com um modo de simulação para testar sem sair de casa.

- **Nome:** NearGram
- **Público:** exploradores de lugares / turistas
- **Plataforma:** Web (PWA instalável em Android/iOS)

---

## 2. Funcionalidades

### Autenticação
- Cadastro e login por usuário/senha.
- Sessões por cookie `HttpOnly` + `SameSite=Lax` (+ `Secure` atrás de HTTPS).
- Perfil com estatísticas (fotos, curtidas, comentários) e grid das próprias fotos.
- Autor pode **excluir** as próprias fotos e vê as próprias a qualquer distância.

### Publicação por geo-fence
- Publicar foto com nome, descrição, posição atual e **raio de desbloqueio** (50–2000 m, padrão 500 m).
- A foto fica **🔒 bloqueada** para quem está longe; é **revelada** ao entrar no raio.
- Distância calculada em tempo real (fórmula de Haversine).

### Descoberta e interação
- Mapa Leaflet + OpenStreetMap com marcadores (⬤ você, 🔒 bloqueado, foto desbloqueada).
- Feed de lugares com foto, autor, curtidas, comentários e distância.
- **Curtir** / descurtir e **comentar** fotos desbloqueadas.
- Dois modos de posicionamento: **GPS real** e **simulação** (clique no mapa).

### PWA (instalável)
- `manifest.json`, service worker com cache offline (só o shell; API/tiles não são cacheados).
- Instalável como app no Android (Chrome) e iOS (Safari → Adicionar à Tela de Início).

---

## 3. Stack tecnológica

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.12 — servidor HTTP próprio (`http.server`, sem frameworks) |
| Banco | PostgreSQL (produção) / SQLite (desenvolvimento), camada `db.py` agnóstica |
| Frontend | HTML + CSS + JavaScript puro + **Leaflet** + OpenStreetMap |
| PWA | `manifest.json`, service worker, ícones |
| Segurança | PBKDF2 (120k iterações), sessão por cookie |
| Deploy | Render (web service free) + PostgreSQL free |

Única dependência Python: `psycopg2-binary==2.9.10`.

---

## 4. Arquitetura

```
Navegador (app.js)
   │  JSON / HTTP (fetch, cookie de sessão)
   ▼
server.py  (BaseHTTPRequestHandler — rotas /api + estáticos)
   │
   ▼
db.py  (camada agnóstica: escolhe Postgres ou SQLite pelo env DATABASE_URL)
   ▼
PostgreSQL (schema neargram)  /  SQLite (data.db)
```

- **Servidor sem framework**: usa a biblioteca padrão do Python (`http.server`), mantendo dependências mínimas.
- **Fotos no banco**: as imagens são gravadas em base64 (coluna `photo_b64`), evitando armazenamento de arquivos — custo à parte da simplicidade.
- **Multi-bancos**: a camada `db.py` converte placeholders `?`→`%s` e `DATETIME`→`to_char(now())`, permitindo trocar de SQLite para Postgres sem alterar o restante do código.

---

## 5. Estrutura de arquivos

```
server.py        # servidor HTTP + rotas de API + regras de negócio (geo-fence, autorização)
db.py            # camada de banco (PostgreSQL/SQLite) + criação de schema
render.yaml      # blueprint de deploy (web + postgres) no Render
requirements.txt # psycopg2-binary
static/
  index.html     # tela de login + app + modais
  app.js         # lógica do cliente (mapa, feed, modais, boot)
  style.css      # tema dark estilo Instagram
  sw.js          # service worker (cache offline)
  manifest.json  # metadados PWA
  icons/         # ícones do app
  vendor/leaflet # Leaflet servido localmente (sem CDN)
RELATORIO.md     # este documento
```

---

## 6. Banco de dados (schema `neargram`)

| Tabela | Função | Colunas principais |
|---|---|---|
| `users` | Usuários | `id`, `username` (único, ≤24), `password_hash`, `created_at` |
| `sessions` | Sessões | `token` (PK), `user_id` (FK), `created_at` |
| `spots` | Fotos/lugares | `id`, `user_id`, `name`, `description`, `lat`, `lng`, `photo_b64`, `photo_mime`, `radius_m` (padrão 500), `created_at` |
| `likes` | Curtidas | `spot_id`+`user_id` (PK composta), `created_at` |
| `comments` | Comentários | `id`, `spot_id`, `user_id`, `text` (≤500), `created_at` |

Relacionamentos: `spots`, `sessions`, `likes` e `comments` usam `ON DELETE CASCADE` em relação a `users`/`spots`. No Postgres as tabelas ficam isoladas no **schema `neargram`** para conviver com outro app no mesmo banco free sem conflito.

---

## 7. API (endpoints)

| Método | Rota | Descrição | Auth |
|---|---|---|---|
| POST | `/api/register` | Cria conta e abre sessão | — |
| POST | `/api/login` | Login | — |
| POST | `/api/logout` | Encerra sessão | cookie |
| GET | `/api/me` | Usuário atual (ou `null`) | — |
| GET | `/api/profile` | Stats + fotos do usuário | cookie |
| GET | `/api/spots?lat=&lng=` | Lista lugares com distância/bloqueio | — |
| POST | `/api/spots` | Publica foto (JSON, foto em base64) | cookie |
| GET | `/api/spots/:id/photo?lat=&lng=` | Foto — só se estiver no raio | geo-fence |
| POST | `/api/spots/:id/like` | Curtir/descurtir | cookie |
| POST | `/api/spots/:id/comments` | Comentar | cookie |
| DELETE | `/api/spots/:id` | Excluir (somente autor) | cookie |

Regra-chave (`api_spot_photo`): se o visualizador não é o autor e está fora do `radius_m`, a foto retorna `403 locked`.

---

## 8. Segurança

- **Senhas**: PBKDF2-HMAC-SHA256, 120.000 iterações, salt aleatório por usuário.
- **Sessão**: token aleatório (hex 32) armazenado em cookie `HttpOnly`, `SameSite=Lax`, `Secure` em HTTPS.
- **Validação de entrada**: tamanhos e intervalos de coordenadas, foto limitada a **6 MB** base64.
- **Autorização**: apenas o dono pode excluir; apenas dentro do raio é possível ver a foto de terceiros.
- **CORS**: `Access-Control-Allow-Origin: *` apenas na opção OPTIONS (aplicativo é mesmo-origin).

---

## 9. Deploy e hospedagem

- **Produção (ativos):** <https://neargram.onrender.com>
- **Mecanismo:** auto-deploy no Render a cada `push` na branch `main` (repo `victorenderli-cyber/neargram`).
- **Base:** web service Python (free, Oregon) + PostgreSQL free, via blueprint `render.yaml`.
- **Domínio próprio (DuckDNS) — concluído:** <https://neargram.duckdns.org>
  - O DuckDNS **não suporta CNAME** pela API (aceita apenas IPv4/IPv6).
  - Solução aplicada: registro **A** → `216.24.57.15` (IP de edge do Render), com o domínio cadastrado como **Custom Domain** no painel do Render.
  - Verificado: site, PWA, API e SSL todos funcionando (`200`) no domínio próprio.

> ⚠️ No plano free, o serviço "dorme" após ~15 min sem uso (primeiro acesso demora alguns segundos) e o Postgres expira em ~90 dias.

---

## 10. Estado atual (verificado)

- Site em produção: **200 OK** em `/`, ícones e `/api/spots`.
- **8 lugares (spots) cadastrados** em produção.
- Código publicado idêntico ao local.
- **Domínio próprio ativo:** <https://neargram.duckdns.org> (site, PWA, API e SSL verificados — `200`).
- Última correção em produção: **endurecimento da tela preta** — limpeza de cache do service worker (`v2`), erro de boot visível (overlay `#fatal`) e fallback se `app.js` não carregar.

---

## 11. Histórico de desenvolvimento

| Commit | Descrição |
|---|---|
| `5489852` | NearGram: rede social de fotos por geolocalização (base) |
| `24ea654` | Ajusta `pythonVersion` para 3.12 no `render.yaml` |
| `8d6b87b` | Produção: camada Postgres/SQLite, fotos no banco, blueprint Render, README |
| `9ecf155` | Isola tabelas no schema `neargram` para reuso de banco free |
| `59e4aec` | Perfil com estatísticas, excluir fotos (só autor), autor vê foto a qualquer distância |
| `475abae` | Corrige tela preta (Leaflet local), PWA instalável, tratamento de erro de boot |
| `ab34bc0` | Endurece contra tela preta: erro de boot visível, cache SW v2, fallback app.js |

---

## 12. Pendências e melhorias sugeridas

1. **Servir imagens por CDN/arquivo** em vez de base64 no banco (escalabilidade e tamanho).
2. **Rate limiting** e **expiração de sessão** para produção mais robusta.
3. **Paginação do feed** e filtro "próximos de mim".
4. **Notificações push** (ex.: "alguém comentou em um lugar que você curtiu").
5. Limpeza: remover `Curriculo_Camila_da_Silva.md` já feita (arquivo alheio ao projeto).

### ✔ Concluídos
- Domínio próprio **`neargram.duckdns.org`** configurado e funcionando (A record + Custom Domain no Render).
- Endurecimento da tela preta (erro de boot visível, cache SW v2, fallback `app.js`).
- **Endurecimento do backend (avaliação):** rate limiting em login/registro (429), expiração de sessões (30 dias) + `Max-Age` no cookie, 500 sem vazar detalhes internos, logs de requisição habilitados, consultas em lote (fim do N+1), paginação (`limit`) em `/api/spots`.
- **Testes automatizados:** `tests/test_api.py` (9 testes, `unittest` puro) — autenticação, geo-fence, foto bloqueada, curtir/comentar/perfil/excluir, sessão expirada, rate limit.

---

## 13. Como rodar localmente

```bash
# sem instalar nada (usa SQLite)
python server.py
# abra http://127.0.0.1:8000

# com PostgreSQL na máquina
pip install -r requirements.txt
$env:DATABASE_URL = "postgres://user:pass@host:5432/db"
python server.py
```

O banco é criado automaticamente na primeira execução (`db.init()`).

---

## 14. Avaliação do Projeto

### Nota geral: **8/10** — MVP sólido, conceito original e funcional; precisa de endurecimento para escala/produção.

### Pontos fortes
- **Conceito original e coerente**: geo-fence em rede social é um diferencial claro e bem implementado (bloqueio/revelação por raio, autor sempre vê o próprio).
- **Zero dependências no backend**: servidor HTTP com biblioteca padrão — fácil de rodar e entender.
- **Segurança básica correta**: PBKDF2 (120k), cookie `HttpOnly`/`SameSite`/`Secure`, autorização por dono e por raio.
- **Frontend limpo e autocontido**: JS vanilla com estado centralizado, modais, XSS escapado, Leaflet servido localmente (sem CDN) e PWA instalável.
- **Camada de banco agnóstica** (SQLite/Postgres) bem isolada em `db.py` — facilita dev/prod.
- **Deploy automatizado** (Render + auto-deploy no push) e domínio próprio funcionando.

### Pontos fracos / riscos
1. **Performance (N+1)**: `public_spot()` abre uma conexão nova e faz 3+ consultas **por lugar** — com poucos spots funciona, mas não escala.
2. **Fotos no banco como base64**: estoura o limite do Postgres free com uso real; ideal é servir por CDN/armazenamento de objetos e guardar só a URL.
3. **Sem rate limiting**: `/api/login` e `/api/register` são alvo fácil de brute-force.
4. **Sessões sem expiração**: a tabela `sessions` cresce indefinidamente e tokens nunca revogam (exceto logout).
5. **Vazamento de erro**: `internal error: {e}` devolve detalhes internos ao cliente em produção.
6. **Sem logs**: `log_message` está desativado — impossível depurar em produção.
7. **Mapeamento/payload**: `_read_json` carrega o corpo inteiro em memória e `serve_static` lê arquivo inteiro por request.
8. **Área do mapa escura**: se o OSM/tiles estiverem bloqueados pela rede, o mapa vira um bloco preto (pode parecer tela preta).
9. **Sem paginação**: o feed busca e renderiza todos os spots de uma vez.
10. **Sem testes automatizados**: não há testes unitários/e2e.

### Recomendações por prioridade
| Prioridade | Ação | Status |
|---|---|---|
| Alta | Rate limiting em login/registro; expiração de sessão; parar de vazar erros internos | ✔ feito |
| Alta | Migrar fotos para armazenamento de objetos (ex.: Cloudinary/S3) com URL no banco | pendente |
| Média | Paginar `/api/spots` e otimizar as consultas (join em vez de N+1) | ✔ feito (limite no API; pooling ainda pendente) |
| Média | Adicionar testes básicos (`unittest` em `tests/test_api.py`) | ✔ feito |
| Média | Logging de requisições | ✔ feito (stderr; estruturado segue pendente) |
| Baixa | Compressão da imagem no cliente antes do upload; gzip nas respostas | pendente |

### Conclusão
O NearGram entrega exatamente a proposta (ver só perto do lugar) com código pequeno, limpo e seguro o suficiente para um MVP em plano free. Antes de virar produto com usuários reais, priorize **rate limiting**, **armazenamento de imagens fora do banco** e **paginação**.