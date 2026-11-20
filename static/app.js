"use strict";

// ------------------------------------------------------------------ köməkçilər
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const LABELS = {
  status: { todo: "Gözləyir", in_progress: "Davam edir", done: "Tamamlanıb" },
  priority: { low: "Aşağı", medium: "Orta", high: "Yüksək" },
};
const PRIORITY_COLORS = { high: "#dc2626", medium: "#d97706", low: "#0d9488" };

// XSS-dən qorunmaq üçün bütün istifadəçi mətni escape olunur
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

function todayStr() {
  const d = new Date();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${m}-${day}`;
}

function fmtDate(iso) {
  if (!iso) return "";
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add("hidden"), 2500);
}

async function api(path, { method = "GET", body } = {}) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
    credentials: "same-origin",
  });
  let data = null;
  try { data = await res.json(); } catch (_) { /* boş cavab */ }
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/api/login") && !path.startsWith("/api/me")) {
      showAuth();
    }
    throw new Error((data && data.error) || "Xəta baş verdi.");
  }
  return data;
}

// ------------------------------------------------------------------ görünüşlər
function showAuth() {
  $("#app-view").classList.add("hidden");
  $("#auth-view").classList.remove("hidden");
}

function showApp(user) {
  $("#auth-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#username-label").textContent = "👤 " + user.username;
  switchView("dashboard");
}

function switchView(name) {
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $("#dashboard-view").classList.toggle("hidden", name !== "dashboard");
  $("#tasks-view").classList.toggle("hidden", name !== "tasks");
  if (name === "dashboard") loadStats();
  else loadTasks();
}

// ------------------------------------------------------------------ autentifikasiya
$$("[data-auth-tab]").forEach((btn) => btn.addEventListener("click", () => {
  const which = btn.dataset.authTab;
  $$("[data-auth-tab]").forEach((b) => b.classList.toggle("active", b === btn));
  $("#login-form").classList.toggle("hidden", which !== "login");
  $("#register-form").classList.toggle("hidden", which !== "register");
  $("#auth-error").classList.add("hidden");
}));

function authError(msg) {
  const el = $("#auth-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}

$("#login-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  try {
    const user = await api("/api/login", {
      method: "POST",
      body: { username: f.get("username"), password: f.get("password") },
    });
    e.target.reset();
    showApp(user);
  } catch (err) { authError(err.message); }
});

$("#register-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(e.target);
  if (f.get("password") !== f.get("password2")) return authError("Parollar uyğun gəlmir.");
  try {
    const user = await api("/api/register", {
      method: "POST",
      body: { username: f.get("username"), password: f.get("password") },
    });
    e.target.reset();
    showApp(user);
  } catch (err) { authError(err.message); }
});

$("#logout-btn").addEventListener("click", async () => {
  await api("/api/logout", { method: "POST" }).catch(() => {});
  showAuth();
});

// ------------------------------------------------------------------ naviqasiya
$$(".nav-btn").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.view)));

// ------------------------------------------------------------------ dashboard
async function loadStats() {
  try {
    const s = await api("/api/stats");
    $("#st-total").textContent = s.total;
    $("#st-todo").textContent = s.by_status.todo;
    $("#st-prog").textContent = s.by_status.in_progress;
    $("#st-done").textContent = s.by_status.done;
    $("#st-over").textContent = s.overdue;
    $("#st-today").textContent = s.due_today;
    $("#st-rate").textContent = s.completion_rate;
    $("#progress-bar").style.width = s.completion_rate + "%";

    const max = Math.max(1, ...Object.values(s.by_priority));
    $("#priority-bars").innerHTML = ["high", "medium", "low"].map((p) => `
      <div class="bar-row">
        <span>${LABELS.priority[p]}</span>
        <div class="bar-track"><div class="bar-fill" style="width:${(s.by_priority[p] / max) * 100}%;background:${PRIORITY_COLORS[p]}"></div></div>
        <strong>${s.by_priority[p]}</strong>
      </div>`).join("");

    $("#upcoming-list").innerHTML = s.upcoming.length
      ? s.upcoming.map((t) => `
          <li>
            <span>${esc(t.title)} <span class="badge ${t.priority}">${LABELS.priority[t.priority]}</span></span>
            <span class="muted">${fmtDate(t.due_date)}</span>
          </li>`).join("")
      : '<li class="muted">Yaxınlaşan son tarix yoxdur.</li>';
  } catch (err) { toast(err.message); }
}

// ------------------------------------------------------------------ tapşırıq siyahısı
let searchTimer;
["#f-status", "#f-priority", "#f-sort"].forEach((id) => $(id).addEventListener("change", loadTasks));
$("#f-search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(loadTasks, 250);
});

async function loadTasks() {
  const p = new URLSearchParams();
  if ($("#f-search").value.trim()) p.set("q", $("#f-search").value.trim());
  if ($("#f-status").value) p.set("status", $("#f-status").value);
  if ($("#f-priority").value) p.set("priority", $("#f-priority").value);
  p.set("sort", $("#f-sort").value);
  try {
    const tasks = await api("/api/tasks?" + p.toString());
    renderTasks(tasks);
  } catch (err) { toast(err.message); }
}

function renderTasks(tasks) {
  const list = $("#task-list");
  $("#empty-msg").classList.toggle("hidden", tasks.length > 0);
  const today = todayStr();
  list.innerHTML = tasks.map((t) => {
    const overdue = t.due_date && t.status !== "done" && t.due_date < today;
    return `
    <article class="task ${t.status}" data-id="${esc(t.id)}">
      <input type="checkbox" class="task-check" ${t.status === "done" ? "checked" : ""} title="Tamamlandı kimi işarələ">
      <div class="task-body">
        <div class="task-title">${esc(t.title)}</div>
        ${t.description ? `<div class="task-desc">${esc(t.description)}</div>` : ""}
        <div class="meta">
          <span class="badge ${t.status}">${LABELS.status[t.status]}</span>
          <span class="badge ${t.priority}">${LABELS.priority[t.priority]}</span>
          ${t.due_date ? `<span class="badge ${overdue ? "overdue" : ""}">📅 ${fmtDate(t.due_date)}${overdue ? " (gecikib)" : ""}</span>` : ""}
        </div>
      </div>
      <div class="task-actions">
        <select class="status-select" aria-label="Status">
          ${Object.entries(LABELS.status).map(([k, v]) => `<option value="${k}" ${k === t.status ? "selected" : ""}>${v}</option>`).join("")}
        </select>
        <button class="btn ghost small" data-edit>✏️</button>
        <button class="btn danger small" data-delete>🗑</button>
      </div>
    </article>`;
  }).join("");

  // hadisələr
  $$(".task", list).forEach((el, i) => {
    const t = tasks[i];
    $(".task-check", el).addEventListener("change", (e) =>
      setStatus(t.id, e.target.checked ? "done" : "todo"));
    $(".status-select", el).addEventListener("change", (e) => setStatus(t.id, e.target.value));
    $("[data-edit]", el).addEventListener("click", () => openModal(t));
    $("[data-delete]", el).addEventListener("click", () => removeTask(t));
  });
}

async function setStatus(id, status) {
  try {
    await api(`/api/tasks/${id}/status`, { method: "PATCH", body: { status } });
    toast("Status yeniləndi");
  } catch (err) { toast(err.message); }
  loadTasks();
}

async function removeTask(t) {
  if (!confirm(`"${t.title}" tapşırığı silinsin?`)) return;
  try {
    await api(`/api/tasks/${t.id}`, { method: "DELETE" });
    toast("Tapşırıq silindi");
  } catch (err) { toast(err.message); }
  loadTasks();
}

// ------------------------------------------------------------------ modal
const modal = $("#modal");
const taskForm = $("#task-form");

function openModal(task = null) {
  taskForm.reset();
  $("#modal-error").classList.add("hidden");
  $("#modal-title").textContent = task ? "Tapşırığı redaktə et" : "Yeni tapşırıq";
  taskForm.id.value = task ? task.id : "";
  if (task) {
    taskForm.title.value = task.title;
    taskForm.description.value = task.description || "";
    taskForm.status.value = task.status;
    taskForm.priority.value = task.priority;
    taskForm.due_date.value = task.due_date || "";
  }
  modal.classList.remove("hidden");
  taskForm.title.focus();
}

function closeModal() { modal.classList.add("hidden"); }

$$("[data-new-task]").forEach((b) => b.addEventListener("click", () => openModal()));
$("#modal-cancel").addEventListener("click", closeModal);
modal.addEventListener("click", (e) => { if (e.target === modal) closeModal(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

taskForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const f = new FormData(taskForm);
  const id = f.get("id");
  const body = {
    title: f.get("title"),
    description: f.get("description"),
    status: f.get("status"),
    priority: f.get("priority"),
    due_date: f.get("due_date"),
  };
  try {
    await api(id ? `/api/tasks/${id}` : "/api/tasks", { method: id ? "PUT" : "POST", body });
    closeModal();
    toast(id ? "Tapşırıq yeniləndi" : "Tapşırıq əlavə olundu");
    // aktiv görünüşü yenilə
    if (!$("#tasks-view").classList.contains("hidden")) loadTasks(); else loadStats();
  } catch (err) {
    const el = $("#modal-error");
    el.textContent = err.message;
    el.classList.remove("hidden");
  }
});

// ------------------------------------------------------------------ başlanğıc
(async function init() {
  try {
    const user = await api("/api/me");
    showApp(user);
  } catch (_) {
    showAuth();
  }
})();
