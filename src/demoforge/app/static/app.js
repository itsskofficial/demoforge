/* demoforge — the window.
 *
 * One file, no build step, no framework. Every screen is a function that
 * returns DOM, the router calls one of them on each hash change, and the
 * catalog the server sends decides what the forms contain. That is deliberate:
 * a mode is added in catalog.py, not here.
 */

"use strict";

const S = {
  state: null,        // /api/state
  projects: [],       // /api/projects
  jobs: {},           // id -> job
  dockJob: null,      // the job the dock is showing
  detail: null,       // the project on screen
  ws: null,
  timer: null,
};

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

// ---------------------------------------------------------------------------
// small things
// ---------------------------------------------------------------------------

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const [k, v] of Object.entries(attrs)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "value") el.value = v;
      else if (k === "checked") el.checked = !!v;
      else if (k === "disabled") el.disabled = !!v;
      else el.setAttribute(k, v === true ? "" : v);
    }
  }
  for (const c of children.flat(Infinity)) {
    if (c === null || c === undefined || c === false) continue;
    el.append(c.nodeType ? c : document.createTextNode(String(c)));
  }
  return el;
}

async function api(path, method = "GET", body) {
  const res = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = { detail: text }; }
  if (!res.ok) throw new Error((data && data.detail) || `${res.status} ${res.statusText}`);
  return data;
}

function toast(message, kind = "") {
  const el = h("div", { class: `toast ${kind}` }, message);
  $("#toasts").append(el);
  setTimeout(() => el.remove(), kind === "bad" ? 7000 : 3500);
}

const fmtTime = (s) => {
  s = Math.max(0, Math.round(s));
  const m = Math.floor(s / 60), r = s % 60;
  return m ? `${m}:${String(r).padStart(2, "0")}` : `${r}s`;
};
const fmtSize = (b) => b > 1e9 ? (b / 1e9).toFixed(2) + " GB" : b > 1e6 ? (b / 1e6).toFixed(1) + " MB" : Math.round(b / 1e3) + " KB";
const ago = (t) => {
  const d = Date.now() / 1000 - t;
  if (d < 60) return "just now";
  if (d < 3600) return `${Math.floor(d / 60)} min ago`;
  if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
  return `${Math.floor(d / 86400)} d ago`;
};
const modeOf = (key) => S.state.modes[key];
const escapeHtml = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const ACCENT_HEX = {
  lime: "#c8ff2e", cyan: "#38cdd6", coral: "#ff6b5c", gold: "#f0be5a", violet: "#a78bfa",
  white: "#f4f4f4", blue: "#58a6ff", red: "#f86960", green: "#48cf73",
};

const GLYPHS = {
  short: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="7" y="3" width="10" height="18" rx="2"/><path d="M10 8h4M10 12h4M10 16h2"/></svg>',
  reel: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="7" y="3" width="10" height="18" rx="2"/><circle cx="12" cy="10" r="2.5"/><path d="M9 17c1-1.5 5-1.5 6 0"/></svg>',
  edit: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18M8 5v14"/></svg>',
  present: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"/><circle cx="16.5" cy="14.5" r="2.5"/><path d="M6 9h6"/></svg>',
  demo: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 17l4-4-4-4M10 17h10"/></svg>',
};

// ---------------------------------------------------------------------------
// boot + router
// ---------------------------------------------------------------------------

async function boot() {
  S.state = await api("/api/state");
  $("#version").textContent = `v${S.state.version}`;
  await refreshProjects();
  connect();
  checkDoctorBadge();
  window.addEventListener("hashchange", route);
  route();
}

async function refreshProjects() {
  S.projects = await api("/api/projects");
  renderSidebar();
}

function renderSidebar() {
  const nav = $("#projects");
  nav.innerHTML = "";
  const current = (location.hash.match(/^#\/p\/([^/?]+)/) || [])[1];
  const order = ["short", "reel", "edit", "present", "demo"];
  for (const key of order) {
    const items = S.projects.filter((p) => p.mode === key);
    if (!items.length) continue;
    nav.append(h("h4", null, modeOf(key).name));
    for (const p of items) {
      const a = h("a", { href: `#/p/${p.name}`, class: p.name === current ? "active" : "" },
        h("span", { class: `aspect ${p.aspect === "9:16" ? "v" : p.aspect === "1:1" ? "s" : ""}` }),
        h("span", { class: "name", title: p.title }, p.title));
      nav.append(a);
    }
  }
  if (!S.projects.length) nav.append(h("div", { class: "dim", style: "padding:10px" }, "No projects yet."));
}

function route() {
  const hash = location.hash || "#/";
  const [path, query] = hash.slice(1).split("?");
  const q = Object.fromEntries(new URLSearchParams(query || ""));
  const parts = path.split("/").filter(Boolean);
  const main = $("#main");
  main.innerHTML = "";
  $$(".side-foot a").forEach((a) => a.classList.toggle("active", a.dataset.nav === parts[0]));
  renderSidebar();
  let view;
  if (!parts.length) view = viewHome();
  else if (parts[0] === "new" && !parts[1]) view = viewChoose();
  else if (parts[0] === "new") view = viewNew(parts[1]);
  else if (parts[0] === "p") view = viewProject(parts[1], q.tab || "setup");
  else if (parts[0] === "tools" && !parts[1]) view = viewTools();
  else if (parts[0] === "tools") view = viewTool(parts[1]);
  else if (parts[0] === "settings") view = viewSettings();
  else if (parts[0] === "doctor") view = viewDoctor();
  else view = viewHome();
  Promise.resolve(view).then((el) => { main.innerHTML = ""; main.append(el); main.scrollTop = 0; })
    .catch((e) => { main.append(h("div", { class: "empty" }, String(e.message || e))); });
}

// ---------------------------------------------------------------------------
// home
// ---------------------------------------------------------------------------

function viewHome() {
  const wrap = h("div");
  wrap.append(
    h("div", { class: "hero" },
      h("div", null,
        h("div", { class: "eyebrow" }, "Local video creation"),
        h("h1", null, "What are you making?"),
        h("p", { class: "lead" }, "Five ways in, one machine, nothing uploaded. Pick the one that matches what you already have.")),
    ),
    modeGrid(),
  );
  wrap.append(h("div", { class: "section-title" }, h("h2", null, "Or just one thing"),
    h("span", { class: "muted" }, "one feature on one file, no project")));
  wrap.append(h("div", { class: "tool-chips" }, Object.values(S.state.tools).map((t) =>
    h("a", { href: `#/tools/${t.key}` }, t.name))));
  const recent = S.projects.slice(0, 12);
  wrap.append(h("div", { class: "section-title" }, h("h2", null, "Projects"),
    h("span", { class: "muted" }, S.projects.length ? `${S.projects.length} in ${S.state.settings.projects_dir}` : "")));
  if (!recent.length) {
    wrap.append(h("div", { class: "empty" }, "Nothing yet. Start with a Short: it takes one clip and ten minutes."));
  } else {
    wrap.append(h("div", { class: "grid projects" }, recent.map(projectCard)));
  }
  return wrap;
}

function modeGrid() {
  return h("div", { class: "grid modes" }, ["short", "reel", "edit", "present", "demo"].map((key) => {
    const m = modeOf(key);
    return h("div", { class: "mode-card", onclick: () => (location.hash = `#/new/${key}`) },
      h("span", { class: "tag" }, m.aspect),
      h("div", { class: "glyph", html: GLYPHS[key] }),
      h("h3", null, m.name),
      h("p", null, m.tagline),
      h("ul", { class: "needs" }, m.needs.map((n) => h("li", null, n))));
  }));
}

function projectCard(p) {
  const poster = h("div", { class: "poster", style: p.aspect === "9:16" ? "aspect-ratio:16/9" : "" });
  if (p.output && p.output.thumb) poster.append(h("img", { src: p.output.thumb, alt: "" }));
  else if (p.output && p.output.url && /\.(jpg|png)$/i.test(p.output.name)) poster.append(h("img", { src: p.output.url, alt: "" }));
  else poster.append(h("div", { class: "ph" }, p.title));
  poster.append(h("span", { class: `chip ${p.mode}` }, modeOf(p.mode).name));
  const done = p.steps.filter((s) => s.done).length;
  return h("div", { class: "proj-card", onclick: () => (location.hash = `#/p/${p.name}`) },
    poster,
    h("div", { class: "body" },
      h("div", { class: "title" }, p.title),
      h("div", { class: "sub" }, `${p.built ? "Built" : `${done}/${p.steps.length} steps`} · ${ago(p.updated)}`)));
}

// ---------------------------------------------------------------------------
// new
// ---------------------------------------------------------------------------

function viewChoose() {
  return h("div", null,
    h("div", { class: "eyebrow" }, "New video"),
    h("h1", null, "Pick a mode"),
    h("p", { class: "lead" }, "Each one starts from something different. The question is what you have, not what you want."),
    modeGrid());
}

async function viewNew(key) {
  const m = modeOf(key);
  if (!m) throw new Error(`no mode ${key}`);
  const model = {};
  for (const f of m.fields) if (f.default !== null && f.default !== undefined) model[f.key] = structuredClone(f.default);
  const doctor = await api("/api/doctor");
  const missing = m.requires.filter((r) => !doctor.find((c) => c.key === r && c.ok));

  const form = buildForm(m, model, { creating: true });
  const wrap = h("div", null,
    h("div", { class: "eyebrow" }, "New " + m.name.toLowerCase()),
    h("h1", null, m.name),
    h("p", { class: "lead" }, m.blurb),
    missing.length ? h("div", { class: "warnbox", style: "margin-bottom:18px" },
      `Before this will build: ${missing.map((r) => doctor.find((c) => c.key === r).label).join(", ")}. `,
      h("a", { href: "#/doctor", style: "text-decoration:underline" }, "See the doctor.")) : null,
    h("div", { class: "panel" }, form.el),
    h("div", { class: "actions" },
      h("button", { class: "btn primary", onclick: create }, "Create project"),
      h("a", { class: "btn ghost", href: "#/new" }, "Back")));

  async function create() {
    const profile = form.values();
    for (const f of m.fields) {
      if (f.required && (profile[f.key] === "" || profile[f.key] === undefined || (Array.isArray(profile[f.key]) && !profile[f.key].length))) {
        toast(`${f.label} is required`, "bad");
        return;
      }
    }
    try {
      const detail = await api("/api/projects", "POST", { mode: key, name: profile.title, profile });
      await refreshProjects();
      toast(`Created ${detail.title}`, "ok");
      location.hash = `#/p/${detail.name}`;
    } catch (e) { toast(e.message, "bad"); }
  }
  return wrap;
}

// ---------------------------------------------------------------------------
// the form engine
// ---------------------------------------------------------------------------

const GROUPS = [["basics", "Basics"], ["look", "Look"], ["speech", "Speech"], ["sound", "Sound"], ["advanced", "Advanced"]];

function buildForm(mode, model, { creating = false } = {}) {
  const el = h("div", { class: "form" });
  const fields = mode.fields.filter((f) => !creating || f.create);
  for (const [g, label] of GROUPS) {
    const own = fields.filter((f) => f.group === g);
    if (!own.length) continue;
    const details = h("details", { class: "group", open: g === "basics" || (!creating && g !== "advanced") },
      h("summary", null, label));
    for (const f of own) details.append(fieldRow(f, model, mode));
    el.append(details);
  }
  return { el, values: () => model };
}

function fieldRow(f, model, mode) {
  const wide = ["cards", "sections", "corrections", "repairs", "paths", "textarea", "list"].includes(f.kind);
  const row = h("div", { class: `field ${wide ? "wide" : ""}` },
    h("label", null, f.label, f.required ? h("span", { class: "req" }, " *") : null));
  row.append(control(f, model, mode));
  if (f.help) row.append(h("div", { class: "help" }, f.help));
  return row;
}

function control(f, model, mode) {
  const v = model[f.key];
  const set = (val) => { model[f.key] = val; };
  switch (f.kind) {
    case "text":
      return h("input", { class: "input", value: v ?? "", oninput: (e) => set(e.target.value) });
    case "textarea":
      return h("textarea", { class: "input", oninput: (e) => set(e.target.value) }, v ?? "");
    case "number":
      return h("input", { class: "input num", type: "number", value: v ?? "", step: f.step ?? "any", min: f.min, max: f.max,
        oninput: (e) => set(e.target.value === "" ? null : Number(e.target.value)) });
    case "bool":
      return h("label", { class: "toggle" }, h("input", { type: "checkbox", checked: !!v, onchange: (e) => set(e.target.checked) }), h("span", { class: "sw" }));
    case "select":
      return h("select", { class: "input", style: "width:220px", onchange: (e) => set(e.target.value) },
        f.options.map((o) => h("option", { value: o, selected: o === v }, o)));
    case "color":
      return swatches(f.options, v, set);
    case "path":
      return pathRow(v ?? "", set, { kind: "file", filters: f.filters });
    case "folder":
      return pathRow(v ?? "", set, { kind: "folder" });
    case "paths":
      return pathsList(Array.isArray(v) ? v : [], set, f.filters);
    case "list":
      return h("textarea", { class: "input", placeholder: "one per line",
        oninput: (e) => set(e.target.value.split("\n").map((s) => s.trim()).filter(Boolean)) }, (v || []).join("\n"));
    case "corrections":
      return kvTable(v || {}, set);
    case "repairs":
      return repairsTable(v || [], set);
    case "cards":
      return cardsEditor(v || [], set);
    case "sections":
      return sectionsEditor(v || [], set);
    default:
      return h("textarea", { class: "input mono", oninput: (e) => { try { set(JSON.parse(e.target.value)); } catch {} } }, JSON.stringify(v ?? null, null, 2));
  }
}

function swatches(options, current, set) {
  const box = h("div", { class: "swatches" });
  const draw = () => {
    box.innerHTML = "";
    for (const o of options) {
      box.append(h("div", { class: `swatch ${o === current ? "on" : ""}`, title: o, style: `background:${ACCENT_HEX[o] || o}`,
        onclick: () => { current = o; set(o); draw(); } }));
    }
  };
  draw();
  return box;
}

async function pick(opts) {
  const r = await api("/api/pick", "POST", opts);
  return r.paths || [];
}

function pathRow(value, set, { kind, filters }) {
  const input = h("input", { class: "input", value, placeholder: kind === "folder" ? "a folder" : "a file", oninput: (e) => set(e.target.value) });
  const browse = h("button", { class: "btn small", onclick: async () => {
    const paths = await pick({ kind, filters });
    if (paths.length) { input.value = paths[0]; set(paths[0]); }
  } }, "Browse");
  return h("div", { class: "pathrow" }, input, browse);
}

function pathsList(list, set, filters) {
  const wrap = h("div", { class: "paths" });
  const rows = h("div", { class: "paths" });
  const draw = () => {
    rows.innerHTML = "";
    list.forEach((p, i) => rows.append(h("div", { class: "pathrow" },
      h("input", { class: "input", value: p, oninput: (e) => { list[i] = e.target.value; set(list); } }),
      h("button", { class: "mini", title: "remove", onclick: () => { list.splice(i, 1); set(list); draw(); } }, "×"))));
  };
  draw();
  wrap.append(rows, h("div", { class: "row" },
    h("button", { class: "btn small", onclick: async () => { const p = await pick({ kind: "file", multiple: true, filters }); list.push(...p); set(list); draw(); } }, "Add files"),
    h("button", { class: "btn small", onclick: async () => { const p = await pick({ kind: "folder" }); list.push(...p); set(list); draw(); } }, "Add folder"),
    h("button", { class: "btn small ghost", onclick: () => { list.push(""); draw(); } }, "Add a pattern"),
  ));
  return wrap;
}

function kvTable(obj, set) {
  const entries = Object.entries(obj);
  const table = h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "Heard"), h("th", null, "Should be"), h("th"))));
  const body = h("tbody");
  const sync = () => { const o = {}; for (const [k, v] of entries) if (k) o[k] = v; set(o); };
  const draw = () => {
    body.innerHTML = "";
    entries.forEach((e, i) => body.append(h("tr", null,
      h("td", null, h("input", { class: "input", value: e[0], oninput: (ev) => { e[0] = ev.target.value; sync(); } })),
      h("td", null, h("input", { class: "input", value: e[1], oninput: (ev) => { e[1] = ev.target.value; sync(); } })),
      h("td", null, h("button", { class: "mini", onclick: () => { entries.splice(i, 1); sync(); draw(); } }, "×")))));
    body.append(h("tr", null, h("td", { colspan: 3 }, h("button", { class: "btn small ghost", onclick: () => { entries.push(["", ""]); draw(); } }, "+ add"))));
  };
  draw();
  table.append(body);
  return table;
}

function repairsTable(list, set) {
  const table = h("table", { class: "table" }, h("thead", null, h("tr", null, h("th", null, "From (s)"), h("th", null, "To (s)"), h("th"))));
  const body = h("tbody");
  const draw = () => {
    body.innerHTML = "";
    list.forEach((r, i) => body.append(h("tr", null,
      h("td", null, h("input", { class: "input num", type: "number", step: "0.05", value: r[0], oninput: (e) => { r[0] = Number(e.target.value); set(list); } })),
      h("td", null, h("input", { class: "input num", type: "number", step: "0.05", value: r[1], oninput: (e) => { r[1] = Number(e.target.value); set(list); } })),
      h("td", null, h("button", { class: "mini", onclick: () => { list.splice(i, 1); set(list); draw(); } }, "×")))));
    body.append(h("tr", null, h("td", { colspan: 3 }, h("button", { class: "btn small ghost", onclick: () => { list.push([0, 0]); set(list); draw(); } }, "+ add window"))));
  };
  draw();
  table.append(body);
  return table;
}

// ---- short: the cards ----

function cardsEditor(cards, set) {
  const wrap = h("div");
  const table = h("table", { class: "table" }, h("thead", null, h("tr", null,
    h("th", null, "Kind"), h("th", null, "#"), h("th", null, "Headline"), h("th", null, "Icon"), h("th", null, "Note"), h("th", null, "Seconds"), h("th"))));
  const body = h("tbody");
  const total = h("div", { class: "total" });
  const sync = () => { set(cards); const t = cards.reduce((a, c) => a + (Number(c.seconds) || 0), 0); total.innerHTML = `Runs <b>${t.toFixed(1)}s</b> · ${cards.filter((c) => c.kind === "point").length} points`; };
  const draw = () => {
    body.innerHTML = "";
    let n = 0;
    cards.forEach((c, i) => {
      if (c.kind === "point") { n += 1; if (!c.index) c.index = String(n).padStart(2, "0"); }
      const tr = h("tr", null,
        h("td", null, h("select", { class: "input", onchange: (e) => { c.kind = e.target.value; draw(); sync(); } },
          ["title", "point", "cta"].map((k) => h("option", { value: k, selected: c.kind === k }, k)))),
        h("td", null, c.kind === "point" ? h("input", { class: "input", style: "width:52px", value: c.index || "", oninput: (e) => { c.index = e.target.value; sync(); } }) : ""),
        h("td", null, h("input", { class: "input", value: c.headline || "", placeholder: c.kind === "title" ? "The hook" : c.kind === "cta" ? "The close" : "The point", oninput: (e) => { c.headline = e.target.value; sync(); } })),
        h("td", null, c.kind === "point" ? iconPicker(c.icon || "", (name) => { c.icon = name; sync(); }) : ""),
        h("td", null, h("input", { class: "input", value: c.note || "", placeholder: "a few words", oninput: (e) => { c.note = e.target.value; sync(); } })),
        h("td", null, h("input", { class: "input num", type: "number", step: "0.1", min: "0.4", value: c.seconds ?? 1.5, oninput: (e) => { c.seconds = Number(e.target.value); sync(); } })),
        h("td", null, h("div", { class: "row", style: "gap:2px;flex-wrap:nowrap" },
          h("button", { class: "mini", disabled: i === 0, onclick: () => { [cards[i - 1], cards[i]] = [cards[i], cards[i - 1]]; draw(); sync(); } }, "↑"),
          h("button", { class: "mini", disabled: i === cards.length - 1, onclick: () => { [cards[i + 1], cards[i]] = [cards[i], cards[i + 1]]; draw(); sync(); } }, "↓"),
          h("button", { class: "mini", onclick: () => { cards.splice(i, 1); draw(); sync(); } }, "×"))));
      body.append(tr);
    });
  };
  draw(); sync();
  table.append(body);
  wrap.append(table, h("div", { class: "row", style: "margin-top:8px" },
    h("button", { class: "btn small ghost", onclick: () => { const at = Math.max(0, cards.findIndex((c) => c.kind === "cta")); cards.splice(at < 0 ? cards.length : at, 0, { kind: "point", index: "", headline: "", icon: "bolt", note: "", seconds: 1.5 }); draw(); sync(); } }, "+ add a point"),
    total));
  return wrap;
}

function iconPicker(current, onpick) {
  const glyph = h("span", { class: "ms", title: current }, current);
  const btn = h("button", { class: "btn small", onclick: open }, "pick");
  const cell = h("div", { class: "icon-cell" }, glyph, btn);
  async function open(ev) {
    $$(".icon-pop").forEach((p) => p.remove());
    const pop = h("div", { class: "icon-pop" });
    const input = h("input", { class: "input", placeholder: "search icons — e.g. warning, money, bug", autofocus: true });
    const grid = h("div", { class: "grid-icons" });
    const search = async () => {
      const names = await api(`/api/icons?q=${encodeURIComponent(input.value)}&limit=96`);
      grid.innerHTML = "";
      for (const n of names) grid.append(h("button", { class: n === current ? "on" : "", title: n, onclick: () => { current = n; glyph.textContent = n; glyph.title = n; onpick(n); pop.remove(); } }, h("span", { class: "ms" }, n)));
    };
    input.addEventListener("input", search);
    pop.append(input, grid);
    document.body.append(pop);
    const r = btn.getBoundingClientRect();
    pop.style.left = Math.min(r.left, window.innerWidth - 380) + "px";
    pop.style.top = Math.min(r.bottom + 6, window.innerHeight - 320) + "px";
    input.focus();
    input.value = current.replace(/_/g, " ");
    await search();
    setTimeout(() => document.addEventListener("click", (e) => { if (!pop.contains(e.target) && e.target !== btn) pop.remove(); }, { once: true }), 0);
  }
  return cell;
}

// ---- presenter: the sections ----

function sectionsEditor(sections, set) {
  const wrap = h("div");
  const list = h("div");
  const layouts = S.state.layouts.slide;
  const draw = () => {
    list.innerHTML = "";
    sections.forEach((s, i) => {
      s.visual = s.visual || { kind: "none" };
      s.meta = s.meta || {};
      const card = h("div", { class: "section-card" });
      const visualBox = h("div");
      const drawVisual = () => {
        visualBox.innerHTML = "";
        if (s.visual.kind === "slide") {
          const spec = s.meta.slide = s.meta.slide || { layout: "statement", headline: "" };
          visualBox.append(h("div", { class: "slide-spec" },
            h("select", { class: "input", onchange: (e) => { spec.layout = e.target.value; set(sections); } }, layouts.map((l) => h("option", { value: l, selected: spec.layout === l }, l))),
            h("input", { class: "input", placeholder: "Headline — *word* is accented", value: spec.headline || "", oninput: (e) => { spec.headline = e.target.value; set(sections); } }),
            h("input", { class: "input", placeholder: "kicker", value: spec.kicker || "", oninput: (e) => { spec.kicker = e.target.value; set(sections); } }),
            h("textarea", { class: "input", placeholder: "items, one per line (label | value | note)", oninput: (e) => {
              spec.items = e.target.value.split("\n").map((l) => l.trim()).filter(Boolean).map((l) => { const [label, value, note] = l.split("|").map((x) => x.trim()); return { label, ...(value ? { value } : {}), ...(note ? { note } : {}) }; });
              set(sections);
            } }, (spec.items || []).map((it) => [it.label, it.value, it.note].filter(Boolean).join(" | ")).join("\n"))));
        } else if (s.visual.kind === "screen") {
          visualBox.append(pathRow(s.visual.path || "", (p) => { s.visual.path = p; set(sections); }, { kind: "file", filters: ["*.mp4", "*.mov", "*.mkv", "*.webm"] }));
        }
      };
      card.append(
        h("div", { class: "head" },
          h("input", { class: "input", value: s.id || "", placeholder: "01_hook", oninput: (e) => { s.id = e.target.value; set(sections); } }),
          h("select", { class: "input", title: "framing", onchange: (e) => { s.presenter = e.target.value; set(sections); } },
            ["full", "corner", "off"].map((k) => h("option", { value: k, selected: (s.presenter || "corner") === k }, k))),
          h("select", { class: "input", title: "behind you", onchange: (e) => { s.visual.kind = e.target.value; set(sections); drawVisual(); } },
            ["none", "slide", "screen"].map((k) => h("option", { value: k, selected: s.visual.kind === k }, k))),
          h("span", { class: "spacer" }),
          h("button", { class: "mini", disabled: i === 0, onclick: () => { [sections[i - 1], sections[i]] = [sections[i], sections[i - 1]]; set(sections); draw(); } }, "↑"),
          h("button", { class: "mini", disabled: i === sections.length - 1, onclick: () => { [sections[i + 1], sections[i]] = [sections[i], sections[i + 1]]; set(sections); draw(); } }, "↓"),
          h("button", { class: "mini", onclick: () => { sections.splice(i, 1); set(sections); draw(); } }, "×")),
        h("textarea", { class: "input", placeholder: "What you will say.", oninput: (e) => { s.say = e.target.value; set(sections); } }, s.say || ""),
        h("input", { class: "input", placeholder: "delivery note (only you see this)", value: s.note || "", oninput: (e) => { s.note = e.target.value; set(sections); } }),
        visualBox);
      drawVisual();
      list.append(card);
    });
  };
  draw();
  wrap.append(list, h("button", { class: "btn small ghost", onclick: () => {
    const n = String(sections.length + 1).padStart(2, "0");
    sections.push({ id: `${n}_section`, presenter: "corner", visual: { kind: "slide" }, say: "", meta: { slide: { layout: "statement", headline: "" } } });
    set(sections); draw();
  } }, "+ add a section"));
  return wrap;
}

// ---------------------------------------------------------------------------
// project
// ---------------------------------------------------------------------------

async function viewProject(name, tab) {
  const d = await api(`/api/projects/${encodeURIComponent(name)}`);
  S.detail = d;
  const m = modeOf(d.mode);
  const wrap = h("div");
  const outDir = d.home;

  wrap.append(h("div", { class: "proj-head" },
    h("div", { style: "flex:1;min-width:0" },
      h("div", { class: "eyebrow" }, `${m.name} · ${d.profile.aspect || m.aspect}`),
      h("h1", null, d.title),
      h("div", { class: "meta" },
        h("a", { href: "#", onclick: (e) => { e.preventDefault(); api("/api/open", "POST", { path: d.path }); } }, d.path),
        h("span", null, "·"),
        h("a", { href: "#", onclick: (e) => { e.preventDefault(); api("/api/open", "POST", { path: outDir }).catch(() => toast("Nothing built yet", "")); } }, "output folder"))),
    h("div", { class: "row" },
      d.artifacts[m.output] && d.artifacts[m.output].exists
        ? h("a", { class: "btn primary", href: `#/p/${name}?tab=output` }, "Watch")
        : null)));

  wrap.append(pipeline(d, m));
  wrap.append(h("div", { class: "tabs" }, [["setup", "Setup"], ["plan", planLabel(m)], ["output", "Output"], ["activity", "Activity"]]
    .filter(([k]) => k !== "plan" || planLabel(m))
    .map(([k, label]) => h("a", { href: `#/p/${name}?tab=${k}`, class: k === tab ? "active" : "" }, label))));

  if (tab === "setup") wrap.append(await tabSetup(d, m));
  else if (tab === "plan") wrap.append(await tabPlan(d, m));
  else if (tab === "output") wrap.append(tabOutput(d, m));
  else wrap.append(tabActivity(d));
  return wrap;
}

function planLabel(m) {
  return m.key === "edit" || m.key === "reel" ? "Plan" : m.key === "demo" ? "Scenes" : m.key === "present" ? "Takes" : "";
}

function activeFor(name) {
  return Object.values(S.jobs).find((j) => j.project === name && (j.status === "running" || j.status === "queued"));
}

function pipeline(d, m) {
  const running = activeFor(d.name);
  const busy = Object.values(S.jobs).some((j) => j.status === "running" || j.status === "queued");
  const grid = h("div", { class: "pipeline" });
  m.steps.forEach((s, i) => {
    const st = d.steps.find((x) => x.key === s.key) || {};
    const isRunning = running && running.step === s.key;
    const cls = ["step", st.done ? "done" : "", isRunning ? "running" : "", !st.ready ? "locked" : ""].join(" ");
    const opts = {};
    const optsBox = s.options.length ? h("div", { class: "opts" }, s.options.map((o) => {
      const c = control(o, opts, m);
      return h("div", { class: "o" }, h("label", { class: "dim" }, o.label), c);
    })) : null;
    if (optsBox) optsBox.hidden = true;
    const run = h("button", { class: `btn small ${st.done ? "" : "primary"}`, disabled: busy, onclick: async () => {
      try {
        const job = await api(`/api/projects/${encodeURIComponent(d.name)}/run`, "POST", { step: s.key, options: opts });
        S.jobs[job.id] = job;
        showDock(job, true);
        route();
      } catch (e) { toast(e.message, "bad"); }
    } }, isRunning ? [h("span", { class: "spin" }), "Running"] : st.done ? "Run again" : "Run");
    grid.append(h("div", { class: cls },
      h("div", { class: "n" }, h("span", { class: "st" }), `STEP ${i + 1}`, s.heavy ? h("span", { class: "heavy" }, "· takes a while") : null),
      h("h3", null, s.label),
      h("p", null, s.help),
      optsBox,
      h("div", { class: "foot" }, run,
        s.options.length ? h("button", { class: "btn small ghost", onclick: () => { optsBox.hidden = !optsBox.hidden; } }, "options") : null,
        !st.ready ? h("span", { class: "dim", style: "font-size:11.5px" }, `needs ${s.needs.join(", ")}`) : null)));
  });
  return grid;
}

async function tabSetup(d, m) {
  const model = structuredClone(d.profile);
  const form = buildForm(m, model, { creating: false });
  const raw = h("textarea", { class: "editor", style: "min-height:360px" }, JSON.stringify(d.profile, null, 2));
  raw.hidden = true;
  let showingRaw = false;
  const toggle = h("button", { class: "btn ghost small", onclick: () => {
    showingRaw = !showingRaw;
    if (showingRaw) { raw.value = JSON.stringify(model, null, 2); }
    else { try { Object.assign(model, JSON.parse(raw.value)); } catch (e) { toast("The JSON has an error; fix it before switching back", "bad"); showingRaw = true; return; } form.el.replaceWith(rebuild()); }
    raw.hidden = !showingRaw; formBox.hidden = showingRaw;
  } }, "Raw JSON");
  let formBox = h("div", null, form.el);
  const rebuild = () => { const f = buildForm(m, model); formBox.innerHTML = ""; formBox.append(f.el); return f.el; };
  const save = h("button", { class: "btn primary", onclick: async () => {
    let profile = model;
    if (showingRaw) { try { profile = JSON.parse(raw.value); } catch (e) { toast("Not valid JSON: " + e.message, "bad"); return; } }
    try {
      await api(`/api/projects/${encodeURIComponent(d.name)}/profile`, "PUT", { profile });
      toast("Saved", "ok"); await refreshProjects(); route();
    } catch (e) { toast(e.message, "bad"); }
  } }, "Save");

  const panel = h("div", { class: "panel" }, formBox, raw, h("div", { class: "actions" }, save, toggle));
  const wrap = h("div", null, panel);

  if (m.key === "short" && d.profile.background) wrap.append(await backgroundPanel(d));
  if (m.key === "reel") wrap.append(folderPanel(d, "broll", "B-roll", "Screen recordings or clips for cutaways. Refer to them by file name in the plan."));
  return wrap;
}

async function backgroundPanel(d) {
  let info = { seconds: 0 };
  try { info = await api(`/api/probe?path=${encodeURIComponent(resolveIn(d, d.profile.background))}`); } catch {}
  const runs = (d.profile.cards || []).reduce((a, c) => a + (Number(c.seconds) || 0), 0);
  const note = info.seconds
    ? info.seconds >= runs ? `The clip is ${info.seconds.toFixed(1)}s and the cards run ${runs.toFixed(1)}s: one continuous take, no loop.`
      : `The clip is ${info.seconds.toFixed(1)}s and the cards run ${runs.toFixed(1)}s: it will loop with a crossfade.`
    : "";
  return h("div", { class: "panel" },
    h("h3", null, "Background"),
    h("div", { class: "output-hero vertical" },
      h("div", { class: "player vertical" }, h("video", { controls: true, muted: true, loop: true, src: `/api/media?path=${encodeURIComponent(resolveIn(d, d.profile.background))}` })),
      h("div", null,
        h("p", { class: "muted" }, note),
        info.width ? h("p", { class: "dim" }, `${info.width}×${info.height}`) : null)));
}

function resolveIn(d, p) {
  if (/^([a-zA-Z]:[\\/]|\/)/.test(p)) return p;
  return d.path.replace(/[\\/]$/, "") + "/" + p;
}

function folderPanel(d, sub, title, help, opts = {}) {
  const files = (d.files[sub] || []);
  const list = h("div", { class: "filelist" }, files.length ? files.map((f) => h("div", null, h("b", null, f.name), h("span", { class: "dim" }, fmtSize(f.size)))) : h("div", { class: "dim" }, "Nothing here yet."));
  return h("div", { class: "panel" },
    h("h3", null, title),
    h("p", { class: "muted", style: "margin-top:0" }, help),
    list,
    h("div", { class: "actions" },
      h("button", { class: "btn small", onclick: async () => {
        const paths = await pick({ kind: "file", multiple: true, filters: ["*.mp4", "*.mov", "*.mkv", "*.webm", "*.m4a", "*.wav", "*.mp3"] });
        if (!paths.length) return;
        await api(`/api/projects/${encodeURIComponent(d.name)}/import`, "POST", { into: sub, paths });
        toast(`Copied ${paths.length} file${paths.length > 1 ? "s" : ""}`, "ok"); route();
      } }, "Add files"),
      h("button", { class: "btn small ghost", onclick: () => api("/api/open", "POST", { path: d.path + "/" + sub }).catch(() => toast("Folder does not exist yet")) }, "Open folder")));
}

async function tabPlan(d, m) {
  if (m.key === "present") return takesPanel(d);
  const wrap = h("div");
  const plan = d.plan;
  if (!plan) {
    wrap.append(h("div", { class: "empty" }, m.key === "demo" ? "Run Plan to read the repository and propose scenes." : "Run Ingest and then Plan. The cut appears here as a table you can read and a file you can edit."));
  } else if (plan.error) {
    wrap.append(h("div", { class: "warnbox" }, plan.error));
  } else if (plan.kind === "scenes") {
    wrap.append(h("div", { class: "panel" }, h("h3", null, `${plan.rows.length} scenes`),
      h("table", { class: "table plan-table" }, h("thead", null, h("tr", null, h("th", null, "id"), h("th", null, "visual"), h("th", null, "narration"), h("th", null, "runs"))),
        h("tbody", null, plan.rows.map((r) => h("tr", null, h("td", { class: "id" }, r.id), h("td", null, r.visual), h("td", { class: "say" }, r.text), h("td", { class: "mono" }, r.extra)))))));
  } else {
    wrap.append(h("div", { class: "panel" },
      h("h3", null, `${plan.rows.length} sections · ${fmtTime(plan.seconds)} of source`),
      h("table", { class: "table plan-table" }, h("thead", null, h("tr", null, h("th", null, "id"), h("th", null, "in"), h("th", null, "out"), h("th", null, "shot"), h("th", null, "on screen"), h("th", null, "says"))),
        h("tbody", null, plan.rows.map((r) => h("tr", null,
          h("td", { class: "id" }, r.id), h("td", { class: "mono" }, r.start?.toFixed?.(2) ?? r.start), h("td", { class: "mono" }, r.end?.toFixed?.(2) ?? r.end),
          h("td", null, r.shot || r.layout), h("td", null, r.headline), h("td", { class: "say" }, r.say)))))));
  }
  // The files behind the table. plan.json is what build reads; cut.json is the
  // hand-written cut that `plan --from` settles. Either is editable here.
  for (const file of ["plan.json", "cut.json"]) {
    const path = d.path + "/" + file;
    const art = Object.values(d.artifacts).find((a) => a.pattern === file);
    if (!art || !art.exists) {
      if (file === "cut.json" && m.key !== "demo") wrap.append(h("div", { class: "panel" }, h("h3", null, "cut.json"),
        h("p", { class: "muted" }, "Write the cut by hand here and settle it with Plan → options → “Settle cut.json”. See docs/reel-mode.md for the shape."),
        h("button", { class: "btn small", onclick: async () => { await api("/api/file", "PUT", { path, text: JSON.stringify({ note: "sections in seconds into the source", sections: [] }, null, 2) }); route(); } }, "Start a cut.json")));
      continue;
    }
    wrap.append(await fileEditor(path, file));
  }
  return wrap;
}

async function fileEditor(path, title) {
  const { text } = await api(`/api/file?path=${encodeURIComponent(path)}`);
  const editor = h("textarea", { class: "editor" }, text);
  editor.hidden = true;
  const open = h("button", { class: "btn small ghost", onclick: () => { editor.hidden = !editor.hidden; open.textContent = editor.hidden ? "Edit" : "Hide"; } }, "Edit");
  return h("div", { class: "panel" },
    h("div", { class: "row" }, h("h3", { style: "margin:0" }, title), h("span", { class: "spacer" }), open,
      h("button", { class: "btn small", onclick: async () => { try { await api("/api/file", "PUT", { path, text: editor.value }); toast("Saved " + title, "ok"); } catch (e) { toast(e.message, "bad"); } } }, "Save")),
    editor);
}

function takesPanel(d) {
  const sections = d.profile.sections || [];
  const takes = d.files.takes || [];
  const rows = sections.map((s) => {
    const found = takes.find((t) => t.name.replace(/\.[^.]+$/, "") === s.id);
    return h("tr", null,
      h("td", { class: "id" }, s.id),
      h("td", null, s.presenter || "corner"),
      h("td", { class: "say" }, (s.say || "").slice(0, 120)),
      h("td", null, found ? h("span", { class: "chip ok" }, "recorded") : h("span", { class: "chip warn" }, "missing")),
      h("td", null, h("button", { class: "btn small", onclick: async () => {
        const paths = await pick({ kind: "file", filters: ["*.mp4", "*.mov", "*.mkv", "*.webm", "*.m4a", "*.wav", "*.mp3"] });
        if (!paths.length) return;
        const ext = paths[0].match(/\.[^.\\/]+$/)?.[0] || ".mp4";
        await api(`/api/projects/${encodeURIComponent(d.name)}/import`, "POST", { into: "takes", paths, rename: { [paths[0]]: s.id + ext } });
        toast(`Take for ${s.id} added`, "ok"); route();
      } }, found ? "Replace" : "Add take")));
  });
  const script = d.artifacts.script;
  return h("div", null,
    h("div", { class: "panel" },
      h("h3", null, "Takes"),
      h("p", { class: "muted", style: "margin-top:0" }, "One recording per section. Same distance, framing and lighting for all of them; two seconds of silence at each end. Run Script first for the words and target times, then Intake to check what you recorded."),
      h("table", { class: "table plan-table" }, h("thead", null, h("tr", null, h("th", null, "section"), h("th", null, "framing"), h("th", null, "says"), h("th", null, "take"), h("th"))), h("tbody", null, rows)),
      h("div", { class: "actions" },
        script && script.exists ? h("button", { class: "btn small", onclick: () => api("/api/open", "POST", { path: script.files[0].path }) }, "Open the recording script") : h("span", { class: "dim" }, "Run Script to get RECORDING-SCRIPT.md"),
        h("button", { class: "btn small ghost", onclick: () => api("/api/open", "POST", { path: d.path + "/takes" }) }, "Open takes folder"))));
}

function tabOutput(d, m) {
  const out = d.artifacts[m.output];
  const wrap = h("div");
  const vertical = (d.profile.aspect || m.aspect) === "9:16";
  if (!out || !out.exists) {
    wrap.append(h("div", { class: "empty" }, "Nothing built yet. Run the steps above; the film appears here."));
  } else {
    const file = out.files[out.files.length - 1];
    const cover = d.artifacts.cover && d.artifacts.cover.exists ? d.artifacts.cover.files[0] : null;
    wrap.append(h("div", { class: `output-hero ${vertical ? "vertical" : ""}` },
      h("div", { class: `player ${vertical ? "vertical" : ""}` }, h("video", { controls: true, src: file.url + "&v=" + Math.round(file.mtime) })),
      h("div", null,
        h("h3", null, file.name),
        h("p", { class: "muted" }, `${fmtSize(file.size)} · ${ago(file.mtime)}`),
        h("div", { class: "row" },
          h("button", { class: "btn", onclick: () => api("/api/open", "POST", { path: file.path }) }, "Open"),
          h("button", { class: "btn", onclick: () => api("/api/open", "POST", { path: file.path, reveal: true }) }, "Show in folder")),
        cover ? h("div", { style: "margin-top:18px" }, h("h3", null, "Cover"), h("img", { class: "cover-img", src: cover.url + "&v=" + Math.round(cover.mtime), style: vertical ? "max-width:200px" : "" })) : null)));
  }
  const others = Object.values(d.artifacts).filter((a) => a.key !== m.output && a.key !== "cover");
  wrap.append(h("div", { class: "section-title" }, h("h2", null, "Everything it made")));
  wrap.append(h("div", { class: "artlist" }, others.map((a) => h("div", { class: `art ${a.exists ? "" : "missing"}` },
    h("div", { class: "info" }, h("div", { class: "k" }, a.label), h("div", { class: "p" }, a.exists ? a.files.map((f) => f.name).join(", ") : a.pattern)),
    a.exists ? h("button", { class: "btn small ghost", onclick: () => api("/api/open", "POST", { path: a.files[0].path, reveal: a.kind !== "folder" }) }, a.kind === "folder" ? "Open" : "Show") : h("span", { class: "dim" }, "not yet")))));
  return wrap;
}

function tabActivity(d) {
  const jobs = d.jobs.length ? d.jobs : Object.values(S.jobs).filter((j) => j.project === d.name).sort((a, b) => b.created - a.created);
  if (!jobs.length) return h("div", { class: "empty" }, "No runs yet.");
  return h("div", { class: "panel jobs-list" }, jobs.map((j) => h("div", { class: "job", onclick: () => showDock(j, true) },
    h("span", { class: `st ${j.status}` }, j.status),
    h("span", null, h("b", null, j.step), " ", h("span", { class: "dim mono" }, j.argv.slice(3).join(" "))),
    h("span", { class: "dim" }, j.ended ? fmtTime(j.ended - j.started) : ""),
    h("span", { class: "dim" }, ago(j.created)))));
}

// ---------------------------------------------------------------------------
// tools: one feature, one file
// ---------------------------------------------------------------------------

const TOOL_GLYPHS = {
  score: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 18V6l10-2v12"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="16.5" cy="16" r="2.5"/></svg>',
  caption: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M7 14h6M15 14h2M7 10h2M11 10h6"/></svg>',
  tighten: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M4 12h6M14 12h6M10 7l4 5-4 5"/></svg>',
  gaze: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M2 12s4-7 10-7 10 7 10 7-4 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  cover: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 15l5-5 4 4 3-3 6 6"/></svg>',
  punch: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="6"/><path d="M20 20l-4.5-4.5M11 8v6M8 11h6"/></svg>',
  voice: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  lipsync: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 12c3-4 6-4 9 0s6 4 9 0M3 12c3 4 6 4 9 0s6-4 9 0"/></svg>',
  broll_generate: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 3l1.8 4.6L18 9l-4.2 1.4L12 15l-1.8-4.6L6 9l4.2-1.4zM5 17l.8 2 2 .8-2 .8L5 22l-.8-1.4-2-.8 2-.8z"/></svg>',
  broll_search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="10" cy="10" r="6"/><path d="M20 20l-5.5-5.5M8 10h4"/></svg>',
};

function toolGrid() {
  return h("div", { class: "grid modes" }, Object.values(S.state.tools).map((t) =>
    h("div", { class: "mode-card", onclick: () => (location.hash = `#/tools/${t.key}`) },
      t.heavy ? h("span", { class: "tag" }, "SLOW") : null,
      h("div", { class: "glyph", html: TOOL_GLYPHS[t.key] || "" }),
      h("h3", null, t.name),
      h("p", null, t.tagline),
      h("ul", { class: "needs" }, t.needs.map((n) => h("li", null, n))))));
}

function viewTools() {
  return h("div", null,
    h("div", { class: "eyebrow" }, "Tools"),
    h("h1", null, "One feature, one file"),
    h("p", { class: "lead" }, "Everything the modes are built from, on its own. Drop a file in, set two or three things, get a file back. No project needed."),
    toolGrid());
}

async function viewTool(key) {
  const t = S.state.tools[key];
  if (!t) throw new Error(`no tool ${key}`);
  const doctor = await api("/api/doctor");
  const missing = t.requires.filter((r) => !doctor.find((c) => c.key === r && c.ok));
  const model = {};
  for (const f of t.fields) if (f.default !== null && f.default !== undefined) model[f.key] = structuredClone(f.default);
  const form = buildForm(t, model, { creating: true });
  const busy = Object.values(S.jobs).some((j) => j.status === "running" || j.status === "queued");
  const run = h("button", { class: "btn primary", disabled: busy, onclick: async () => {
    for (const f of t.fields) {
      if (f.required && (model[f.key] === "" || model[f.key] === undefined)) { toast(`${f.label} is required`, "bad"); return; }
    }
    try {
      const job = await api(`/api/tools/${key}/run`, "POST", { options: model });
      S.jobs[job.id] = job;
      showDock(job, true);
      run.disabled = true;
      run.innerHTML = ""; run.append(h("span", { class: "spin" }), " Running");
    } catch (e) { toast(e.message, "bad"); }
  } }, busy ? "Something else is running" : `Run ${t.name}`);

  const results = h("div", { class: "tool-runs" });
  const refresh = async () => {
    const runs = await api(`/api/tools/${key}/runs`);
    results.innerHTML = "";
    results.append(...(runs.length ? runs.map(toolRun) : [h("div", { class: "empty" }, "Nothing yet. What comes back lands here, newest first.")]));
    const busyNow = Object.values(S.jobs).some((j) => j.status === "running" || j.status === "queued");
    run.disabled = busyNow;
    run.textContent = busyNow ? "Something else is running" : `Run ${t.name}`;
  };
  // A finished run refreshes the results and leaves the form as it was, so
  // the next run is one click rather than a re-fill.
  S.detail = { name: `tool:${key}`, refresh };
  await refresh();

  return h("div", null,
    h("div", { class: "eyebrow" }, "Tool" + (t.heavy ? " · takes a while" : "")),
    h("h1", null, t.name),
    h("p", { class: "lead" }, t.blurb),
    missing.length ? h("div", { class: "warnbox", style: "margin-bottom:18px" },
      `Needs: ${missing.map((r) => (doctor.find((c) => c.key === r) || { label: r }).label).join(", ")}. `,
      h("a", { href: "#/doctor", style: "text-decoration:underline" }, "See the doctor.")) : null,
    h("div", { class: "tool-form" },
      h("div", { class: "panel" }, form.el, h("div", { class: "actions" }, run, h("span", { class: "dim" }, `→ ${t.makes}`))),
      h("div", null, h("h3", null, "Results"), results)));
}

function toolRun(r) {
  const media = r.files.filter((f) => ["video", "image", "audio"].includes(f.kind));
  const rest = r.files.filter((f) => !["video", "image", "audio"].includes(f.kind));
  return h("div", { class: "tool-run" },
    h("div", { class: "head" }, h("span", { class: "name" }, r.name), h("span", { class: "dim" }, ago(r.mtime)), h("span", { class: "spacer" }),
      h("button", { class: "btn small ghost", onclick: () => api("/api/open", "POST", { path: r.path }) }, "Open folder")),
    media.length ? h("div", { class: "media" }, media.map((f) =>
      f.kind === "video" ? h("video", { controls: true, src: f.url + "&v=" + Math.round(f.mtime), title: f.name })
        : f.kind === "image" ? h("img", { src: f.url + "&v=" + Math.round(f.mtime), alt: f.name, onclick: () => api("/api/open", "POST", { path: f.path }) })
        : h("audio", { controls: true, src: f.url }))) : null,
    h("div", { class: "files" }, r.files.map((f) => h("a", { title: f.path, onclick: () => api("/api/open", "POST", { path: f.path, reveal: f.kind !== "text" && f.kind !== "json" }) }, `${f.name} · ${fmtSize(f.size)}`))),
    rest.some((f) => f.name === "report.txt") ? reportBox(rest.find((f) => f.name === "report.txt").path) : null);
}

function reportBox(path) {
  const pre = h("pre", { class: "log", style: "max-height:220px;border:1px solid var(--line);border-radius:8px;margin-top:10px" });
  api(`/api/file?path=${encodeURIComponent(path)}`).then((r) => { pre.textContent = r.text; }).catch(() => pre.remove());
  return pre;
}

// ---------------------------------------------------------------------------
// settings + doctor
// ---------------------------------------------------------------------------

async function viewSettings() {
  const s = await api("/api/settings");
  const model = { projects_dir: s.projects_dir, out_dir: s.out_dir, music_dir: s.music_dir, whisper_model: s.whisper_model, keys: {} };
  const keyRow = (key, label, hint) => {
    const input = h("input", { class: "input", type: "password", placeholder: s.keys[key] ? "set — paste to replace" : "not set", oninput: (e) => { model.keys[key] = e.target.value; } });
    return [h("div", { class: "k" }, label, h("div", { class: "dim", style: "font-size:11.5px" }, hint)),
      h("div", { class: "keyrow" }, input, h("span", { class: s.keys[key] ? "status-ok" : "status-off" }, s.keys[key] ? "SET" : "UNSET"),
        s.keys[key] ? h("button", { class: "btn small ghost danger", onclick: () => { model.keys[key] = ""; input.placeholder = "will be removed on save"; } }, "remove") : null)];
  };
  const wrap = h("div", null,
    h("div", { class: "eyebrow" }, "Settings"),
    h("h1", null, "Where things live"),
    h("p", { class: "lead" }, "Projects and output are folders you own. Move them anywhere; an update to demoforge never touches them."),
    h("div", { class: "panel" }, h("div", { class: "kv" },
      h("div", { class: "k" }, "Projects folder"), pathRow(model.projects_dir, (v) => (model.projects_dir = v), { kind: "folder" }),
      h("div", { class: "k" }, "Output folder"), pathRow(model.out_dir, (v) => (model.out_dir = v), { kind: "folder" }),
      h("div", { class: "k" }, "Music folder", h("div", { class: "dim", style: "font-size:11.5px" }, "Tracks you own. Used before anything is fetched.")), pathRow(model.music_dir || "", (v) => (model.music_dir = v), { kind: "folder" }),
      h("div", { class: "k" }, "Default recogniser"), h("select", { class: "input", style: "width:220px", onchange: (e) => (model.whisper_model = e.target.value) }, ["medium.en", "large-v3", "small.en", "base.en"].map((o) => h("option", { value: o, selected: o === model.whisper_model }, o))),
    )),
    h("div", { class: "panel" }, h("h3", null, "Keys"), h("p", { class: "muted", style: "margin-top:0" }, `Stored in ${s.env_path}, on this machine only.`),
      h("div", { class: "kv" },
        ...keyRow("ANTHROPIC_API_KEY", "Anthropic", "Plans the cut in Editor mode and the scenes in Demo mode. Without it, Editor falls back to the longest take."),
        ...keyRow("PIXABAY_API_KEY", "Pixabay", "Fetches licence-free music when no local track is pinned. Optional."))),
    h("div", { class: "panel" }, h("h3", null, "Install"),
      h("p", { class: "muted", style: "margin-top:0" }, "Put demoforge in the Start Menu and on the desktop so it opens like any other application."),
      h("button", { class: "btn", onclick: async () => { try { const r = await api("/api/shortcuts", "POST"); toast(`Made ${r.made.length} shortcut${r.made.length === 1 ? "" : "s"}`, "ok"); } catch (e) { toast(e.message, "bad"); } } }, "Create shortcuts")),
    h("div", { class: "actions" }, h("button", { class: "btn primary", onclick: async () => {
      try { await api("/api/settings", "PUT", model); toast("Saved", "ok"); S.state = await api("/api/state"); await refreshProjects(); route(); } catch (e) { toast(e.message, "bad"); }
    } }, "Save")));
  return wrap;
}

async function viewDoctor() {
  const checks = await api("/api/doctor");
  const bad = checks.filter((c) => !c.ok);
  return h("div", null,
    h("div", { class: "eyebrow" }, "Doctor"),
    h("h1", null, bad.length ? `${bad.length} thing${bad.length > 1 ? "s" : ""} missing` : "Everything is here"),
    h("p", { class: "lead" }, "What is installed, what is not, and what each mode needs. Nothing here blocks the app; it only says which step will fail."),
    h("div", { class: "panel checks" }, checks.map((c) => h("div", { class: `check ${c.ok ? "ok" : "bad"}` },
      h("span", { class: "mark" }, c.ok ? "✓" : "×"),
      h("span", null, h("b", null, c.label), c.detail ? h("div", { class: "dim", style: "font-size:11.5px" }, c.detail) : null),
      h("span", { class: "fix" }, c.ok ? "" : c.fix),
      h("span", { class: "for" }, c.needed_by)))));
}

async function checkDoctorBadge() {
  try {
    const checks = await api("/api/doctor");
    const critical = checks.filter((c) => !c.ok && ["ffmpeg", "whisper", "torch"].includes(c.key)).length;
    const badge = $("#doctor-badge");
    badge.hidden = !critical;
    badge.textContent = critical;
  } catch {}
}

// ---------------------------------------------------------------------------
// jobs: the socket and the dock
// ---------------------------------------------------------------------------

function connect() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws`);
  S.ws = ws;
  ws.onmessage = (ev) => {
    const e = JSON.parse(ev.data);
    if (e.type === "hello") {
      for (const j of e.jobs) S.jobs[j.id] = j;
      if (e.active) showDock(e.active, false);
    } else if (e.type === "job") {
      const before = S.jobs[e.job.id];
      S.jobs[e.job.id] = e.job;
      if (e.job.status === "running" && (!S.dockJob || S.dockJob.status !== "running" || S.dockJob.id === e.job.id)) showDock(e.job, false);
      if (S.dockJob && S.dockJob.id === e.job.id) { S.dockJob = e.job; paintDock(); }
      if (before && before.status !== e.job.status && ["done", "failed", "cancelled"].includes(e.job.status)) {
        toast(`${e.job.project} · ${e.job.step}: ${e.job.status}`, e.job.status === "done" ? "ok" : e.job.status === "failed" ? "bad" : "");
        if (e.job.status === "failed") { $("#dock-log").hidden = false; }
        if (S.detail && S.detail.name === e.job.project && S.detail.refresh) S.detail.refresh();
        else refreshProjects().then(() => { if (S.detail && S.detail.name === e.job.project) route(); });
      } else if (before && before.status !== e.job.status) {
        if (S.detail && S.detail.name === e.job.project && !S.detail.refresh) route();
      }
    } else if (e.type === "line") {
      if (S.dockJob && S.dockJob.id === e.id) appendLine(e.text, e.n);
      if (e.phase && S.dockJob && S.dockJob.id === e.id) { S.dockJob.phase = e.phase; $("#dock-phase").textContent = e.phase; }
    }
  };
  ws.onclose = () => setTimeout(connect, 1500);
}

async function showDock(job, openLog) {
  S.dockJob = job;
  const dock = $("#dock");
  dock.hidden = false;
  const log = $("#dock-log");
  log.innerHTML = "";
  log.hidden = !openLog;
  paintDock();
  try {
    const full = await api(`/api/jobs/${job.id}?since=0`);
    S.dockJob = { ...full, tail: undefined };
    log.innerHTML = "";
    for (const line of full.tail) appendLine(line);
    paintDock();
  } catch {}
}

function paintDock() {
  const j = S.dockJob;
  if (!j) return;
  const dock = $("#dock");
  dock.className = `dock ${j.status}`;
  $("#dock-title").textContent = `${j.project} · ${j.step}`;
  $("#dock-phase").textContent = j.phase || (j.status === "queued" ? "queued" : "");
  $("#dock-cancel").hidden = !(j.status === "running" || j.status === "queued");
  $("#dock-cancel").onclick = () => api(`/api/jobs/${j.id}/cancel`, "POST");
  $("#dock-toggle").onclick = () => { const log = $("#dock-log"); log.hidden = !log.hidden; if (!log.hidden) log.scrollTop = log.scrollHeight; };
  clearInterval(S.timer);
  const tick = () => {
    const end = j.ended || Date.now() / 1000;
    $("#dock-time").textContent = j.started ? fmtTime(end - j.started) : "";
  };
  tick();
  if (j.status === "running") S.timer = setInterval(tick, 1000);
}

function appendLine(text) {
  const log = $("#dock-log");
  const cls = text.startsWith("$ ") ? "cmd" : /^\s*==.*==\s*$/.test(text) ? "phase" : /error|traceback|failed|exception/i.test(text) ? "err" : "";
  const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 40;
  log.append(h("span", { class: cls }, text + "\n"));
  while (log.childNodes.length > 4000) log.firstChild.remove();
  if (atBottom) log.scrollTop = log.scrollHeight;
}

boot().catch((e) => { $("#main").append(h("div", { class: "empty" }, "The app could not start: " + e.message)); });
