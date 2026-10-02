// GOD'S EYE shell: History-API router, navigation, global search, add-lead, sign-out.
import { get, post } from "./api.js";
import { state, icon, esc, errorBox, toast, debounce } from "./ui.js";
import { openAddLead } from "./views/addlead.js";

const NAV = [
  { path: "/dashboard", label: "Dashboard", icon: "dashboard", view: "dashboard" },
  { path: "/today", label: "Today's Drop", icon: "drop", view: "today", count: "today" },
  { path: "/discover", label: "Discover", icon: "discover", view: "discover" },
  { path: "/leads", label: "Leads", icon: "leads", view: "leads" },
  { path: "/follow-ups", label: "Follow-ups", icon: "followups", view: "followups", count: "due" },
  { path: "/analytics", label: "Analytics", icon: "analytics", view: "analytics" },
  { path: "/strategy", label: "Strategy", icon: "strategy", view: "strategy" },
  { path: "/settings", label: "Settings", icon: "settings", view: "settings" },
];
const TABS = ["/dashboard", "/today", "/leads", "/discover"];
const VIEWS = {
  dashboard: () => import("./views/dashboard.js"),
  today: () => import("./views/today.js"),
  discover: () => import("./views/discover.js"),
  leads: () => import("./views/leads.js"),
  lead: () => import("./views/lead.js"),
  followups: () => import("./views/followups.js"),
  analytics: () => import("./views/analytics.js"),
  strategy: () => import("./views/strategy.js"),
  settings: () => import("./views/settings.js"),
  import: () => import("./views/import.js"),
};
const TITLES = { dashboard: "Dashboard", today: "Today's Drop", discover: "Discover", leads: "Leads", lead: "Lead",
  followups: "Follow-ups", analytics: "Analytics", strategy: "Strategy", settings: "Settings", import: "Import" };

let counts = { today: 0, due: 0, demo: 0 };
let cleanup = null;
let renderToken = 0;

function resolve(pathname) {
  const p = pathname.replace(/\/+$/, "") || "/dashboard";
  const m = p.match(/^\/leads\/(\d+)$/);
  if (m) return { view: "lead", params: { id: m[1] }, nav: "/leads" };
  const map = { "/dashboard": "dashboard", "/today": "today", "/discover": "discover", "/leads": "leads",
    "/follow-ups": "followups", "/analytics": "analytics", "/strategy": "strategy", "/settings": "settings", "/import": "import" };
  const view = map[p] || "dashboard";
  return { view, params: {}, nav: map[p] ? (p === "/import" ? "/leads" : p) : "/dashboard" };
}

function countBadge(key) {
  const n = counts[key] || 0;
  return n ? `<span class="count ${key === "due" || key === "today" ? "hot" : ""}">${n}</span>` : "";
}

function renderNav(active) {
  document.getElementById("nav").innerHTML = NAV.map((n, i) =>
    `${i === 5 ? '<div class="nav-sep" role="separator"></div>' : ""}<a href="${n.path}" data-link class="${n.path === active ? "active" : ""}" ${n.path === active ? 'aria-current="page"' : ""}>${icon[n.icon]}<span>${esc(n.label)}</span>${n.count ? countBadge(n.count) : ""}</a>`).join("");
  const tabs = TABS.map((p) => NAV.find((n) => n.path === p));
  const moreActive = !TABS.includes(active);
  document.getElementById("tabbar").innerHTML = tabs.map((n) =>
    `<a href="${n.path}" data-link class="${n.path === active ? "active" : ""}" ${n.path === active ? 'aria-current="page"' : ""}>${icon[n.icon]}<span>${esc(n.label.replace("Today's ", ""))}</span>${n.count ? countBadge(n.count) : ""}</a>`).join("")
    + `<button type="button" data-action="more" class="${moreActive ? "active" : ""}" aria-haspopup="dialog">${icon.more}<span>More</span>${counts.due ? countBadge("due") : ""}</button>`;
}

async function refreshCounts() {
  try {
    counts = await get("/api/nav");
    renderNav(resolve(location.pathname).nav);
    const banner = document.getElementById("demo-banner");
    if (counts.demo) {
      banner.hidden = false;
      banner.innerHTML = `DEMO DATA PRESENT · ${counts.demo} fictional leads from the development seed. <a href="/settings#data" data-link>Remove in Settings</a>.`;
    } else {
      banner.hidden = true;
    }
  } catch (e) { /* counters are cosmetic */ }
}

export async function loadMeta(force = false) {
  if (!state.meta || force) {
    state.meta = await get("/api/meta");
    state.tz = state.meta.strategy.timezone || "Africa/Lagos";
  }
  return state.meta;
}

async function render() {
  const token = ++renderToken;
  const { view, params, nav } = resolve(location.pathname);
  renderNav(nav);
  if (cleanup) { try { cleanup(); } catch (e) { /* ignore */ } cleanup = null; }
  const el = document.getElementById("view");
  el.innerHTML = `<div class="skeleton" aria-hidden="true"></div>`;
  const search = document.getElementById("q");
  if (view !== "leads" && document.activeElement !== search) search.value = "";
  try {
    await loadMeta();
    const mod = await VIEWS[view]();
    if (token !== renderToken) return;
    el.innerHTML = "";
    el.style.animation = "none";
    void el.offsetWidth;
    el.style.animation = "";
    const query = Object.fromEntries(new URLSearchParams(location.search));
    cleanup = (await mod.render(el, { params, query, navigate, refreshCounts, loadMeta })) || null;
    if (token === renderToken) document.title = `${TITLES[view]} · GOD'S EYE`;
    if (location.hash) document.getElementById(location.hash.slice(1))?.scrollIntoView();
  } catch (e) {
    if (token !== renderToken || e.status === 401) return;
    el.innerHTML = errorBox(e);
    document.querySelector(".online")?.classList.toggle("down", e.status === 0);
  }
  refreshCounts();
}

export function navigate(path, { replace = false } = {}) {
  if (replace) history.replaceState(null, "", path);
  else if (path !== location.pathname + location.search) history.pushState(null, "", path);
  render();
  window.scrollTo(0, 0);
}

function openMore() {
  const root = document.getElementById("sheet-root");
  const wrap = document.createElement("div");
  const items = NAV.filter((n) => !TABS.includes(n.path));
  wrap.innerHTML = `<div class="overlay" data-close></div><div class="sheet" role="dialog" aria-label="More">
    <div class="grab"></div>
    ${items.map((n) => `<a href="${n.path}" data-link>${icon[n.icon]}<span>${esc(n.label)}</span>${n.count ? countBadge(n.count) : ""}</a>`).join("")}
    <a href="/import" data-link>${icon.import}<span>Import leads</span></a>
    <button class="item" type="button" data-action="logout">${icon.logout}<span>Sign out</span><span class="eyebrow" style="margin-left:auto">OG-WAN · Private access</span></button>
  </div>`;
  const close = () => wrap.remove();
  wrap.addEventListener("click", (e) => { if (e.target.closest("[data-close], a, [data-action]")) setTimeout(close, 0); });
  root.appendChild(wrap);
}

async function logout() {
  try { await post("/api/logout"); } catch (e) { /* fall through */ }
  location.replace("/login");
}

function wire() {
  document.addEventListener("click", (e) => {
    const a = e.target.closest("a[data-link]");
    if (a && !e.metaKey && !e.ctrlKey && !e.shiftKey && a.target !== "_blank") {
      e.preventDefault();
      navigate(a.getAttribute("href"));
      return;
    }
    const act = e.target.closest("[data-action]");
    if (!act) return;
    if (act.dataset.action === "logout") { e.preventDefault(); logout(); }
    if (act.dataset.action === "add-lead") { e.preventDefault(); openAddLead({ navigate }); }
    if (act.dataset.action === "more") { e.preventDefault(); openMore(); }
  });
  window.addEventListener("popstate", render);

  const form = document.getElementById("global-search");
  const input = document.getElementById("q");
  const live = debounce(() => {
    if (location.pathname === "/leads") {
      const q = input.value.trim();
      const params = new URLSearchParams(location.search);
      if (q) params.set("q", q); else params.delete("q");
      history.replaceState(null, "", "/leads" + (params.toString() ? "?" + params : ""));
      document.dispatchEvent(new CustomEvent("ge:search", { detail: q }));
    }
  }, 220);
  input.addEventListener("input", live);
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value.trim();
    if (location.pathname === "/leads") { live(); input.blur(); return; }
    navigate("/leads" + (q ? "?q=" + encodeURIComponent(q) : ""));
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !/INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName)) {
      e.preventDefault();
      input.focus();
      input.select();
    }
  });
  if (location.pathname === "/leads") input.value = new URLSearchParams(location.search).get("q") || "";
}

wire();
render().catch((e) => toast(e.message, { error: true }));
