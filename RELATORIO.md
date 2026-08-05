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
- Sessões por cookie `HttpOnly` + `SameSite=Lax` (+ `Secure` atrás de HTTPS), com expiração de 30 dias.
- Perfil com **bio e foto de avatar**, estatísticas (fotos, curtidas, comentários, seguidores, seguindo) e grid das próprias fotos.
- Autor pode **excluir** as próprias fotos e vê as próprias a qualquer distância.

### Rede social
- **Seguir / deixar de seguir** usuários; **feed "Seguindo"** (só fotos de quem você segue, perto de você).
- **Busca** de lugares e usuários (por nome/bio).
- **Notificações** de curtidas, comentários e novos seguidores (com badge de não-lidas).
- **Perfil público** de qualquer usuário (bio, avatar, stats, grid) com botão seguir.
- **Compartilhar link do lugar** (link direto `#spot=ID` abre a foto).
- **Denunciar conteúdo impróprio** (motivo gravado, com rate limit por IP).
- **Modo claro/escuro** (preferência salva no navegador).

### Publicação por geo-fence
- Publicar foto com nome, descrição, posição atual e **raio de desbloqueio** (50–2000 m, padrão 500 m).
- A foto fica **🔒 bloqueada** para quem está longe; é **revelada** ao entrar no raio.
- Distância calculada em tempo real (fórmula de Haversine).

### Descoberta e interação
- Mapa Leaflet + OpenStreetMap com **clusters** (marcadores agrupados por proximidade), **círculo do raio de desbloqueio** ao redor da sua posição e marcadores (⬤ você, 🔒 bloqueado, foto desbloqueada).
- Feed de lugares com foto, autor, curtidas, comentários e distância — **paginado** com botão "Carregar mais lugares" **e autoload** ao rolar (`limit`+`offset`+`has_more`).
- **Curtir** / descurtir e **comentar** fotos desbloqueadas (autor do comentário ou do spot podem **excluir comentários**).
- Autor pode **editar** nome, descrição e raio de desbloqueio das próprias fotos, **excluir a própria conta** (com confirmação de senha) e **alterar a senha**.
- **Busca com debounce** (resultados enquanto digita) **ordenada por proximidade** quando lat/lng informados.
- Dois modos de posicionamento: **GPS real** e **simulação** (clique no mapa).

### PWA (instalável)
- `manifest.json`, service worker com cache offline (só o shell; API/tiles não são cacheados).
- **Botão "Instalar"** no app (`beforeinstallprompt`) para instalar como app no Android (Chrome) e iOS (Safari → Adicionar à Tela de Início).
- **Aviso de nova versão**: ao detectar service worker novo, o app mostra um toast "Nova versão disponível" com botão **Atualizar** (recarrega na hora).
- **`theme-color` dinâmico** que acompanha o tema claro/escuro.
- **Web Push** (opt-in): notificações nativas de curtida/comentário/follow (VAPID; requer `VAPID_PUBLIC_KEY`/`VAPID_PRIVATE_KEY`/`VAPID_SUBJECT` no ambiente).

### Performance e robustez
- **Compressão de imagem no cliente** (canvas → JPEG 1280px no upload de fotos, 512px no avatar), reduzindo até ~90% do payload.
- **gzip** automático em JSON e estáticos (quando o cliente aceita `Accept-Encoding: gzip`).
- **Cabeçalhos de segurança**: CSP, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`, `Permissions-Policy`.
- **Storage externo opt-in**: se `CLOUDINARY_CLOUD_NAME` + `CLOUDINARY_UPLOAD_PRESET` estiverem configurados, as fotos vão para o Cloudinary (URL salva; redirect 302 na entrega); senão, mantém base64 no banco.
- **Índices no banco** (`spots(user_id)`, `spots(lat,lng)`, `likes(spot_id)`, `comments(spot_id)`, `notifications(user_id,read)`) para consultas rápidas.
- **Feed ordenado por proximidade** (desbloqueadas primeiro, depois por distância), **paginação** com `has_more`, **autoload** ao rolar e **polling** de notificações (badge a cada 30 s).
- **Pooling de conexões Postgres** (psycopg2 `ThreadedConnectionPool`, 1–20 conexões) — sem abrir conexão nova a cada requisição.
- **Logs estruturados em JSON** (acesso + erros com timestamp UTC) para facilitar depuração em produção.
- **Skeleton loading** no feed e **toasts** com ação (ex.: atualizar app).

---

## 3. Stack tecnológica

| Camada | Tecnologia |
|---|---|
| Backend | Python 3.12 — servidor HTTP próprio (`http.server`, sem frameworks) |
| Banco | PostgreSQL (produção) / SQLite (desenvolvimento), camada `db.py` agnóstica |
| Frontend | HTML + CSS + JavaScript puro + **Leaflet** + OpenStreetMap |
| PWA | `manifest.json`, service worker, ícones, **Web Push (VAPID)** |
| Segurança | PBKDF2 (120k iterações), sessão por cookie, CSP + headers de segurança |
| Deploy | Render (web service free) + PostgreSQL free |
| Extras (opt-in) | Cloudinary (fotos externas), `pywebpush` |

Dependências Python: `psycopg2-binary` (Postgres) e `pywebpush` (Web Push — import preguiçoso; sem VAPID configurado não é usado).

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
  sw.js          # service worker (cache offline + Web Push)
  manifest.json  # metadados PWA
  icons/         # ícones do app
  vendor/leaflet # Leaflet servido localmente (sem CDN)
  vendor/leaflet.markercluster # markercluster servido localmente (sem CDN)
tools/gen_vapid.py # gera chaves VAPID para Web Push
RELATORIO.md     # este documento
```

---

## 6. Banco de dados (schema `neargram`)

| Tabela | Função | Colunas principais |
|---|---|---|
| `users` | Usuários | `id`, `username` (único, ≤24), `password_hash`, `bio`, `avatar`, `created_at` |
| `sessions` | Sessões | `token` (PK), `user_id` (FK), `created_at` |
| `spots` | Fotos/lugares | `id`, `user_id`, `name`, `description`, `lat`, `lng`, `photo_b64`, `photo_mime`, `radius_m` (padrão 500), `created_at` |
| `likes` | Curtidas | `spot_id`+`user_id` (PK composta), `created_at` |
| `comments` | Comentários | `id`, `spot_id`, `user_id`, `text` (≤500), `created_at` |
| `follows` | Seguidores | `follower_id`+`followee_id` (PK composta), `created_at` |
| `notifications` | Notificações | `id`, `user_id`, `actor_id`, `type`, `spot_id`, `text`, `read`, `created_at` |
| `reports` | Denúncias | `id`, `reporter_id`, `spot_id`, `reason`, `created_at` |
| `push_subs` | Assinaturas Web Push | `id`, `user_id`, `endpoint` (único), `p256dh`, `auth`, `created_at` |

Relacionamentos: `spots`, `sessions`, `likes`, `comments`, `follows`, `notifications` e `reports` usam `ON DELETE CASCADE` em relação a `users`/`spots` (exceto `reports.reporter_id` que usa `SET NULL`). No Postgres as tabelas ficam isoladas no **schema `neargram`** para conviver com outro app no mesmo banco free sem conflito. Para bancos existentes, `db.migrate()` adiciona `bio`/`avatar` via `ALTER TABLE`.

---

## 7. API (endpoints)

| Método | Rota | Descrição | Auth |
|---|---|---|---|
| POST | `/api/register` | Cria conta e abre sessão | — |
| POST | `/api/login` | Login | — |
| POST | `/api/logout` | Encerra sessão | cookie |
| GET | `/api/me` | Usuário atual (ou `null`) | — |
| GET | `/api/profile` | Stats + fotos do usuário | cookie |
| POST | `/api/profile` | Atualiza bio/avatar | cookie |
| POST | `/api/profile/password` | Altera a senha (exige senha atual) | cookie |
| GET | `/api/search?q=&lat=&lng=` | Busca usuários e lugares | — |
| GET | `/api/notifications` | Notificações + contagem de não-lidas | cookie |
| POST | `/api/notifications/read` | Marca todas como lidas | cookie |
| GET | `/api/users/:username` | Perfil público (stats, follows, fotos) | — |
| POST | `/api/users/:id/follow` | Seguir / deixar de seguir | cookie |
| GET | `/api/spots?lat=&lng=&feed=following&limit=&offset=` | Lista lugares paginado (`has_more`) | — |
| POST | `/api/spots` | Publica foto (JSON, foto em base64) | cookie |
| GET | `/api/spots/:id/photo?lat=&lng=` | Foto — só se estiver no raio | geo-fence |
| PATCH | `/api/spots/:id` | Edita nome/descrição/raio (somente autor) | cookie |
| POST | `/api/spots/:id/like` | Curtir/descurtir (gera notificação) | cookie |
| POST | `/api/spots/:id/comments` | Comentar (gera notificação) | cookie |
| POST | `/api/spots/:id/report` | Denunciar conteúdo (rate limit por IP) | cookie |
| DELETE | `/api/spots/:id` | Excluir (somente autor) | cookie |
| DELETE | `/api/comments/:id` | Excluir comentário (autor do comentário ou do spot) | cookie |
| DELETE | `/api/me` | Excluir conta (confirma senha) | cookie |
| GET | `/api/push/vapid-public-key` | Chave pública VAPID (para assinar push) | — |
| POST | `/api/push/subscribe` | Registra assinatura de push do usuário | cookie |
| DELETE | `/api/push/subscribe` | Remove assinatura de push | cookie |

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
- **Melhorias aplicadas (a publicar):** paginação do feed (`has_more`), clusters no mapa, busca ordenada por proximidade, editar spot, excluir comentário, excluir conta, toasts, progresso de upload, botão instalar PWA, log estruturado JSON e pooling Postgres (SW v6, 23 testes).
- **Últimas melhorias (a publicar):** círculo do raio de desbloqueio no mapa, autoload do feed, busca com debounce, compartilhar via Web Share API, alterar senha, aviso de nova versão do app (SW v7), skeleton loading, tempo relativo em comentários/notificações, índices no banco e `theme-color` dinâmico.

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
| `ad97d9f` | Adiciona relatório do projeto e marca domínio próprio como concluído |
| `bef3ac6` | Correções da avaliação: rate limit, expiração de sessão, 500 genérico, logs, fim do N+1, paginação, testes |
| `7fa64c8` | Corrige bug crítico: prefixo `/api` duplicado em app.js (404 → tela preta). SW v3 |
| `31d621b` | **Novas funcionalidades:** seguidores/follow + feed "Seguindo", busca, notificações, bio+avatar, compartilhar link, denúncia, modo claro/escuro. Fix: botão curtir (span `like-count` era destruído). SW v4. 15 testes |
| `89be1f3` | **Melhorias:** compressão de imagem no cliente, gzip, cabeçalhos de segurança (CSP), feed ordenado por proximidade, polling de notificações, Web Push opt-in (VAPID), storage Cloudinary opt-in, `tools/gen_vapid.py`. SW v5. 19 testes |
| `5f51ed6` | **Melhorias:** paginação do feed (`limit`/`offset`/`has_more` + "Carregar mais"), clusters no mapa (markercluster local), busca ordenada por proximidade, editar spot (PATCH), excluir comentário (DELETE), excluir conta (DELETE `/api/me`), toasts, progresso de upload, botão instalar PWA, log estruturado JSON, pooling Postgres. SW v6. 23 testes |
| `30afa32` | **UX:** tema automático pelo sistema + tiles CartoDB por tema, lightbox de fotos, curtida rápida no card do feed, botão "ver no mapa", `loading="lazy"` nas imagens, gerenciar perfil a partir do perfil público, rate limit em curtir/comentar/follow. SW v8. 25 testes |
| `8a79fce` | **Melhorias:** rate limit por usuário, `has_more` consistente com ordenação por proximidade, SW não cacha tiles CartoDB, preconnect + acessibilidade (aria-labels, `role="dialog"`, `aria-live`), manifest com shortcuts e deep-link `?action=`, compressão WebP com fallback. SW v9. 26 testes |
| `c08726c` | **Mapa em modo satélite:** Esri World Imagery + camada de rótulos (CSP/preconnect/SW atualizados, OSM removido). SW v10 |
| `0f67b0e` | **Melhorias:** validação de username (regex `[A-Za-z0-9_]{4,24}`, unicidade case-insensitive), senha mínima 6 (registro e troca), avisos offline/online, `minlength`/`pattern` no registro, CSP sem OSM. 28 testes |
| *(atual)* | **Melhorias:** editar comentário (PATCH `/api/comments/{id}`), listas de seguidores/seguindo no perfil (avatares clicáveis), `mine` nos comentários (API), rate limit na busca, Cache-Control por tipo (HTML/JSON `no-cache`, estáticos 1 dia). 31 testes |

---

## 12. Pendências e melhorias sugeridas

1. **Notificações push ativas em produção**: executar `python tools/gen_vapid.py` e configurar `VAPID_PUBLIC_KEY`, `VAPID_PRIVATE_KEY` e `VAPID_SUBJECT` no Render (o backend já está pronto).
2. **Fotos no Cloudinary em produção**: configurar `CLOUDINARY_CLOUD_NAME` e `CLOUDINARY_UPLOAD_PRESET` (o backend já envia as fotos para lá quando presentes; senão mantém base64).
3. **Imagens por CDN/S3 genérico** (o Cloudinary é o caminho já implementado; S3/Backblaze seguiriam o mesmo padrão).
4. Compressão **gzip em imagens** não se aplica (já são JPEG/PNG); otimizar formato (WebP/AVIF) no cliente.

### ✔ Concluídos
- Domínio próprio **`neargram.duckdns.org`** configurado e funcionando (A record + Custom Domain no Render).
- Endurecimento da tela preta (erro de boot visível, cache SW v2, fallback `app.js`).
- **Endurecimento do backend (avaliação):** rate limiting em login/registro (429), expiração de sessões (30 dias) + `Max-Age` no cookie, 500 sem vazar detalhes internos, logs de requisição habilitados, consultas em lote (fim do N+1), paginação (`limit`) em `/api/spots`.
- **Testes automatizados:** `tests/test_api.py` (24 testes, `unittest` puro) — autenticação, geo-fence, foto bloqueada, curtir/comentar/perfil/excluir, sessão expirada, rate limit, bio/avatar, follow, notificações, feed "seguindo", denúncia, busca, **gzip/security headers, ordenação por proximidade, push subscribe, paginação, editar spot, excluir comentário, excluir conta, alterar senha**.
- **Redes sociais:** seguidores/follow, perfil público, feed "Seguindo", notificações de curtida/comentário/follow, busca de lugares e usuários.
- **Perfil rico:** bio e foto de avatar (upload), stats de seguidores/seguindo, **alteração de senha**.
- **Gestão de conteúdo:** editar spot (nome/descrição/raio), excluir comentário (autor ou dono do spot), excluir conta com confirmação de senha.
- **Compartilhamento e moderação:** link direto do lugar (`#spot=ID`), **Web Share API** (fallback clipboard) e denúncia de conteúdo impróprio.
- **UX:** modo claro/escuro persistente (**`theme-color` dinâmico**), fix do botão curtir no modal do spot, feed ordenado por proximidade, **paginação com "Carregar mais" + autoload**, **toasts (inclusive com ação)**, **skeleton loading**, **tempo relativo** em comentários/notificações, **busca com debounce**, progresso ao publicar/salvar/excluir, loading do feed e polling de notificações.
- **Mapa:** **clusters** de marcadores (markercluster servido localmente, sem CDN) e **círculo do raio de desbloqueio**.
- **Performance:** compressão de imagem no cliente (canvas), gzip em respostas JSON/estáticas, **pooling de conexões Postgres** e **índices** nas tabelas mais consultadas.
- **Observabilidade:** **logs estruturados JSON** (acesso + erros com timestamp UTC).
- **Segurança:** CSP + `nosniff`/`X-Frame-Options`/`Referrer-Policy`/`Permissions-Policy`.
- **Push (código pronto, precisa das env VAPID):** assinatura no cliente, endpoints `/api/push/*`, envio de curtida/comentário/follow e handlers `push`/`notificationclick` no service worker.
- **Instalação PWA:** botão "Instalar" (`beforeinstallprompt`) e **aviso de nova versão** com recarga automática.

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
1. **Performance**: consultas já são em lote (fim do N+1) e conexões Postgres são **pooled**; ainda assim, muitos spots exigem índices espaciais no futuro.
2. **Fotos no banco como base64**: estoura o limite do Postgres free com uso real; ideal é servir por CDN/armazenamento de objetos e guardar só a URL (Cloudinary já implementado, configurar env).
3. **Rate limiting** em `/api/login` e `/api/register` já existe (429); ampliar para outros endpoints é um próximo passo.
4. **Sessões**: expiram em 30 dias e são podadas; tokens não revogam individualmente (exceto logout).
5. **Vazamento de erro**: erros internos não vazam para o cliente (500 genérico); detalhes vão para os **logs JSON**.
6. **Logs**: estruturados em JSON no stderr (acesso + erros).
7. **Mapeamento/payload**: `_read_json` carrega o corpo inteiro em memória e `serve_static` lê arquivo inteiro por request (limites já impostos no corpo).
8. **Área do mapa escura**: se o OSM/tiles estiverem bloqueados pela rede, o mapa vira um bloco preto (pode parecer tela preta).
9. **Paginação**: implementada com `limit`/`offset`/`has_more` no feed e botão "Carregar mais".
10. **Testes automatizados**: 23 testes de API passando; testes e2e manuais via Edge headless (CDP) neste ciclo.

### Recomendações por prioridade
| Prioridade | Ação | Status |
|---|---|---|
| Alta | Rate limiting em login/registro; expiração de sessão; parar de vazar erros internos | ✔ feito |
| Alta | Migrar fotos para armazenamento de objetos (ex.: Cloudinary/S3) com URL no banco | ✔ feito (opt-in Cloudinary; configurar env p/ ativar) |
| Média | Paginar `/api/spots` e otimizar as consultas (join em vez de N+1) | ✔ feito (paginação `limit`/`offset`/`has_more` + pooling Postgres) |
| Média | Adicionar testes básicos (`unittest` em `tests/test_api.py`) | ✔ feito (23 testes) |
| Média | Logging de requisições | ✔ feito (logs estruturados JSON) |
| Baixa | Compressão da imagem no cliente antes do upload | ✔ feito (canvas → JPEG 1280px/512px) |
| Baixa | gzip nas respostas | ✔ feito (JSON + estáticos) |
| Baixa | Cabeçalhos de segurança (CSP, nosniff, X-Frame-Options) | ✔ feito |
| Baixa | Notificações push | ✔ código pronto (VAPID via env) |

### Conclusão
O NearGram entrega exatamente a proposta (ver só perto do lugar) com código pequeno, limpo e seguro o suficiente para um MVP em plano free. Neste ciclo foram endereçados **rate limiting**, **armazenamento de imagens fora do banco (opt-in)**, **paginação**, **clusters no mapa**, **gestão de conteúdo (editar/excluir)** e **pooling Postgres**; para virar produto, priorize configurar VAPID + Cloudinary em produção e índices espaciais.