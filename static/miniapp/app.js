const tg = window.Telegram?.WebApp;
if (tg) { tg.ready(); tg.expand(); }
const initData = tg?.initData || "";

async function api(path) {
  const res = await fetch(path, {
    headers: initData ? { "X-Telegram-Init-Data": initData } : {},
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

function toast(text) {
  let el = document.querySelector(".toast");
  if (!el) {
    el = document.createElement("div");
    el.className = "toast";
    document.body.appendChild(el);
  }
  el.textContent = text;
  el.classList.add("show");
  setTimeout(() => el.classList.remove("show"), 1800);
}

const app = document.getElementById("app");
let activeCategoryId = null;
let docsById = {};
function cacheDocs(docs) { docs.forEach(d => { docsById[d.id] = d; }); }

function escapeHtml(s) {
  if (!s) return "";
  return String(s).replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}
function initials(name) {
  return name.trim().split(/\s+/).slice(0, 2).map(w => w[0]?.toUpperCase() || "").join("");
}
function formatDate(iso) {
  if (!iso) return null;
  const [y, m, d] = iso.split("-");
  return `${d}.${m}.${y}`;
}
function validityText(d) {
  if (!d.valid_from && !d.valid_until) return "бессрочно";
  if (d.valid_until) return `до ${formatDate(d.valid_until)}`;
  return `с ${formatDate(d.valid_from)}`;
}
function isExpiringSoon(validUntil) {
  if (!validUntil) return null;
  const days = Math.ceil((new Date(validUntil) - new Date()) / 86400000);
  if (days < 0) return "истёк";
  if (days <= 60) return `${days} дн.`;
  return null;
}
function debounce(fn, ms) {
  let t;
  return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); };
}

function field(label, value) {
  if (!value) return "";
  return `<div><div class="doc-field-label">${label}</div><div class="doc-field-value">${escapeHtml(value)}</div></div>`;
}

function renderDocCard(d) {
  const expiring = isExpiringSoon(d.valid_until);
  return `
  <div class="doc-card">
    <div class="doc-tags">
      <span class="tag">${escapeHtml(d.category)}</span>
      ${d.is_primary ? `<span class="tag primary">★ Основной</span>` : ""}
      ${expiring ? `<span class="tag warn">${expiring}</span>` : ""}
    </div>
    <div class="doc-title">${escapeHtml(d.title)}</div>
    <div class="doc-fields">
      ${field("Серия", d.series)}
      ${field("Номер", d.number)}
      ${field("Дата выдачи", formatDate(d.issue_date))}
    </div>
    <div class="doc-details" id="details-${d.id}">
      <div class="doc-detail-row"><span>Кем выдан</span><span>${escapeHtml(d.issued_by || "—")}</span></div>
      <div class="doc-detail-row"><span>Действует</span><span>${validityText(d)}</span></div>
      <div class="doc-detail-row"><span>Субъект</span><span>${escapeHtml(d.subject_name)}</span></div>
    </div>
    <button class="toggle-btn" data-toggle="${d.id}">Раскрыть подробнее ⌄</button>
    <div class="doc-actions">
      <button data-download="${d.id}" disabled title="Появится после подключения Google Drive">⬇ Скачать</button>
      <button data-copy="${d.id}">⧉ Скопировать</button>
    </div>
  </div>`;
}

function attachDocCardEvents(container) {
  container.querySelectorAll("[data-toggle]").forEach(btn => {
    btn.addEventListener("click", () => {
      const id = btn.dataset.toggle;
      const details = document.getElementById(`details-${id}`);
      const open = details.classList.toggle("open");
      btn.textContent = open ? "Свернуть ︿" : "Раскрыть подробнее ⌄";
    });
  });
  container.querySelectorAll("[data-copy]").forEach(btn => {
    btn.addEventListener("click", () => copyDoc(btn.dataset.copy));
  });
}

function copyDoc(id) {
  const d = docsById[id];
  if (!d) return;
  const text = [
    `${d.title} (${d.category})`,
    [d.series && `Серия: ${d.series}`, d.number && `Номер: ${d.number}`].filter(Boolean).join(", "),
    d.issue_date && `Выдан: ${formatDate(d.issue_date)}${d.issued_by ? ", " + d.issued_by : ""}`,
  ].filter(Boolean).join("\n");
  navigator.clipboard.writeText(text).then(() => {
    toast("Скопировано");
    tg?.HapticFeedback?.notificationOccurred("success");
  });
}

function renderDocResults(docs, primaryFiltered) {
  cacheDocs(docs);
  const results = document.getElementById("results");
  if (!docs.length) { results.innerHTML = `<div class="empty">Ничего не нашлось</div>`; return; }
  results.innerHTML = docs.map(renderDocCard).join("");
  if (primaryFiltered) {
    results.innerHTML += `<button class="toggle-btn" id="show-all">Показать все</button>`;
    document.getElementById("show-all").addEventListener("click", async () => {
      renderDocResults(await api(`/api/search?category_id=${activeCategoryId}`), false);
    });
  }
  attachDocCardEvents(results);
}

function renderSubjectList(subjects) {
  const results = document.getElementById("results");
  if (!subjects.length) { results.innerHTML = `<div class="empty">Пока пусто</div>`; return; }
  results.innerHTML = `<div class="subject-list">` + subjects.map(s => `
    <div class="subject-row" data-id="${s.id}">
      <div class="subject-avatar">${initials(s.name)}</div>
      <div class="subject-name">${escapeHtml(s.name)}</div>
      <div class="subject-count">${s.doc_count}</div>
      <div class="chevron">›</div>
    </div>`).join("") + `</div>`;
  results.querySelectorAll(".subject-row").forEach(row => {
    row.addEventListener("click", () => { location.hash = `#/subject/${row.dataset.id}`; });
  });
}

async function toggleCategory(id) {
  activeCategoryId = activeCategoryId === id ? null : id;
  document.querySelectorAll(".chip").forEach(c =>
    c.classList.toggle("active", Number(c.dataset.id) === activeCategoryId));
  if (activeCategoryId) {
    renderDocResults(await api(`/api/search?category_id=${activeCategoryId}&primary_only=true`), true);
  } else {
    renderSubjectList(await api("/api/subjects"));
  }
}

async function onSearch(e) {
  const q = e.target.value.trim();
  if (!q) { renderSubjectList(await api("/api/subjects")); return; }
  renderDocResults(await api(`/api/search?q=${encodeURIComponent(q)}`), false);
}

async function renderHome() {
  activeCategoryId = null;
  app.innerHTML = `
    <div class="header"><h1>Документы</h1></div>
    <div class="search"><input id="search-input" placeholder="Поиск по документам..."></div>
    <div class="chips" id="chips"></div>
    <div id="results"></div>`;

  const [subjects, categories] = await Promise.all([api("/api/subjects"), api("/api/categories")]);
  document.getElementById("chips").innerHTML = categories.map(c =>
    `<span class="chip" data-id="${c.id}">${escapeHtml(c.name)}</span>`).join("");
  document.querySelectorAll(".chip").forEach(chip =>
    chip.addEventListener("click", () => toggleCategory(Number(chip.dataset.id))));
  document.getElementById("search-input").addEventListener("input", debounce(onSearch, 300));

  renderSubjectList(subjects);
}

async function renderSubject(id) {
  app.innerHTML = `<div class="back-row" id="back">‹ Субъекты</div><div id="subject-body"></div>`;
  document.getElementById("back").addEventListener("click", () => { location.hash = "#/"; });

  const data = await api(`/api/subjects/${id}`);
  const body = document.getElementById("subject-body");
  let html = `<div class="header"><h1>${escapeHtml(data.name)}</h1></div>`;

  data.folders.forEach(f => {
    cacheDocs(f.documents);
    html += `<div class="folder-block"><div class="folder-title">📁 ${escapeHtml(f.name)}</div>` +
      (f.documents.length ? f.documents.map(renderDocCard).join("") : `<div class="empty">Пусто</div>`) +
      `</div>`;
  });

  if (data.documents_no_folder.length) {
    cacheDocs(data.documents_no_folder);
    html += `<div class="folder-block"><div class="folder-title">Без папки</div>` +
      data.documents_no_folder.map(renderDocCard).join("") + `</div>`;
  }

  if (!data.folders.length && !data.documents_no_folder.length) {
    html += `<div class="empty">У этого субъекта пока нет документов</div>`;
  }

  body.innerHTML = html;
  attachDocCardEvents(body);
}

function route() {
  const m = location.hash.match(/^#\/subject\/(\d+)/);
  if (m) renderSubject(Number(m[1])); else renderHome();
}
window.addEventListener("hashchange", route);
route();
