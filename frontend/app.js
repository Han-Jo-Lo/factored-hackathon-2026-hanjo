const SESSIONS = [
  { id: "analyst_demo", role: "marketing_analyst" },
  { id: "analyst_pt", role: "marketing_analyst" },
  { id: "viewer_demo", role: "marketing_viewer" },
];

const I18N = {
  es: {
    title: "Copiloto marketing",
    tagline: "Analista interno · campañas",
    session: "Sesión",
    role: "Rol",
    connected: "Conectado",
    reconnecting: "Reconectando…",
    disconnected: "Desconectado",
    unauthorized: "Sesión no autorizada",
    send: "Enviar",
    approve: "Aprobar",
    reject: "Rechazar",
    hitlKicker: "Revisión humana",
    hitlFallback:
      "Consulta con cobertura por debajo del umbral. El ROI puede estar sesgado.",
    hitlLost:
      "Si había una aprobación pendiente, vuelve a lanzar la consulta o espera un nuevo aviso HITL.",
    placeholder: "Escribe un mensaje…",
    you: "Tú",
    agent: "Agente",
    thinking: "Consultando…",
    resuming: "Reanudando…",
    toolConsultar: "Consultando desempeño de campañas…",
    toolFallback: "Usando herramienta…",
  },
  pt: {
    title: "Copiloto de marketing",
    tagline: "Analista interno · campanhas",
    session: "Sessão",
    role: "Função",
    connected: "Conectado",
    reconnecting: "Reconectando…",
    disconnected: "Desconectado",
    unauthorized: "Sessão não autorizada",
    send: "Enviar",
    approve: "Aprovar",
    reject: "Rejeitar",
    hitlKicker: "Revisão humana",
    hitlFallback:
      "Consulta com cobertura abaixo do limiar. O ROI pode estar enviesado.",
    hitlLost:
      "Se havia uma aprovação pendente, envie de novo a consulta ou aguarde um novo aviso HITL.",
    placeholder: "Escreva uma mensagem…",
    you: "Você",
    agent: "Agente",
    thinking: "Consultando…",
    resuming: "Retomando…",
    toolConsultar: "Consultando desempenho das campanhas…",
    toolFallback: "Usando ferramenta…",
  },
};

const PING_MS = 25000;
const PONG_TIMEOUT_MS = 10000;
const BACKOFF = [1000, 2000, 4000, 8000, 15000];

const state = {
  lang: localStorage.getItem("ui_lang") || "es",
  sessionId: localStorage.getItem("ui_session") || "analyst_demo",
  ws: null,
  intentionalClose: false,
  unauthorized: false,
  connected: false,
  reconnectTimer: null,
  pingTimer: null,
  pongTimer: null,
  backoffIndex: 0,
  hitlOpen: false,
  progress: null,
};

const el = {
  title: document.getElementById("title"),
  tagline: document.getElementById("tagline"),
  sessionHeading: document.getElementById("session-heading"),
  sessionList: document.getElementById("session-list"),
  roleLabel: document.getElementById("role-label"),
  roleValue: document.getElementById("role-value"),
  statusDot: document.getElementById("status-dot"),
  statusLabel: document.getElementById("status-label"),
  transcript: document.getElementById("transcript"),
  hitl: document.getElementById("hitl"),
  hitlKicker: document.getElementById("hitl-kicker"),
  hitlDesc: document.getElementById("hitl-desc"),
  btnApprove: document.getElementById("btn-approve"),
  btnReject: document.getElementById("btn-reject"),
  btnSend: document.getElementById("btn-send"),
  input: document.getElementById("input"),
  composer: document.getElementById("composer"),
  langEs: document.getElementById("lang-es"),
  langPt: document.getElementById("lang-pt"),
};

function t(key) {
  return I18N[state.lang][key];
}

function currentSession() {
  return SESSIONS.find((s) => s.id === state.sessionId) || SESSIONS[0];
}

function applyI18n() {
  document.documentElement.lang = state.lang;
  el.title.textContent = t("title");
  el.tagline.textContent = t("tagline");
  el.sessionHeading.textContent = t("session");
  el.roleLabel.textContent = t("role");
  el.hitlKicker.textContent = t("hitlKicker");
  el.btnApprove.textContent = t("approve");
  el.btnReject.textContent = t("reject");
  el.btnSend.textContent = t("send");
  el.input.placeholder = t("placeholder");
  el.langEs.classList.toggle("is-on", state.lang === "es");
  el.langPt.classList.toggle("is-on", state.lang === "pt");
  renderSessions();
  refreshStatusLabel();
  refreshProgressLabel();
}

function renderSessions() {
  el.sessionList.innerHTML = "";
  for (const sess of SESSIONS) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "session-btn" + (sess.id === state.sessionId ? " is-on" : "");
    btn.innerHTML = `${escapeHtml(sess.id)}<small>${escapeHtml(sess.role)}</small>`;
    btn.addEventListener("click", () => switchSession(sess.id));
    el.sessionList.appendChild(btn);
  }
  el.roleValue.textContent = currentSession().role;
}

function setStatus(kind) {
  el.statusDot.className = "status-dot " + (kind === "ok" ? "ok" : kind === "wait" ? "wait" : "err");
  state.connected = kind === "ok";
  refreshStatusLabel();
  syncControls();
}

function refreshStatusLabel() {
  if (state.unauthorized) {
    el.statusLabel.textContent = t("unauthorized");
    return;
  }
  if (state.connected) el.statusLabel.textContent = t("connected");
  else if (state.reconnectTimer) el.statusLabel.textContent = t("reconnecting");
  else el.statusLabel.textContent = t("disconnected");
}

function syncControls() {
  const live = state.connected;
  el.btnSend.disabled = !live;
  el.input.disabled = !live;
  el.btnApprove.disabled = !live || !state.hitlOpen;
  el.btnReject.disabled = !live || !state.hitlOpen;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;");
}

function progressText(payload) {
  const key = payload?.paso_key;
  if (key === "resuming") return t("resuming");
  if (key === "tool") {
    if (payload.tool === "consultar_desempeno_campanas") return t("toolConsultar");
    return t("toolFallback");
  }
  return t("thinking");
}

function hideProgress() {
  const node = el.transcript.querySelector(".bubble.progress");
  if (node) node.remove();
  state.progress = null;
}

function showProgress(payload) {
  state.progress = payload || { paso_key: "thinking" };
  let node = el.transcript.querySelector(".bubble.progress");
  if (!node) {
    node = document.createElement("div");
    node.className = "bubble progress";
    el.transcript.appendChild(node);
  }
  node.textContent = progressText(state.progress);
  el.transcript.scrollTop = el.transcript.scrollHeight;
}

function refreshProgressLabel() {
  const node = el.transcript.querySelector(".bubble.progress");
  if (node && state.progress) node.textContent = progressText(state.progress);
}

function addBubble(kind, text) {
  const clean = String(text ?? "").trim();
  if (!clean) return;
  const last = el.transcript.lastElementChild;
  if (last && last.className === "bubble " + kind && last.textContent === clean) {
    return;
  }
  const div = document.createElement("div");
  div.className = "bubble " + kind;
  div.textContent = clean;
  el.transcript.appendChild(div);
  el.transcript.scrollTop = el.transcript.scrollHeight;
}

function textFromContent(value) {
  if (value == null) return "";
  if (typeof value === "string") return value.trim();
  if (Array.isArray(value)) {
    return value.map(textFromContent).filter(Boolean).join("\n");
  }
  if (typeof value === "object") {
    if (typeof value.text === "string") return value.text.trim();
    if (value.content != null) return textFromContent(value.content);
  }
  return String(value).trim();
}

function hideHitl() {
  state.hitlOpen = false;
  el.hitl.hidden = true;
  syncControls();
}

function showHitl(payload) {
  const desc =
    payload?.interrupt?.action_requests?.[0]?.description || t("hitlFallback");
  el.hitlDesc.textContent = desc;
  el.hitl.hidden = false;
  state.hitlOpen = true;
  syncControls();
}

function wsUrl(sessionId) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}/ws/${sessionId}`;
}

function clearTimers() {
  if (state.pingTimer) clearInterval(state.pingTimer);
  if (state.pongTimer) clearTimeout(state.pongTimer);
  if (state.reconnectTimer) clearTimeout(state.reconnectTimer);
  state.pingTimer = null;
  state.pongTimer = null;
  state.reconnectTimer = null;
}

function armPongWatch() {
  if (state.pongTimer) clearTimeout(state.pongTimer);
  state.pongTimer = setTimeout(() => {
    if (state.ws) state.ws.close();
  }, PONG_TIMEOUT_MS);
}

function startPing() {
  if (state.pingTimer) clearInterval(state.pingTimer);
  state.pingTimer = setInterval(() => {
    if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    state.ws.send("__ping__");
    armPongWatch();
  }, PING_MS);
}

function scheduleReconnect() {
  if (state.intentionalClose || state.unauthorized) return;
  const wait = BACKOFF[Math.min(state.backoffIndex, BACKOFF.length - 1)];
  state.backoffIndex += 1;
  setStatus("wait");
  state.reconnectTimer = setTimeout(connect, wait);
}

function connect() {
  clearTimers();
  if (state.ws && state.ws.readyState < 2) {
    state.intentionalClose = true;
    state.ws.close();
  }
  state.intentionalClose = false;
  const ws = new WebSocket(wsUrl(state.sessionId));
  state.ws = ws;
  setStatus("wait");

  ws.addEventListener("open", () => {
    state.backoffIndex = 0;
    state.unauthorized = false;
    setStatus("ok");
    startPing();
    ws.send("__ping__");
    armPongWatch();
  });

  ws.addEventListener("message", (ev) => {
    const raw = ev.data;
    if (raw === "__pong__") {
      if (state.pongTimer) clearTimeout(state.pongTimer);
      return;
    }
    let payload = raw;
    try {
      payload = JSON.parse(raw);
    } catch {
      hideProgress();
      addBubble("agent", String(raw));
      return;
    }
    if (payload.tipo === "progreso") {
      showProgress(payload);
      return;
    }
    if (payload.status === "awaiting_approval") {
      hideProgress();
      showHitl(payload);
      return;
    }
    hideProgress();
    hideHitl();
    const text = textFromContent(payload.response_text);
    addBubble(payload.status === "error" ? "sys" : "agent", text || JSON.stringify(payload));
  });

  ws.addEventListener("close", (ev) => {
    if (state.ws !== ws) return;
    clearTimers();
    state.ws = null;
    state.connected = false;
    if (ev.code === 4401) {
      state.unauthorized = true;
      setStatus("err");
      hideProgress();
      addBubble("sys", t("unauthorized"));
      return;
    }
    if (state.intentionalClose) {
      setStatus("err");
      return;
    }
    if (state.hitlOpen) {
      hideHitl();
      hideProgress();
      addBubble("sys", t("hitlLost"));
    }
    scheduleReconnect();
  });

  ws.addEventListener("error", () => {
    /* close handler reconecta */
  });
}

function disconnectIntentional() {
  state.intentionalClose = true;
  clearTimers();
  if (state.ws) {
    state.ws.close();
    state.ws = null;
  }
}

function switchSession(id) {
  if (id === state.sessionId && state.ws) return;
  state.sessionId = id;
  localStorage.setItem("ui_session", id);
  hideHitl();
  hideProgress();
  el.transcript.replaceChildren();
  renderSessions();
  disconnectIntentional();
  connect();
}

function sendText(text) {
  if (!state.ws || state.ws.readyState !== WebSocket.OPEN) return;
  state.ws.send(text);
}

el.composer.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = el.input.value.trim();
  if (!text || !state.connected) return;
  addBubble("user", text);
  showProgress({ paso_key: "thinking" });
  sendText(text);
  el.input.value = "";
});

el.input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    el.composer.requestSubmit();
  }
});

el.btnApprove.addEventListener("click", () => {
  sendText(JSON.stringify({ type: "hitl_decision", decision: "approve" }));
  hideHitl();
  showProgress({ paso_key: "resuming" });
});

el.btnReject.addEventListener("click", () => {
  sendText(JSON.stringify({ type: "hitl_decision", decision: "reject" }));
  hideHitl();
  showProgress({ paso_key: "resuming" });
});

el.langEs.addEventListener("click", () => {
  state.lang = "es";
  localStorage.setItem("ui_lang", "es");
  applyI18n();
});

el.langPt.addEventListener("click", () => {
  state.lang = "pt";
  localStorage.setItem("ui_lang", "pt");
  applyI18n();
});

applyI18n();
connect();
