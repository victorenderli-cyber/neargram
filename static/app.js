const $ = (id) => document.getElementById(id);

let state = {
  user: null,
  map: null,
  youMarker: null,
  spotMarkers: new Map(),
  spots: [],
  radius: 500,
  mode: "real", // real | sim
  currentPos: null, // {lat, lng}
  selectedSpotId: null,
  feedMode: "all", // all | following
};

const API = "/api";

/* ---------------- Tema claro/escuro ---------------- */
function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("ng-theme", t);
  $("btn-theme").textContent = t === "light" ? "☀️" : "🌙";
}
$("btn-theme").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  applyTheme(cur === "light" ? "dark" : "light");
});
applyTheme(localStorage.getItem("ng-theme") || "dark");

function setAvatar(id, dataUrl) {
  const el = $(id);
  if (!el) return;
  if (dataUrl) {
    el.src = dataUrl;
    el.classList.remove("no-avatar");
  } else {
    el.removeAttribute("src");
    el.classList.add("no-avatar");
  }
}

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
    method: opts.method || "GET",
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || "erro");
  return data;
}

/* ---------------- Auth ---------------- */
$("tab-login").addEventListener("click", () => setAuthMode("login"));
$("tab-register").addEventListener("click", () => setAuthMode("register"));

function setAuthMode(m) {
  const login = m === "login";
  $("tab-login").classList.toggle("active", login);
  $("tab-register").classList.toggle("active", !login);
  $("auth-submit").textContent = login ? "Entrar" : "Criar conta";
  $("auth-password").autocomplete = login ? "current-password" : "new-password";
}

$("auth-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const mode = $("tab-login").classList.contains("active") ? "login" : "register";
  const body = {
    username: $("auth-username").value,
    password: $("auth-password").value,
  };
  try {
    hideError("auth-error");
    await api(`/${mode}`, { method: "POST", body });
    await boot();
  } catch (err) {
    showError("auth-error", err.message);
  }
});

$("btn-logout").addEventListener("click", async () => {
  await api("/logout", { method: "POST" });
  state.user = null;
  showAuth();
});

function renderProfileGrid(gridId, emptyId, spots, mine) {
  const grid = $(gridId);
  grid.innerHTML = "";
  $(emptyId).classList.toggle("hidden", spots.length > 0);
  spots.forEach((s) => {
    const item = document.createElement("div");
    item.className = "pg-item";
    item.innerHTML = `
      ${s.photo ? `<img src="${s.photo}" />` : `<div class="pg-lock">🔒</div>`}
      ${mine ? `<button class="pg-del" title="Excluir">✕</button>` : ""}`;
    if (mine) {
      item.querySelector(".pg-del").addEventListener("click", (e) => {
        e.stopPropagation();
        deleteSpot(s.id);
      });
    }
    item.addEventListener("click", () => openSpotDetail(s.id));
    grid.appendChild(item);
  });
}

$("btn-profile").addEventListener("click", async () => {
  try {
    const p = await api("/profile");
    $("profile-title").textContent = "@" + p.user.username;
    setAvatar("profile-avatar", p.user.avatar);
    $("profile-bio").textContent = p.user.bio || "Sem biografia ainda.";
    $("profile-stats").innerHTML = `
      <div class="stat"><b>${p.stats.spots}</b><span>fotos</span></div>
      <div class="stat"><b>${p.stats.followers}</b><span>seguidores</span></div>
      <div class="stat"><b>${p.stats.following}</b><span>seguindo</span></div>
      <div class="stat"><b>${p.stats.likes}</b><span>curtidas</span></div>
      <div class="stat"><b>${p.stats.comments}</b><span>comentários</span></div>`;
    renderProfileGrid("profile-spots", "profile-empty", p.spots, true);
    $("profile-edit").classList.add("hidden");
    $("bio-input").value = p.user.bio || "";
    hideError("profile-error");
    showModal("modal-profile");
  } catch (e) {
    alert(e.message);
  }
});

$("btn-edit-profile").addEventListener("click", () => {
  $("profile-edit").classList.remove("hidden");
});

$("avatar-input").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (!f || !f.type.startsWith("image/")) return;
  const reader = new FileReader();
  reader.onload = () => {
    $("profile-avatar").src = reader.result;
    window._newAvatar = reader.result;
  };
  reader.readAsDataURL(f);
});

$("btn-save-profile").addEventListener("click", async () => {
  try {
    hideError("profile-error");
    const body = { bio: $("bio-input").value };
    if (window._newAvatar) body.avatar = window._newAvatar;
    const res = await api("/profile", { method: "POST", body });
    window._newAvatar = null;
    setAvatar("avatar-nav", res.avatar);
    $("profile-bio").textContent = res.bio || "Sem biografia ainda.";
    $("profile-edit").classList.add("hidden");
    alert("Perfil atualizado!");
  } catch (e) {
    showError("profile-error", e.message);
  }
});

async function deleteSpot(id) {
  if (!confirm("Excluir esta foto?")) return;
  try {
    await api(`/spots/${id}`, { method: "DELETE" });
    hideModal("modal-profile");
    hideModal("modal-spot");
    refreshSpots();
  } catch (e) {
    alert(e.message);
  }
}

/* ---------------- Boot ---------------- */
async function boot() {
  const me = await api("/me");
  if (!me.user) return showAuth();
  state.user = me.user;
  showApp();
  initMap();
  startPositioning();
  handleDeepLink();
}

function showAuth() {
  $("app-view").classList.add("hidden");
  $("auth-view").classList.remove("hidden");
}
function showApp() {
  $("auth-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("username-label").textContent = "@" + state.user.username;
  setAvatar("avatar-nav", state.user.avatar);
  loadNotifications();
}

/* ---------------- Map ---------------- */
function initMap() {
  if (state.map) return;
  if (!window.L || !window.L.map) {
    $("map-loading").classList.remove("hidden");
    $("map-loading").textContent = "Biblioteca do mapa não carregou. Verifique sua conexão e recarregue.";
    return;
  }
  state.map = L.map("map").setView([-22.9068, -43.1729], 4);
  state.map.attributionControl.setPrefix(false);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap",
  }).addTo(state.map);
  $("map-loading").classList.add("hidden");
}

/* ---------------- Positioning ---------------- */
document.querySelectorAll('input[name="mode"]').forEach((r) =>
  r.addEventListener("change", (e) => {
    state.mode = e.target.value;
    if (state.map) {
      state.map.off("click");
      if (state.mode === "sim") {
        state.map.on("click", (ev) => {
          setPosition(ev.latlng.lat, ev.latlng.lng, true);
        });
        setModeLabel("📌 Simulação: clique no mapa para ser o seu ponto");
      } else {
        if (navigator.geolocation) navigator.geolocation.getCurrentPosition(pos => {
          const p = pos.coords;
          setPosition(p.latitude, p.longitude, false);
        });
        setModeLabel("🗺️ Localização real ativada", true);
      }
      $("map-loading").classList.add("hidden");
    }
  })
);

function startPositioning() {
  function posReal(pos) {
    setPosition(pos.coords.latitude, pos.coords.longitude, false);
  }
  function posSim() {
    $("map-loading").textContent = "Modo simulação: clique no mapa para se posicionar";
    $("map-loading").style.display = "flex";
    state.map.on("click", (ev) => {
      setPosition(ev.latlng.lat, ev.latlng.lng, true);
      $("map-loading").style.display = "none";
    });
  }
  if (navigator.geolocation) {
    navigator.geolocation.getCurrentPosition(
      (pos) => {
        posReal(pos);
        setModeLabel("📶 Localização real ativada", "ok");
      },
      () => {
        // Sem permissão de localização => cair na simulação
        state.mode = "sim";
        document.querySelector('input[value="sim"]').checked = true;
        posSim();
      },
      { enableHighAccuracy: true, timeout: 8000 }
    );
  } else {
    state.mode = "sim";
    document.querySelector('input[value="sim"]').checked = true;
    posSim();
  }
  setModeLabel("📶 Conectando com o GPS…");
}

function setModeLabel(text, cls = "") {
  const el = $("mode-label");
  el.textContent = text;
  el.className = "pill" + (cls ? " " + cls : "");
}

function setPosition(lat, lng, fromSim) {
  state.currentPos = { lat, lng };
  if (state.youMarker) state.youMarker.remove();
  state.youMarker = L.marker([lat, lng], { icon: youIcon() }).addTo(state.map);
  state.map.setView([lat, lng], Math.max(state.map.getZoom(), 14));
  $("pos-info").textContent = fromSim
    ? `Posição simulada: ${lat.toFixed(5)}, ${lng.toFixed(5)}`
    : `Posição real: ${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  refreshSpots();
}

function youIcon() {
  return L.divIcon({ className: "marker-you", iconSize: [18, 18], iconAnchor: [9, 9] });
}

/* ---------------- Spots ---------------- */
async function refreshSpots() {
  if (!state.currentPos) return;
  try {
    const feedQ = state.feedMode === "following" ? "&feed=following" : "";
    const q = `?lat=${state.currentPos.lat}&lng=${state.currentPos.lng}${feedQ}`;
    const data = await api("/spots" + q);
    state.spots = data.spots;
    state.radius = data.radius_m;
    renderMapMarkers();
    renderFeed();
    renderRadiusHint();
  } catch (e) {
    console.error(e);
  }
}

function renderRadiusHint() {
  const near = state.spots.filter((s) => s.unlocked === true);
  const total = state.spots.length;
  $("radius-hint").textContent = total
    ? `${near.length}/${total} lugares desbloqueados (raio ${state.radius}m)`
    : "";
}

function renderMapMarkers() {
  for (const m of state.spotMarkers.values()) m.remove();
  state.spotMarkers.clear();
  state.spots.forEach((s) => {
    const marker = L.marker([s.lat, s.lng], { icon: renderIcon(s) }).addTo(state.map);
    marker.on("click", () => openSpot(s.id));
    state.spotMarkers.set(s.id, marker);
  });
}

function renderIcon(s) {
  if (s.unlocked && s.photo) {
    return L.divIcon({
      className: "marker-unlocked",
      html: `<img src="${s.photo}"/>`,
      iconSize: [46, 46],
      iconAnchor: [23, 23],
    });
  }
  return L.divIcon({
    className: "marker-locked",
    html: `<span class="ring"></span><span>🔒</span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

function renderFeed() {
  const feed = $("feed");
  feed.innerHTML = "";
  $("feed-count").textContent = `(${state.spots.length})`;
  if (!state.spots.length) {
    feed.innerHTML = state.feedMode === "following"
      ? `<div class="feed-card" style="cursor:default">Você ainda não segue ninguém com fotos perto daqui. <button class="link-author" data-user="" id="empty-search-link">Buscar pessoas</button></div>`
      : `<div class="feed-card" style="cursor:default">Nenhum lugar aqui ainda. Toque em <b>＋ Nova foto</b> para ser o primeiro! 📸</div>`;
    const link = $("empty-search-link");
    if (link) link.addEventListener("click", () => showModal("modal-search"));
    return;
  }
  state.spots.forEach((s) => {
    const card = document.createElement("div");
    card.className = "feed-card";
    const unlocked = s.unlocked === true;
    const imgHtml = unlocked
      ? `<img class="fc-img" src="${s.photo}" />`
      : `<div class="fc-img locked">🔒</div>`;
    const dist =
      s.distance_m == null
        ? ""
        : unlocked
        ? `<div class="fc-dist unlocked">✓ Desbloqueada · ${fmtDistance(s.distance_m)}</div>`
        : `<div class="fc-dist locked">🔒 ${fmtDistance(s.distance_m)} · aproxime-se para abrir</div>`;
    const authorAvatar = s.author_avatar
      ? `<img class="avatar-xs" src="${s.author_avatar}" alt=""/>`
      : `<span class="avatar-xs no-avatar"></span>`;
    card.innerHTML = `
      <div class="fc-top">
        ${imgHtml}
        <div style="flex:1">
          <div class="fc-name">${esc(s.name)}</div>
          <div class="fc-meta"><button class="link-author" data-user="${esc(s.author)}">${authorAvatar}@${esc(s.author)}</button> · ♥ ${s.like_count} · ${s.comments.length} comentários</div>
          ${dist}
        </div>
      </div>`;
    const au = card.querySelector(".link-author");
    if (au) au.addEventListener("click", (e) => { e.stopPropagation(); openUserProfile(au.dataset.user); });
    card.addEventListener("click", () => openSpotDetail(s.id));
    feed.appendChild(card);
  });
}

function fmtDistance(m) {
  if (m < 1000) return `${Math.round(m)} m`;
  return `${(m / 1000).toFixed(1)} km`;
}

function refreshRadius(radius) {
  state.radius = radius;
  $("n-radius-label").textContent = radius + " m";
}

/* ---------------- Spot detail modal ---------------- */
async function openSpotDetail(id) {
  state.selectedSpotId = id;
  try {
    const q = `?lat=${state.currentPos.lat}&lng=${state.currentPos.lng}`;
    const data = await api("/spots" + q);
    const spot = data.spots.find((s) => s.id === id);
    if (!spot) return;
    showSpotModal(spot);
  } catch (e) {
    showError("publish-error", e.message);
  }
}

async function showSpotModal(spot) {
  $("spot-title").textContent = spot.name;
  const unlocked = spot.unlocked === true;
  const photoEl = $("spot-photo");
  const lockEl = $("spot-lock");
  if (unlocked) {
    photoEl.innerHTML = `<img src="${spot.photo}" />`;
    photoEl.classList.remove("hidden");
    lockEl.classList.add("hidden");
  } else {
    photoEl.classList.add("hidden");
    lockEl.classList.remove("hidden");
    $("spot-lock-text").textContent = spot.distance_m == null
      ? "Esta foto é privada e só aparece para quem está no local. Para desbloquear, vá até o lugar."
      : `Você está a ${fmtDistance(spot.distance_m)} de distância. Aproxime-se (dentro de ${spot.radius_m} m) para revelar a foto.`;
  }
  $("spot-meta").innerHTML = `Publicado por <button class="link-author" data-user="${esc(spot.author)}">@${esc(spot.author)}</button> · ${fmtDate(spot.created_at)} · raio ${spot.radius_m} m`;
  const metaAuthor = $("spot-meta").querySelector(".link-author");
  if (metaAuthor) metaAuthor.addEventListener("click", () => { hideModal("modal-spot"); openUserProfile(metaAuthor.dataset.user); });
  $("spot-desc").textContent = spot.description || "Sem descrição.";
  $("spot-distance").textContent = spot.distance_m != null
    ? `${unlocked ? "✓ A  " : "🔒 A "}${fmtDistance(spot.distance_m)}`
    : "";
  const likeBtn = $("btn-like");
  $("like-label").textContent = spot.liked ? "Você curtiu" : "Curtir";
  $("like-count").textContent = spot.like_count;
  likeBtn.classList.toggle("liked", spot.liked);

  const delBtn = $("btn-delete-spot");
  delBtn.classList.toggle("hidden", !spot.mine);
  delBtn.onclick = () => deleteSpot(spot.id);

  const cl = $("comments-list");
  cl.innerHTML = spot.comments.length
    ? spot.comments.map((c) => `<div class="comment"><button class="link-author" data-user="${esc(c.author)}">@${esc(c.author)}</button>${esc(c.text)}<span class="c-time">${fmtDate(c.created_at)}</span></div>`).join("")
    : `<div style="color:var(--muted);font-size:13px">Sem comentários ainda.</div>`;
  cl.querySelectorAll(".link-author").forEach((b) =>
    b.addEventListener("click", () => { hideModal("modal-spot"); openUserProfile(b.dataset.user); })
  );

  showModal("modal-spot");
}

$("btn-like").addEventListener("click", async () => {
  if (!state.user) return showError("publish-error", "faça login");
  const id = state.selectedSpotId;
  const res = await api(`/spots/${id}/like`, { method: "POST", body: {} });
  $("like-label").textContent = res.liked ? "Curtido" : "Curtir";
  $("like-count").textContent = res.like_count;
  $("btn-like").classList.toggle("liked", res.liked);
  loadNotifications();
});

$("comment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.user) return;
  const text = $("comment-input").value.trim();
  if (!text) return;
  await api(`/spots/${state.selectedSpotId}/comments`, { method: "POST", body: { text } });
  $("comment-input").value = "";
  loadNotifications();
  openSpotDetail(state.selectedSpotId);
});

$("btn-share").addEventListener("click", async () => {
  const id = state.selectedSpotId;
  if (!id) return;
  const url = location.origin + "/#spot=" + id;
  try {
    await navigator.clipboard.writeText(url);
    alert("Link copiado! Envie para um amigo abrir este lugar: " + url);
  } catch (e) {
    prompt("Copie o link:", url);
  }
});

$("btn-report").addEventListener("click", () => {
  $("report-box").classList.remove("hidden");
  $("report-msg").textContent = "";
});

$("btn-send-report").addEventListener("click", async () => {
  const reason = $("report-reason").value.trim();
  if (!reason) { $("report-msg").textContent = "Informe um motivo (ex: foto imprópria)."; return; }
  try {
    await api(`/spots/${state.selectedSpotId}/report`, { method: "POST", body: { reason } });
    $("report-box").classList.add("hidden");
    $("report-reason").value = "";
    $("report-msg").textContent = "Denúncia enviada. Obrigado!";
  } catch (e) {
    $("report-msg").textContent = e.message;
  }
});

/* ---------------- New spot modal ---------------- */
$("btn-new").addEventListener("click", () => {
  if (!state.currentPos) {
    showError("publish-error", "aguarde sua posição ser detectada");
    return;
  }
  $("photo-preview").classList.add("hidden");
  $("photo-placeholder").style.display = "block";
  hideError("publish-error");
  $("n-name").value = "";
  $("n-desc").value = "";
  $("n-radius").value = 500;
  refreshRadius(500);
  $("n-pos").textContent = `Sua posição: ${state.currentPos.lat.toFixed(5)}, ${state.currentPos.lng.toFixed(5)}`;
  showModal("modal-new");
});

$("photo-drop").addEventListener("click", () => $("photo-input").click());
$("photo-input").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (!f) return;
  if (!f.type.startsWith("image/")) return;
  const reader = new FileReader();
  reader.onload = () => {
    $("photo-preview").src = reader.result;
    $("photo-preview").classList.remove("hidden");
    $("photo-placeholder").style.display = "none";
  };
  reader.readAsDataURL(f);
});
$("n-radius").addEventListener("input", (e) => refreshRadius(parseInt(e.target.value, 10)));

$("btn-publish").addEventListener("click", async () => {
  if (!state.user) return;
  hideError("publish-error");
  const photo = $("photo-preview").src;
  if (!photo || photo.startsWith(location.origin)) {
    return showError("publish-error", "escolha uma foto primeiro");
  }
  const body = {
    name: $("n-name").value,
    description: $("n-desc").value,
    lat: state.currentPos.lat,
    lng: state.currentPos.lng,
    photo,
    radius_m: parseInt($("n-radius").value, 10),
  };
  try {
    await api("/spots", { method: "POST", body });
    hideModal("modal-new");
    refreshSpots();
  } catch (err) {
    showError("publish-error", err.message);
  }
});

/* ---------------- Search ---------------- */
$("btn-search").addEventListener("click", () => {
  $("search-input").value = "";
  $("search-results").innerHTML = "";
  showModal("modal-search");
  setTimeout(() => $("search-input").focus(), 60);
});

async function runSearch() {
  const q = $("search-input").value.trim();
  const res = $("search-results");
  if (!q) return;
  res.innerHTML = `<div class="hint">Buscando…</div>`;
  try {
    let qs = `?q=${encodeURIComponent(q)}`;
    if (state.currentPos) qs += `&lat=${state.currentPos.lat}&lng=${state.currentPos.lng}`;
    const d = await api("/search" + qs);
    if (!d.users.length && !d.spots.length) {
      res.innerHTML = `<div class="hint">Nada encontrado para "${esc(q)}".</div>`;
      return;
    }
    res.innerHTML = "";
    d.users.forEach((u) => {
      const row = document.createElement("div");
      row.className = "search-row-item";
      row.innerHTML = `
        ${u.avatar ? `<img class="avatar-sm" src="${u.avatar}" alt=""/>` : `<span class="avatar-sm no-avatar"></span>`}
        <span class="search-row-name">@${esc(u.username)}</span>
        <small>${esc(u.bio || "")}</small>`;
      row.addEventListener("click", () => { hideModal("modal-search"); openUserProfile(u.username); });
      res.appendChild(row);
    });
    d.spots.forEach((s) => {
      const row = document.createElement("div");
      row.className = "search-row-item";
      row.innerHTML = `
        ${s.photo ? `<img class="search-thumb" src="${s.photo}" alt=""/>` : `<span class="search-thumb lock">🔒</span>`}
        <span class="search-row-name">${esc(s.name)}</span>
        <small>@${esc(s.author)}</small>`;
      row.addEventListener("click", () => { hideModal("modal-search"); openSpotDetail(s.id); });
      res.appendChild(row);
    });
  } catch (e) {
    res.innerHTML = `<div class="hint">${esc(e.message)}</div>`;
  }
}
$("btn-search-go").addEventListener("click", runSearch);
$("search-input").addEventListener("keydown", (e) => { if (e.key === "Enter") runSearch(); });

/* ---------------- Notifications ---------------- */
async function loadNotifications() {
  try {
    const d = await api("/notifications");
    const badge = $("notif-badge");
    badge.textContent = d.unread || "";
    badge.classList.toggle("hidden", !d.unread);
  } catch (e) {}
}

$("btn-notifs").addEventListener("click", async () => {
  try {
    const d = await api("/notifications");
    const list = $("notif-list");
    list.innerHTML = "";
    $("notif-empty").classList.toggle("hidden", d.notifications.length > 0);
    d.notifications.forEach((n) => {
      const div = document.createElement("div");
      div.className = "notif" + (n.read ? "" : " unread");
      div.innerHTML = `
        <div class="notif-head"><span class="notif-actor">@${esc(n.actor)}</span><span class="notif-time">${fmtDate(n.created_at)}</span></div>
        <div class="notif-text">${esc(n.type === "follow" ? "começou a seguir você" : n.text || "")}</div>
        ${n.spot_id ? `<button class="notif-goto" data-spot="${n.spot_id}">Ver lugar</button>` : ""}`;
      const go = div.querySelector(".notif-goto");
      if (go) go.addEventListener("click", () => { hideModal("modal-notifs"); openSpotDetail(parseInt(go.dataset.spot, 10)); });
      list.appendChild(div);
    });
    showModal("modal-notifs");
    await api("/notifications/read", { method: "POST" });
    $("notif-badge").classList.add("hidden");
    $("notif-badge").textContent = "";
  } catch (e) {
    alert(e.message);
  }
});

/* ---------------- Public user profile & follow ---------------- */
async function openUserProfile(username) {
  try {
    let qs = "";
    if (state.currentPos) qs = `?lat=${state.currentPos.lat}&lng=${state.currentPos.lng}`;
    const d = await api(`/users/${encodeURIComponent(username)}` + qs);
    $("user-title").textContent = "@" + d.username;
    setAvatar("user-avatar", d.avatar);
    $("user-bio").textContent = d.bio || "Sem biografia.";
    const btn = $("btn-follow");
    if (!state.user || d.username === state.user.username) {
      btn.classList.add("hidden");
    } else {
      btn.classList.remove("hidden");
      btn.textContent = d.is_following ? "✓ Seguindo" : "Seguir";
    }
    $("user-follow-hint").textContent = d.follows_me ? "Este perfil segue você" : "";
    $("user-stats").innerHTML = `
      <div class="stat"><b>${d.stats.spots}</b><span>fotos</span></div>
      <div class="stat"><b>${d.stats.followers}</b><span>seguidores</span></div>
      <div class="stat"><b>${d.stats.following}</b><span>seguindo</span></div>`;
    renderProfileGrid("user-spots", "user-empty", d.spots, false);
    window._userProfile = d;
    showModal("modal-user");
  } catch (e) {
    alert(e.message);
  }
}

$("btn-follow").addEventListener("click", async () => {
  const u = window._userProfile;
  if (!u || !state.user) return;
  try {
    const res = await api(`/users/${u.id}/follow`, { method: "POST", body: {} });
    u.is_following = res.following;
    u.stats.followers = res.followers;
    $("btn-follow").textContent = res.following ? "✓ Seguindo" : "Seguir";
    const statEls = $("user-stats").querySelectorAll(".stat");
    if (statEls[1]) statEls[1].querySelector("b").textContent = res.followers;
    loadNotifications();
    if (state.feedMode === "following") refreshSpots();
  } catch (e) {
    alert(e.message);
  }
});

/* ---------------- Feed tabs ---------------- */
$("tab-feed-all").addEventListener("click", () => setFeed("all"));
$("tab-feed-following").addEventListener("click", () => setFeed("following"));
function setFeed(mode) {
  state.feedMode = mode;
  $("tab-feed-all").classList.toggle("active", mode === "all");
  $("tab-feed-following").classList.toggle("active", mode === "following");
  refreshSpots();
}

/* ---------------- Deep link (#spot=ID) ---------------- */
function handleDeepLink() {
  const m = location.hash.match(/^#spot=(\d+)$/);
  if (!m) return;
  const id = parseInt(m[1], 10);
  const tryOpen = () => {
    if (state.currentPos) { openSpotDetail(id); return true; }
    return false;
  };
  if (!tryOpen()) {
    const iv = setInterval(() => { if (tryOpen()) clearInterval(iv); }, 500);
    setTimeout(() => clearInterval(iv), 20000);
  }
}

/* ---------------- Modal helpers ---------------- */
function showModal(id) {
  $(id)?.classList.remove("hidden");
}
function hideModal(id) {
  $(id)?.classList.add("hidden");
}
document.querySelectorAll("[data-close]").forEach((b) =>
  b.addEventListener("click", () => b.closest(".modal").classList.add("hidden"))
);
document.querySelectorAll(".modal").forEach((m) =>
  m.addEventListener("click", (e) => {
    if (e.target === m) m.classList.add("hidden");
  })
);

function showError(id, msg) {
  const el = $(id);
  el.textContent = msg;
  el.classList.remove("hidden");
}
function hideError(id) {
  $(id)?.classList.add("hidden");
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function fmtDate(s) {
  if (!s) return "";
  const d = new Date(s + "Z");
  return isNaN(d) ? s : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

$("btn-locate").addEventListener("click", () => {
  if (state.currentPos) {
    state.map.setView([state.currentPos.lat, state.currentPos.lng], 15);
    refreshSpots();
  }
});

function fatal(msg) {
  const el = $("fatal");
  el.classList.remove("hidden");
  el.innerHTML = `<b>⚠️ Não foi possível carregar o NearGram.</b>
    <p>${esc(msg || "Falha ao inicializar o aplicativo.")}</p>`;
  const btn = document.createElement("button");
  btn.className = "btn-primary";
  btn.textContent = "🔄 Recarregar";
  btn.onclick = () => location.reload();
  el.appendChild(btn);
}

boot().catch((err) => {
  console.error(err);
  fatal("Não foi possível carregar o NearGram.");
});

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}