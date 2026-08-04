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
};

const API = "/api";

async function api(path, opts = {}) {
  const res = await fetch(API + path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...opts,
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
  await api("/api/logout", { method: "POST" });
  state.user = null;
  showAuth();
});

/* ---------------- Boot ---------------- */
async function boot() {
  const me = await api("/api/me");
  if (!me.user) return showAuth();
  state.user = me.user;
  showApp();
  initMap();
  startPositioning();
}

function showAuth() {
  $("app-view").classList.add("hidden");
  $("auth-view").classList.remove("hidden");
}
function showApp() {
  $("auth-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("username-label").textContent = "@" + state.user.username;
}

/* ---------------- Map ---------------- */
function initMap() {
  if (state.map) return;
  state.map = L.map("map").setView([-22.9068, -43.1729], 4);
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
    const q = `?lat=${state.currentPos.lat}&lng=${state.currentPos.lng}`;
    const data = await api("/api/spots" + q);
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
    feed.innerHTML = `<div class="feed-card" style="cursor:default">Nenhum lugar aqui ainda. Toque em <b>＋ Nova foto</b> para ser o primeiro! 📸</div>`;
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
    card.innerHTML = `
      <div class="fc-top">
        ${imgHtml}
        <div style="flex:1">
          <div class="fc-name">${esc(s.name)}</div>
          <div class="fc-meta">@${esc(s.author)} · ♥ ${s.like_count} · ${s.comments.length} comentários</div>
          ${dist}
        </div>
      </div>`;
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
    const data = await api("/api/spots" + q);
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
  $("spot-meta").textContent = `Publicado por @${spot.author} · ${fmtDate(spot.created_at)} · raio ${spot.radius_m} m`;
  $("spot-desc").textContent = spot.description || "Sem descrição.";
  $("spot-distance").textContent = spot.distance_m != null
    ? `${unlocked ? "✓ A  " : "🔒 A "}${fmtDistance(spot.distance_m)}`
    : "";
  const likeBtn = $("btn-like");
  likeBtn.textContent = spot.liked ? "♥ Você curtiu" : `♥ Curtir`;
  $("like-count").textContent = spot.like_count;
  likeBtn.classList.toggle("liked", spot.liked);

  const cl = $("comments-list");
  cl.innerHTML = spot.comments.length
    ? spot.comments.map((c) => `<div class="comment"><span class="c-author">@${esc(c.author)}</span>${esc(c.text)}<span class="c-time">${fmtDate(c.created_at)}</span></div>`).join("")
    : `<div style="color:var(--muted);font-size:13px">Sem comentários ainda.</div>`;

  showModal("modal-spot");
}

$("btn-like").addEventListener("click", async () => {
  if (!state.user) return showError("publish-error", "faça login");
  const id = state.selectedSpotId;
  const res = await api(`/api/spots/${id}/like`, { method: "POST", body: {} });
  $("btn-like").textContent = res.liked ? "♥ Curtido" : "♥ Curtir";
  $("like-count").textContent = res.like_count;
  $("btn-like").classList.toggle("liked", res.liked);
});

$("comment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.user) return;
  const text = $("comment-input").value.trim();
  if (!text) return;
  await api(`/api/spots/${state.selectedSpotId}/comments`, { method: "POST", body: { text } });
  $("comment-input").value = "";
  openSpotDetail(state.selectedSpotId);
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
    await api("/api/spots", { method: "POST", body });
    hideModal("modal-new");
    refreshSpots();
  } catch (err) {
    showError("publish-error", err.message);
  }
});

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

boot();