const $ = (id) => document.getElementById(id);

let state = {
  user: null,
  map: null,
  youMarker: null,
  radiusCircle: null,
  tileLayer: null,
  clusterGroup: null,
  spots: [],
  radius: 500,
  mode: "real", // real | sim
  currentPos: null, // {lat, lng}
  selectedSpotId: null,
  feedMode: "all", // all | following
  offset: 0,
  hasMore: false,
};

const API = "/api";
const SPOT_PAGE = 20;

/* ---------------- Telemetria (consentida) ----------------
   Só coleta dados de quem aceitou o aviso de privacidade.
   A localização enviada é arredondada (precisão de ~1 km). */
const Telemetry = (() => {
  const LS = "ng-consent";
  let enabled = localStorage.getItem(LS) === "1";
  let queue = [];
  let timer = null;
  let errorCount = 0;

  function track(event, props = {}) {
    if (!enabled) return;
    queue.push({
      event,
      props,
      lat: state.currentPos ? +state.currentPos.lat.toFixed(2) : null,
      lng: state.currentPos ? +state.currentPos.lng.toFixed(2) : null,
    });
    if (queue.length >= 10) { flush(); return; }
    if (!timer) timer = setTimeout(flush, 8000);
  }

  async function flush() {
    timer = null;
    if (!enabled || !queue.length) return;
    const batch = queue;
    queue = [];
    try {
      await fetch(API + "/telemetry", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Consent": "1" },
        credentials: "same-origin",
        body: JSON.stringify({ events: batch }),
      });
    } catch (e) { /* melhor esforço */ }
  }

  function setEnabled(v) {
    enabled = !!v;
    localStorage.setItem(LS, enabled ? "1" : "0");
  }

  function trackError(msg) {
    if (errorCount >= 5) return;
    errorCount++;
    track("error", { msg: String(msg).slice(0, 120) });
  }

  window.addEventListener("pagehide", () => {
    if (!enabled || !queue.length) return;
    const batch = queue;
    queue = [];
    try {
      fetch(API + "/telemetry", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Consent": "1" },
        credentials: "same-origin",
        body: JSON.stringify({ events: batch }),
        keepalive: true,
      });
    } catch (e) { /* melhor esforço */ }
  });

  return { track, flush, setEnabled, trackError, isEnabled: () => enabled };
})();
window.addEventListener("error", (e) => Telemetry.trackError(e.message));

/* ---------------- Privacidade & consentimento ---------------- */
function setConsent(v) {
  Telemetry.setEnabled(v);
  localStorage.setItem("ng-consent", v ? "1" : "0");
  const banner = $("consent-banner");
  if (banner) banner.classList.add("hidden");
  const sw = $("tg-telemetry");
  if (sw) sw.checked = v;
  if (state.user) {
    api("/telemetry/consent", { method: "POST", body: { enabled: v } }).catch(() => {});
  }
  if (v) Telemetry.track("consent_granted");
}
$("btn-consent-accept")?.addEventListener("click", () => setConsent(true));
$("btn-consent-refuse")?.addEventListener("click", () => setConsent(false));
$("btn-privacy-open")?.addEventListener("click", () => showModal("modal-privacy"));
$("btn-privacy-auth")?.addEventListener("click", () => showModal("modal-privacy"));
$("btn-privacy-profile")?.addEventListener("click", () => showModal("modal-privacy"));
$("tg-telemetry")?.addEventListener("change", (e) => setConsent(e.target.checked));

(function initConsent() {
  if (localStorage.getItem("ng-consent") !== null) {
    const banner = $("consent-banner");
    if (banner) banner.classList.add("hidden");
  }
  const sw = $("tg-telemetry");
  if (sw) sw.checked = Telemetry.isEnabled();
})();

/* ---------------- Toasts ---------------- */
function toast(msg, type = "") {
  const host = $("toasts");
  if (!host) return;
  const el = document.createElement("div");
  el.className = "toast " + type;
  el.textContent = msg;
  host.appendChild(el);
  setTimeout(() => { el.style.opacity = "0"; el.style.transition = "opacity .3s"; }, 2200);
  setTimeout(() => el.remove(), 2600);
}

function toastAction(msg, label, fn) {
  const host = $("toasts");
  if (!host) return;
  const el = document.createElement("div");
  el.className = "toast action";
  const txt = document.createElement("span");
  txt.textContent = msg;
  const b = document.createElement("button");
  b.textContent = label;
  b.addEventListener("click", () => { el.remove(); fn(); });
  el.appendChild(txt);
  el.appendChild(b);
  host.appendChild(el);
}

/* ---------------- Conexão ---------------- */
window.addEventListener("offline", () => {
  toast("Sem conexão — seus dados locais continuam salvos", "err");
  Telemetry.track("connectivity", { state: "offline" });
});
window.addEventListener("online", () => {
  toast("Conectado de novo! Atualizando…", "ok");
  Telemetry.track("connectivity", { state: "online" });
  if (state.user) { refreshSpots(); loadNotifications(); }
});

/* ---------------- Instalação PWA ---------------- */
let deferredInstall = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  deferredInstall = e;
  $("btn-install").classList.remove("hidden");
});
$("btn-install").addEventListener("click", async () => {
  if (!deferredInstall) return;
  deferredInstall.prompt();
  const choice = await deferredInstall.userChoice;
  deferredInstall = null;
  $("btn-install").classList.add("hidden");
  if (choice && choice.outcome === "accepted") Telemetry.track("install_pwa");
});

/* ---------------- Tema claro/escuro ---------------- */
const SATELLITE_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}";
const SATELLITE_LABELS_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}";
const STREET_URL = "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png";

function applyTheme(t) {
  document.documentElement.dataset.theme = t;
  localStorage.setItem("ng-theme", t);
  $("btn-theme").textContent = t === "light" ? "☀️" : "🌙";
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", t === "light" ? "#f4f4f7" : "#0f0f14");
}

function initTiles() {
  if (!state.map || state.tileLayer) return;
  state.tileLayer = L.tileLayer(SATELLITE_URL, {
    maxZoom: 18,
    attribution: "&copy; Esri, Maxar, Earthstar Geographics",
  }).addTo(state.map);
  state.labelsLayer = L.tileLayer(SATELLITE_LABELS_URL, { maxZoom: 18 }).addTo(state.map);
  state.streetLayer = L.tileLayer(STREET_URL, {
    maxZoom: 19,
    attribution: "&copy; OpenStreetMap contributors",
  });
  L.control.layers(
    { "🛰️ Satélite": state.tileLayer, "🗺️ Mapa": state.streetLayer },
    null,
    { position: "topleft" }
  ).addTo(state.map);
  L.control.scale({ imperial: false, position: "bottomright" }).addTo(state.map);

  // Restaura a camada favorita da última sessão (Satélite padrão).
  const saved = localStorage.getItem("ng-map-layer");
  if (saved === "street") {
    state.map.removeLayer(state.tileLayer);
    state.map.removeLayer(state.labelsLayer);
    state.streetLayer.addTo(state.map);
  }
  state.map.on("baselayerchange", () => {
    const cur = state.streetLayer._map ? "street" : "satellite";
    localStorage.setItem("ng-map-layer", cur);
  });
}

$("btn-theme").addEventListener("click", () => {
  const cur = document.documentElement.dataset.theme === "light" ? "light" : "dark";
  const next = cur === "light" ? "dark" : "light";
  applyTheme(next);
  Telemetry.track("theme", { theme: next });
});
const _savedTheme = localStorage.getItem("ng-theme");
const _systemLight = window.matchMedia && window.matchMedia("(prefers-color-scheme: light)").matches;
applyTheme(_savedTheme || (_systemLight ? "light" : "dark"));

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

const _webpSupported = (() => {
  try {
    return document.createElement("canvas").toDataURL("image/webp").startsWith("data:image/webp");
  } catch (e) {
    return false;
  }
})();

function compressImage(dataUrl, maxDim, quality) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => {
      try {
        let { width, height } = img;
        const scale = Math.min(1, maxDim / Math.max(width, height));
        width = Math.round(width * scale);
        height = Math.round(height * scale);
        const canvas = document.createElement("canvas");
        canvas.width = width;
        canvas.height = height;
        canvas.getContext("2d").drawImage(img, 0, 0, width, height);
        const mime = _webpSupported ? "image/webp" : "image/jpeg";
        let out = canvas.toDataURL(mime, quality);
        if (out.length > MAX_UPLOAD_B64) out = canvas.toDataURL(mime, 0.65);
        if (out.length > MAX_UPLOAD_B64 && mime !== "image/jpeg") out = canvas.toDataURL("image/jpeg", 0.65);
        resolve(out);
      } catch (e) {
        reject(e);
      }
    };
    img.onerror = () => reject(new Error("não foi possível ler a imagem"));
    img.src = dataUrl;
  });
}

/* ---------------- Notificações push ---------------- */
async function enablePush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window) || state._pushTried) return;
  state._pushTried = true;
  if (localStorage.getItem("ng-push-denied")) return;
  try {
    const res = await api("/push/vapid-public-key");
    if (!res.key) return;
    const reg = await navigator.serviceWorker.ready;
    const sub = await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(res.key),
    });
    await api("/push/subscribe", {
      method: "POST",
      body: { endpoint: sub.endpoint, p256dh: btoa(String.fromCharCode(...new Uint8Array(sub.getKey("p256dh")))), auth: btoa(String.fromCharCode(...new Uint8Array(sub.getKey("auth")))) },
    });
  } catch (e) {
    console.warn("push não habilitado:", e);
    if (e && (e.name === "NotAllowedError" || e.name === "PermissionDeniedError")) {
      localStorage.setItem("ng-push-denied", "1");
    }
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = window.atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; i++) outputArray[i] = rawData.charCodeAt(i);
  return outputArray;
}

const MAX_UPLOAD_B64 = 8 * 1024 * 1024;

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
      ${s.photo ? `<img src="${s.photo}" loading="lazy" decoding="async" alt="" />` : `<div class="pg-lock">🔒</div>`}
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

async function openOwnProfile() {
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
    toast(e.message, "err");
  }
}
$("btn-profile").addEventListener("click", openOwnProfile);

$("btn-edit-profile").addEventListener("click", () => {
  $("profile-edit").classList.remove("hidden");
});

$("avatar-input").addEventListener("change", async (e) => {
  const f = e.target.files[0];
  if (!f || !f.type.startsWith("image/")) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const small = await compressImage(reader.result, 512, 0.85);
      $("profile-avatar").src = small;
      window._newAvatar = small;
    } catch (err) {
      alert(err.message);
    }
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
    toast("Perfil atualizado!", "ok");
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
    toast("Foto excluída", "ok");
    refreshSpots();
  } catch (e) {
    alert(e.message);
  }
}

/* ---------------- Excluir conta ---------------- */
$("btn-show-delete-account").addEventListener("click", () => {
  $("del-pass").value = "";
  hideError("delete-account-error");
  $("delete-account-box").classList.remove("hidden");
});
$("btn-cancel-delete-account").addEventListener("click", () => {
  $("delete-account-box").classList.add("hidden");
});
$("btn-confirm-delete-account").addEventListener("click", async () => {
  const btn = $("btn-confirm-delete-account");
  hideError("delete-account-error");
  btn.disabled = true;
  btn.textContent = "Excluindo…";
  try {
    await api("/me", { method: "DELETE", body: { password: $("del-pass").value } });
    hideModal("modal-profile");
    state.user = null;
    toast("Conta excluída", "ok");
    showAuth();
  } catch (e) {
    showError("delete-account-error", e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Confirmar exclusão";
  }
});

/* ---------------- Alterar senha ---------------- */
$("btn-show-change-pass").addEventListener("click", () => {
  $("cp-current").value = "";
  $("cp-new").value = "";
  hideError("change-pass-error");
  $("change-pass-box").classList.remove("hidden");
});
$("btn-cancel-change-pass").addEventListener("click", () => {
  $("change-pass-box").classList.add("hidden");
});
$("btn-confirm-change-pass").addEventListener("click", async () => {
  const btn = $("btn-confirm-change-pass");
  hideError("change-pass-error");
  btn.disabled = true;
  btn.textContent = "Salvando…";
  try {
    await api("/profile/password", {
      method: "POST",
      body: { current_password: $("cp-current").value, new_password: $("cp-new").value },
    });
    $("change-pass-box").classList.add("hidden");
    toast("Senha alterada!", "ok");
  } catch (e) {
    showError("change-pass-error", e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Salvar nova senha";
  }
});

/* ---------------- Boot ---------------- */
async function boot() {
  const me = await api("/me");
  Telemetry.track("app_open", { ms: Math.round(performance.now()), user: !!me.user });
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
  if (state._notifTimer) { clearInterval(state._notifTimer); state._notifTimer = null; }
}
function showApp() {
  $("auth-view").classList.add("hidden");
  $("app-view").classList.remove("hidden");
  $("username-label").textContent = "@" + state.user.username;
  setAvatar("avatar-nav", state.user.avatar);
  loadNotifications();
  loadSuggestedUsers();
  if (!state._notifTimer) {
    state._notifTimer = setInterval(loadNotifications, 30000);
  }
  enablePush();
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
  state.map.on("baselayerchange", (e) => Telemetry.track("map_layer", { layer: e.name }));
  initTiles();
  $("map-loading").classList.add("hidden");
}

/* ---------------- Positioning ---------------- */
document.querySelectorAll('input[name="mode"]').forEach((r) =>
  r.addEventListener("change", (e) => {
    state.mode = e.target.value;
    if (state.map) {
      state.map.off("click");
      if (state.mode === "sim") {
        const saved = _savedMapPos();
        if (saved) {
          setPosition(saved.lat, saved.lng, true);
          setModeLabel("📌 Simulação: clique no mapa para se posicionar");
          return;
        }
        state.map.on("click", (ev) => {
          setPositionDebounced(ev.latlng.lat, ev.latlng.lng, true);
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
    const saved = _savedMapPos();
    if (saved && state.map) {
      setPosition(saved.lat, saved.lng, true);
      state.map.setView([saved.lat, saved.lng], saved.zoom || 14);
      setModeLabel("📌 Última posição restaurada (modo simulação)");
      $("map-loading").style.display = "none";
      return;
    }
    $("map-loading").textContent = "Modo simulação: clique no mapa para se posicionar";
    $("map-loading").style.display = "flex";
    state.map.on("click", (ev) => {
      setPositionDebounced(ev.latlng.lat, ev.latlng.lng, true);
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
  const targetZoom = Math.max(state.map.getZoom(), 14);
  state.map.setView([lat, lng], targetZoom);
  try { localStorage.setItem("ng-map-pos", JSON.stringify({ lat, lng, zoom: targetZoom })); } catch (_) {}
  $("pos-info").textContent = fromSim
    ? `Posição simulada: ${lat.toFixed(5)}, ${lng.toFixed(5)}`
    : `Posição real: ${lat.toFixed(5)}, ${lng.toFixed(5)}`;
  refreshSpots();
}

let _posDebounce = null;
function setPositionDebounced(lat, lng, fromSim) {
  clearTimeout(_posDebounce);
  _posDebounce = setTimeout(() => setPosition(lat, lng, fromSim), 220);
}

function youIcon() {
  return L.divIcon({ className: "marker-you", iconSize: [18, 18], iconAnchor: [9, 9] });
}

function _savedMapPos() {
  try {
    const raw = localStorage.getItem("ng-map-pos");
    if (!raw) return null;
    const p = JSON.parse(raw);
    if (typeof p.lat === "number" && typeof p.lng === "number") return p;
  } catch (_) {}
  return null;
}

/* ---------------- Spots ---------------- */
async function refreshSpots() {
  if (!state.currentPos) return;
  const hadCards = $("feed").querySelectorAll(".feed-card").length > 0;
  if (!hadCards) {
    $("feed").innerHTML = `
      <div class="skeleton-card"></div>
      <div class="skeleton-card"></div>
      <div class="skeleton-card"></div>`;
  }
  state.spots = [];
  state.offset = 0;
  state.hasMore = false;
  try {
    await loadSpots();
  } catch (e) {
    console.error(e);
  }
}

async function loadSpots() {
  const feedQ = state.feedMode === "following" ? "&feed=following" : "";
  const q = `?lat=${state.currentPos.lat}&lng=${state.currentPos.lng}${feedQ}&limit=${SPOT_PAGE}&offset=${state.offset}`;
  const data = await api("/spots" + q);
  state.radius = data.radius_m;
  if (state.offset === 0) state.spots = data.spots;
  else state.spots = state.spots.concat(data.spots);
  state.offset += data.spots.length;
  state.hasMore = data.has_more;
  renderMapMarkers();
  renderFeed();
  renderRadiusHint();
}

async function loadMore() {
  if (!state.hasMore || state._loadingMore) return;
  state._loadingMore = true;
  const btn = $("btn-load-more");
  if (btn) { btn.disabled = true; btn.textContent = "Carregando…"; }
  try {
    await loadSpots();
  } catch (e) {
    toast(e.message, "err");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Carregar mais lugares"; }
    state._loadingMore = false;
  }
}

function renderRadiusHint() {
  const near = state.spots.filter((s) => s.unlocked === true);
  const total = state.spots.length;
  $("radius-hint").textContent = total
    ? `${near.length}/${total} lugares desbloqueados (raio ${state.radius}m)`
    : "";
  renderRadiusCircle();
}

function cssVar(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || "#31c46e";
}

function renderRadiusCircle() {
  if (!state.map) return;
  if (state.radiusCircle) state.radiusCircle.remove();
  if (!state.currentPos) return;
  const ok = cssVar("--ok");
  state.radiusCircle = L.circle([state.currentPos.lat, state.currentPos.lng], {
    radius: state.radius,
    color: ok,
    fillColor: ok,
    fillOpacity: 0.08,
    weight: 1.5,
    interactive: false,
  }).addTo(state.map);
}

function renderMapMarkers() {
  if (!state.clusterGroup) {
    state.clusterGroup = L.markerClusterGroup({ showCoverageOnHover: false });
    state.map.addLayer(state.clusterGroup);
  }
  state.clusterGroup.clearLayers();
  state.spots.forEach((s) => {
    const marker = L.marker([s.lat, s.lng], { icon: renderIcon(s) });
    marker.bindPopup(popupHtml(s), { autoClose: true, closeButton: true, maxWidth: 220 });
    marker.on("click", (e) => e.target.openPopup());
    state.clusterGroup.addLayer(marker);
  });
}

function popupHtml(s) {
  const unlocked = s.unlocked === true;
  const thumb = unlocked && s.photo
    ? `<img class="popup-thumb" src="${s.photo}" alt="${esc(s.name)}" />`
    : `<div class="popup-thumb locked">🔒</div>`;
  const dist = s.distance_m == null ? "" : ` · ${fmtDistance(s.distance_m)}`;
  const status = unlocked
    ? `<span class="popup-status ok">✓ Desbloqueada</span>`
    : `<span class="popup-status">🔒 Fechada</span>`;
  return `
    <div class="popup-box">
      ${thumb}
      <div class="popup-info">
        <b>${esc(s.name)}</b>
        <div class="popup-sub">@${esc(s.author)}${dist}</div>
        <div>${status}</div>
        <button class="popup-open btn-primary" data-id="${s.id}">Ver detalhes</button>
      </div>
    </div>`;
}
document.addEventListener("click", (e) => {
  const b = e.target.closest(".popup-open");
  if (b) {
    state.map.closePopup();
    openSpotDetail(parseInt(b.dataset.id, 10));
  }
});

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
  state.spots.forEach((s, idx) => {
    const card = document.createElement("div");
    card.className = "feed-card";
    const unlocked = s.unlocked === true;
    const imgHtml = unlocked
      ? `<img class="fc-img" src="${s.photo}" loading="lazy" decoding="async" ${idx === 0 ? 'fetchpriority="high"' : ""} alt="${esc(s.name)}" />`
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
          <div class="fc-meta"><button class="link-author" data-user="${esc(s.author)}">${authorAvatar}@${esc(s.author)}</button> · ${s.comments.length} comentários</div>
          ${dist}
        </div>
        <button class="fc-like${s.liked ? " liked" : ""}" data-id="${s.id}" title="Curtir">♥ <span>${s.like_count}</span></button>
      </div>`;
    const au = card.querySelector(".link-author");
    if (au) au.addEventListener("click", (e) => { e.stopPropagation(); openUserProfile(au.dataset.user); });
    const likeBtn = card.querySelector(".fc-like");
    likeBtn.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!state.user) { toast("faça login para curtir", "err"); return; }
      try {
        const res = await api(`/spots/${s.id}/like`, { method: "POST", body: {} });
        s.liked = res.liked;
        s.like_count = res.like_count;
        likeBtn.classList.toggle("liked", res.liked);
        likeBtn.querySelector("span").textContent = res.like_count;
        loadNotifications();
      } catch (err) {
        toast(err.message, "err");
      }
    });
    card.addEventListener("click", () => openSpotDetail(s.id));
    feed.appendChild(card);
  });
  if (state.hasMore) {
    const lm = document.createElement("button");
    lm.id = "btn-load-more";
    lm.textContent = "Carregar mais lugares";
    lm.addEventListener("click", loadMore);
    feed.appendChild(lm);
    observeLoadMore(lm);
  }
}

let _feedObserver = null;
function observeLoadMore(el) {
  if (_feedObserver) _feedObserver.disconnect();
  if (!("IntersectionObserver" in window)) return;
  _feedObserver = new IntersectionObserver((entries) => {
    if (entries.some((en) => en.isIntersecting)) loadMore();
  }, { root: $("feed"), rootMargin: "100px" });
  _feedObserver.observe(el);
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
  Telemetry.track("open_spot", { spot: id });
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
    photoEl.innerHTML = `<img src="${spot.photo}" loading="lazy" decoding="async" alt="${esc(spot.name)}" />`;
    photoEl.classList.remove("hidden");
    lockEl.classList.add("hidden");
    const pimg = photoEl.querySelector("img");
    if (pimg) pimg.addEventListener("click", (e) => { e.stopPropagation(); openLightbox(pimg.src); });
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

  const editBtn = $("btn-edit-spot");
  editBtn.classList.toggle("hidden", !spot.mine);
  $("spot-edit").classList.add("hidden");
  hideError("edit-error");

  const gotoBtn = $("btn-goto-map");
  gotoBtn.onclick = () => {
    hideModal("modal-spot");
    if (state.map) {
      state.map.setView([spot.lat, spot.lng], 16);
      refreshSpots();
    }
  };

  const cl = $("comments-list");
  cl.innerHTML = spot.comments.length
    ? spot.comments.map((c) => {
        const mine = spot.mine || (state.user && c.author === state.user.username);
        const isAuthor = state.user && c.author === state.user.username;
        return `<div class="comment">
          <button class="link-author" data-user="${esc(c.author)}">@${esc(c.author)}</button>
          <span class="c-text">${esc(c.text)}</span>
          <span class="c-time">${timeAgo(c.created_at)}</span>
          ${isAuthor ? `<button class="c-edit" data-id="${c.id}" data-text="${esc(c.text)}" title="Editar comentário">✏️</button>` : ""}
          ${mine ? `<button class="c-del" data-id="${c.id}" title="Excluir comentário">✕</button>` : ""}
        </div>`;
      }).join("")
    : `<div style="color:var(--muted);font-size:13px">Sem comentários ainda.</div>`;
  cl.querySelectorAll(".link-author").forEach((b) =>
    b.addEventListener("click", () => { hideModal("modal-spot"); openUserProfile(b.dataset.user); })
  );
  cl.querySelectorAll(".c-edit").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      const t = prompt("Editar comentário", b.dataset.text);
      if (t === null) return;
      const text = t.trim();
      if (!text) return;
      try {
        await api(`/comments/${b.dataset.id}`, { method: "PATCH", body: { text } });
        toast("Comentário editado", "ok");
        openSpotDetail(state.selectedSpotId);
      } catch (err) {
        toast(err.message, "err");
      }
    })
  );
  cl.querySelectorAll(".c-del").forEach((b) =>
    b.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm("Excluir este comentário?")) return;
      try {
        await api(`/comments/${b.dataset.id}`, { method: "DELETE" });
        toast("Comentário excluído", "ok");
        openSpotDetail(state.selectedSpotId);
      } catch (err) {
        toast(err.message, "err");
      }
    })
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
  Telemetry.track("like", { liked: !!res.liked, spot: id });
  loadNotifications();
});

$("comment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!state.user) return;
  const text = $("comment-input").value.trim();
  if (!text) return;
  await api(`/spots/${state.selectedSpotId}/comments`, { method: "POST", body: { text } });
  $("comment-input").value = "";
  Telemetry.track("comment", { spot: state.selectedSpotId });
  loadNotifications();
  openSpotDetail(state.selectedSpotId);
});

/* ---------------- Editar spot ---------------- */
function refreshEditRadius(r) { $("se-radius-label").textContent = r + " m"; }
$("se-radius").addEventListener("input", (e) => refreshEditRadius(parseInt(e.target.value, 10)));

$("btn-edit-spot").addEventListener("click", () => {
  const spot = state.spots.find((s) => s.id === state.selectedSpotId);
  if (!spot) return;
  $("se-name").value = spot.name;
  $("se-desc").value = spot.description || "";
  $("se-radius").value = spot.radius_m;
  refreshEditRadius(spot.radius_m);
  hideError("edit-error");
  $("spot-edit").classList.remove("hidden");
});

$("btn-cancel-edit").addEventListener("click", () => {
  $("spot-edit").classList.add("hidden");
});

$("btn-save-edit").addEventListener("click", async () => {
  const id = state.selectedSpotId;
  if (!id) return;
  const btn = $("btn-save-edit");
  hideError("edit-error");
  btn.disabled = true;
  btn.textContent = "Salvando…";
  try {
    await api(`/spots/${id}`, {
      method: "PATCH",
      body: {
        name: $("se-name").value,
        description: $("se-desc").value,
        radius_m: parseInt($("se-radius").value, 10),
      },
    });
    $("spot-edit").classList.add("hidden");
    toast("Lugar atualizado!", "ok");
    openSpotDetail(id);
    refreshSpots();
  } catch (e) {
    showError("edit-error", e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Salvar alterações";
  }
});

$("btn-share").addEventListener("click", async () => {
  const id = state.selectedSpotId;
  if (!id) return;
  const url = location.origin + "/#spot=" + id;
  const spot = state.spots.find((s) => s.id === id);
  const title = spot ? spot.name : "NearGram";
  if (navigator.share) {
    try {
      await navigator.share({ title, text: `Abra "${title}" no NearGram 📍`, url });
      return;
    } catch (e) { /* usuário cancelou ou falhou */ }
  }
  try {
    await navigator.clipboard.writeText(url);
    toast("Link copiado para a área de transferência", "ok");
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
  window._photoDataUrl = null;
  $("n-name").value = "";
  $("n-desc").value = "";
  $("n-radius").value = 500;
  refreshRadius(500);
  $("n-pos").textContent = `Sua posição: ${state.currentPos.lat.toFixed(5)}, ${state.currentPos.lng.toFixed(5)}`;
  showModal("modal-new");
});

function openNewModal() {
  Telemetry.track("open_new");
  if (state.currentPos) { $("btn-new").click(); return; }
  const iv = setInterval(() => { if (state.currentPos) { clearInterval(iv); $("btn-new").click(); } }, 500);
  setTimeout(() => clearInterval(iv), 20000);
}

$("photo-drop").addEventListener("click", () => $("photo-input").click());
$("photo-input").addEventListener("change", (e) => {
  const f = e.target.files[0];
  if (!f) return;
  if (!f.type.startsWith("image/")) return;
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const small = await compressImage(reader.result, 1280, 0.8);
      window._photoDataUrl = small;
      $("photo-preview").src = small;
      $("photo-preview").classList.remove("hidden");
      $("photo-placeholder").style.display = "none";
    } catch (err) {
      showError("publish-error", err.message);
    }
  };
  reader.readAsDataURL(f);
});
$("n-radius").addEventListener("input", (e) => refreshRadius(parseInt(e.target.value, 10)));

$("btn-publish").addEventListener("click", async () => {
  if (!state.user) return;
  hideError("publish-error");
  const photo = window._photoDataUrl;
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
  const btn = $("btn-publish");
  btn.disabled = true;
  btn.textContent = "Publicando…";
  try {
    await api("/spots", { method: "POST", body });
    hideModal("modal-new");
    toast("Lugar publicado! 📍", "ok");
    Telemetry.track("publish_spot", { radius_m: body.radius_m });
    refreshSpots();
  } catch (err) {
    showError("publish-error", err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Publicar 📍";
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
  Telemetry.track("search", { q_len: q.length });
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
        ${s.photo ? `<img class="search-thumb" src="${s.photo}" loading="lazy" decoding="async" alt=""/>` : `<span class="search-thumb lock">🔒</span>`}
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
let _searchTimer = null;
$("search-input").addEventListener("input", () => {
  clearTimeout(_searchTimer);
  _searchTimer = setTimeout(() => {
    if ($("search-input").value.trim()) runSearch();
  }, 400);
});

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
        <div class="notif-head"><span class="notif-actor">@${esc(n.actor)}</span><span class="notif-time">${timeAgo(n.created_at)}</span></div>
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

/* ---------------- Sugestões de pessoas ---------------- */
async function loadSuggestedUsers() {
  const section = $("suggested-users-section");
  const list = $("suggested-users-list");
  if (!section || !list || !state.user) return;
  try {
    const d = await api("/users/suggested");
    if (!d.users || !d.users.length) {
      section.classList.add("hidden");
      return;
    }
    section.classList.remove("hidden");
    list.innerHTML = "";
    d.users.forEach((u) => {
      const card = document.createElement("div");
      card.className = "suggested-card";
      card.innerHTML = `
        ${u.avatar ? `<img class="avatar-md" src="${u.avatar}" alt="" />` : `<span class="avatar-md no-avatar"></span>`}
        <div class="suggested-info">
          <span class="suggested-name">@${esc(u.username)}</span>
          <small class="suggested-meta">${u.spot_count} ${u.spot_count === 1 ? "foto" : "fotos"}</small>
        </div>
        <button class="btn-sm btn-follow-quick" data-id="${u.id}">${u.is_following ? "✓" : "+ Seguir"}</button>
      `;
      card.querySelector(".suggested-info")?.addEventListener("click", () => openUserProfile(u.username));
      card.querySelector(".avatar-md")?.addEventListener("click", () => openUserProfile(u.username));
      card.querySelector(".btn-follow-quick")?.addEventListener("click", async (e) => {
        e.stopPropagation();
        const btn = e.currentTarget;
        try {
          const res = await api(`/users/${u.id}/follow`, { method: "POST", body: {} });
          btn.textContent = res.following ? "✓" : "+ Seguir";
          btn.classList.toggle("following", res.following);
          toast(res.following ? `Agora você segue @${u.username}` : `Deixou de seguir @${u.username}`);
          if (state.feedMode === "following") refreshSpots();
        } catch (err) {
          toast(err.message, "err");
        }
      });
      list.appendChild(card);
    });
  } catch (e) {
    section.classList.add("hidden");
  }
}

$("btn-refresh-suggested")?.addEventListener("click", loadSuggestedUsers);

/* ---------------- Ranking de lugares ---------------- */
async function loadRanking() {
  const list = $("ranking-list");
  const empty = $("ranking-empty");
  const loading = $("ranking-loading");
  list.innerHTML = "";
  empty.classList.add("hidden");
  loading.classList.remove("hidden");
  try {
    const d = await api("/spots/ranked?limit=10");
    loading.classList.add("hidden");
    if (!d.spots || !d.spots.length) {
      empty.classList.remove("hidden");
      return;
    }
    d.spots.forEach((s, i) => {
      const card = document.createElement("button");
      card.className = "rank-card";
      const medal = i === 0 ? "🥇" : i === 1 ? "🥈" : i === 2 ? "🥉" : `${i + 1}º`;
      card.innerHTML = `
        <span class="rank-medal">${medal}</span>
        <span class="rank-name">${esc(s.name)}</span>
        <span class="rank-author">@${esc(s.author)}</span>
        <span class="rank-likes">❤ ${s.like_count}</span>
      `;
      card.addEventListener("click", () => {
        hideModal("modal-ranking");
        openSpotDetail(s.id);
      });
      list.appendChild(card);
    });
  } catch (e) {
    loading.classList.add("hidden");
    empty.textContent = "Não foi possível carregar o ranking.";
    empty.classList.remove("hidden");
  }
}

$("btn-ranking").addEventListener("click", () => {
  showModal("modal-ranking");
  loadRanking();
});

/* ---------------- Public user profile & follow ---------------- */
async function openUserProfile(username) {
  try {
    let qs = "";
    if (state.currentPos) qs = `?lat=${state.currentPos.lat}&lng=${state.currentPos.lng}`;
    const d = await api(`/users/${encodeURIComponent(username)}` + qs);
    const isSelf = state.user && d.username === state.user.username;
    $("user-title").textContent = "@" + d.username;
    setAvatar("user-avatar", d.avatar);
    $("user-bio").textContent = d.bio || "Sem biografia.";
    const btn = $("btn-follow");
    if (!state.user || isSelf) {
      btn.classList.add("hidden");
    } else {
      btn.classList.remove("hidden");
      btn.textContent = d.is_following ? "✓ Seguindo" : "Seguir";
    }
    $("user-follow-hint").textContent = d.follows_me ? "Este perfil segue você" : "";
    $("user-stats").innerHTML = `
      <button class="stat" data-list="followers"><b>${d.stats.followers}</b><span>seguidores</span></button>
      <button class="stat" data-list="following"><b>${d.stats.following}</b><span>seguindo</span></button>
      <button class="stat" data-list="spots"><b>${d.stats.spots}</b><span>fotos</span></button>`;
    $("user-lists").classList.add("hidden");
    $("user-lists").innerHTML = "";
    $("user-stats").querySelectorAll("[data-list]").forEach((btn) =>
      btn.addEventListener("click", () => toggleUserList(btn.dataset.list, d))
    );
    $("user-self-actions").classList.toggle("hidden", !isSelf);
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
    toast(res.following ? `Agora você segue @${u.username}` : `Você deixou de seguir @${u.username}`);
    Telemetry.track("follow", { following: !!res.following });
    const statEls = $("user-stats").querySelectorAll(".stat");
    if (statEls[0]) statEls[0].querySelector("b").textContent = res.followers;
    loadNotifications();
    if (state.feedMode === "following") refreshSpots();
  } catch (e) {
    toast(e.message, "err");
  }
});

function toggleUserList(which, d) {
  const box = $("user-lists");
  if (box.dataset.open === which) {
    box.dataset.open = "";
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.dataset.open = which;
  box.innerHTML = "";
  const items = which === "followers" ? d.followers_list : d.following_list;
  if (!items || !items.length) {
    box.innerHTML = `<p class="hint">Nenhum ${which === "followers" ? "seguidor" : "seguindo"} ainda.</p>`;
    box.classList.remove("hidden");
    return;
  }
  items.forEach((u) => {
    const row = document.createElement("button");
    row.className = "user-list-row";
    row.innerHTML = `${u.avatar ? `<img class="avatar-sm" src="${u.avatar}" alt=""/>` : `<span class="avatar-sm no-avatar"></span>`} <span>@${esc(u.username)}</span>`;
    row.addEventListener("click", () => { hideModal("modal-user"); openUserProfile(u.username); });
    box.appendChild(row);
  });
  box.classList.remove("hidden");
}

$("btn-manage-profile").addEventListener("click", () => {
  hideModal("modal-user");
  openOwnProfile();
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
  const params = new URLSearchParams(location.search);
  const action = params.get("action");
  if (action === "new") { openNewModal(); return; }
  if (action === "search") { showModal("modal-search"); return; }
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

/* ---------------- Lightbox ---------------- */
function openLightbox(src) {
  $("lightbox-img").src = src;
  $("lightbox").classList.remove("hidden");
}
$("lightbox").addEventListener("click", () => $("lightbox").classList.add("hidden"));
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") $("lightbox").classList.add("hidden");
});

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

function timeAgo(s) {
  if (!s) return "";
  const d = new Date(s + "Z");
  if (isNaN(d)) return s;
  const sec = Math.max(0, Math.floor((Date.now() - d.getTime()) / 1000));
  if (sec < 60) return "agora";
  const min = Math.floor(sec / 60);
  if (min < 60) return `${min} min`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} h`;
  const day = Math.floor(hr / 24);
  if (day < 7) return `${day} d`;
  return fmtDate(s);
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
    let refreshing = false;
    navigator.serviceWorker.addEventListener("controllerchange", () => {
      if (refreshing) return;
      refreshing = true;
      location.reload();
    });
    navigator.serviceWorker.register("/sw.js").then((reg) => {
      reg.addEventListener("updatefound", () => {
        const nw = reg.installing;
        if (!nw) return;
        nw.addEventListener("statechange", () => {
          if (nw.state === "installed" && navigator.serviceWorker.controller) {
            toastAction("Nova versão disponível 🚀", "Atualizar", () => nw.postMessage({ type: "SKIP_WAITING" }));
          }
        });
      });
    }).catch(() => {});
  });
}