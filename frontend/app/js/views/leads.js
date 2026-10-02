// LEADS: the whole database with fast server-side search, filters and a live "SHOW N PROSPECTS" count.
import { get, qs } from "../api.js";
import { state, esc, icon, leadCard, bindCards, emptyState, debounce, plural, statusLabel } from "../ui.js";

const FIELDS = ["platform", "genre", "location", "min_score", "status", "discovered", "activity", "followers", "freshness", "provenance", "sort"];
const PAGE = 30;

export async function render(el, { query, navigate }) {
  const m = state.meta;
  let filters = Object.fromEntries(Object.entries(query).filter(([k, v]) => (FIELDS.includes(k) || k === "q") && v));
  let offset = 0;
  const opt = (pairs, sel) => pairs.map(([v, l]) => `<option value="${esc(v)}" ${String(v) === String(sel ?? "") ? "selected" : ""}>${esc(l)}</option>`).join("");
  const platforms = [["", "Any platform"], ...m.platforms.filter((p) => m.facets.platforms.includes(p.key) || m.strategy.target_platforms.includes(p.key)).map((p) => [p.key, p.label])];
  const genres = [["", "Any genre"], ...[...new Set([...m.strategy.target_genres, ...m.facets.genres])].map((g) => [g, g])];
  const locations = [["", "Anywhere"], ...[...new Set([...m.strategy.target_locations, ...m.facets.locations])].map((g) => [g, g])];
  const statuses = [["", "Any status"], ["active", "Open (new · watching · contact)"], ...m.statuses.map((s) => [s.key, s.label])];

  el.innerHTML = `<header class="page-head">
      <div><span class="eyebrow">Lead database</span><h1>Leads</h1></div>
      <div class="page-actions">
        <a class="btn" href="/import" data-link>${icon.import}Import</a>
        <a class="btn" id="export" href="/api/export.csv" download>${icon.download}Export CSV</a>
        <button class="btn btn-primary" type="button" data-action="add-lead">${icon.plus}Add lead</button>
      </div>
    </header>
    <div class="toolbar">
      <button class="btn" type="button" id="toggle-filters" aria-expanded="false" aria-controls="filters">${icon.settings}Filter<span id="fcount" class="mono"></span></button>
      <label class="sr-only" for="quick-sort">Sort</label>
      <select class="input" id="quick-sort" style="width:auto;min-height:40px">${opt([["score", "Sort: lead score"], ["newest", "Sort: newest"], ["activity", "Sort: recent activity"], ["followers", "Sort: following"], ["name", "Sort: name"]], filters.sort || "score")}</select>
      <span class="grow"></span><span class="result-count" id="count"></span>
    </div>
    <form id="filters" class="panel" novalidate hidden>
      <div class="filters">
        <label class="field"><span>Platform</span><select class="input" name="platform">${opt(platforms, filters.platform)}</select></label>
        <label class="field"><span>Genre</span><select class="input" name="genre">${opt(genres, filters.genre)}</select></label>
        <label class="field"><span>Location</span><select class="input" name="location">${opt(locations, filters.location)}</select></label>
        <label class="field"><span>Lead score</span><select class="input" name="min_score">${opt([["", "Any score"], ["40", "40+"], ["50", "50+"], ["60", "60+"], ["70", "70+"], ["80", "80+"], ["90", "90+"]], filters.min_score)}</select></label>
        <label class="field"><span>Status</span><select class="input" name="status">${opt(statuses, filters.status)}</select></label>
        <label class="field"><span>Discovered</span><select class="input" name="discovered">${opt([["", "Any time"], ["today", "Today"], ["7d", "Last 7 days"], ["30d", "Last 30 days"], ["older", "Older than 30 days"]], filters.discovered)}</select></label>
        <label class="field"><span>Activity</span><select class="input" name="activity">${opt([["", "Any activity"], ["7d", "Active in 7 days"], ["30d", "Active in 30 days"], ["90d", "Active in 90 days"], ["inactive", "Quiet 90+ days"], ["unknown", "Unknown"]], filters.activity)}</select></label>
        <label class="field"><span>Following</span><select class="input" name="followers">${opt([["", "Any size"], ["lt1k", "Under 1K"], ["1k-10k", "1K–10K"], ["10k-50k", "10K–50K"], ["50k-250k", "50K–250K"], ["250k+", "250K+"], ["unknown", "Unknown"]], filters.followers)}</select></label>
        <label class="field"><span>Freshness</span><select class="input" name="freshness">${opt([["", "Any"], ["new_today", "New today"], ["seen_before", "Seen before"], ["fresh", "Not stale"], ["stale", "Stale"]], filters.freshness)}</select></label>
        <label class="field"><span>Origin</span><select class="input" name="provenance">${opt([["", "Any origin"], ["verified", "Source verified"], ["manual", "Manual entry"], ["import", "Imported"]], filters.provenance)}</select></label>
        <input type="hidden" name="sort" value="${esc(filters.sort || "score")}">
      </div>
      <div class="filter-foot">
        <button class="btn btn-ghost btn-sm" type="button" id="reset">Clear filters</button>
        <button class="btn btn-primary" type="submit" id="show">Show prospects</button>
      </div>
    </form>
    <div class="toolbar" style="margin-top:14px" id="chips-bar"><span id="chips" class="row"></span></div>
    <section id="list"></section>`;

  const form = el.querySelector("#filters");
  const toggle = el.querySelector("#toggle-filters");
  const setOpen = (open) => {
    form.hidden = !open;
    toggle.setAttribute("aria-expanded", String(open));
  };
  toggle.addEventListener("click", () => setOpen(form.hidden));
  el.querySelector("#quick-sort").addEventListener("change", (e) => {
    form.elements.sort.value = e.target.value;
    filters = formFilters();
    syncUrl();
    load();
  });
  const list = el.querySelector("#list");
  const showBtn = el.querySelector("#show");
  bindCards(list, {});

  const formFilters = () => {
    const f = {};
    for (const k of FIELDS) if (form.elements[k] && form.elements[k].value) f[k] = form.elements[k].value;
    if (filters.q) f.q = filters.q;
    if (f.sort === "score") delete f.sort;
    return f;
  };

  const liveCount = debounce(async () => {
    try {
      const r = await get("/api/leads/count" + qs(formFilters()));
      showBtn.textContent = `Show ${plural(r.total, "prospect")}`;
    } catch (e) { /* ignore */ }
  }, 150);
  form.addEventListener("change", liveCount);

  async function load(append = false) {
    if (!append) {
      offset = 0;
      list.innerHTML = `<div class="skeleton"></div>`;
    }
    const data = await get("/api/leads" + qs({ ...filters, limit: PAGE, offset }));
    const total = data.total;
    el.querySelector("#count").textContent = `${plural(total, "prospect")}${filters.q ? ` matching “${filters.q}”` : ""}`;
    showBtn.textContent = `Show ${plural(total, "prospect")}`;
    el.querySelector("#export").setAttribute("href", "/api/export.csv" + qs(filters));
    renderChips();
    const html = data.items.map((l) => leadCard(l)).join("");
    if (!append) {
      if (!total) {
        list.innerHTML = m.total_leads
          ? emptyState({ small: true, title: "No prospects match", text: "Loosen a filter or clear the search.", actions: `<button class="btn" type="button" id="clear2">Clear filters</button>` })
          : emptyState({ title: "No leads yet", text: "Connect a discovery source or import your first batch.", actions: `<a class="btn btn-primary" href="/discover" data-link>${icon.discover}Discover leads</a><a class="btn" href="/import" data-link>${icon.import}Import CSV</a>` });
        list.querySelector("#clear2")?.addEventListener("click", clearAll);
        return;
      }
      list.innerHTML = `<div class="cards boxed" id="cards">${html}</div><div class="load-more" id="more"></div>`;
    } else {
      list.querySelector("#cards").insertAdjacentHTML("beforeend", html);
    }
    offset += data.items.length;
    const more = list.querySelector("#more");
    more.innerHTML = offset < total ? `<button class="btn" type="button">Load ${Math.min(PAGE, total - offset)} more</button>` : "";
    more.querySelector("button")?.addEventListener("click", () => load(true));
  }

  function syncUrl() {
    history.replaceState(null, "", "/leads" + qs(filters));
  }

  function renderChips() {
    const names = { platform: "Platform", genre: "Genre", location: "Location", min_score: "Score", status: "Status", discovered: "Discovered", activity: "Activity", followers: "Following", freshness: "Freshness", provenance: "Origin" };
    const val = (k, v) => k === "status" ? (v === "active" ? "Open" : statusLabel(v)) : k === "min_score" ? v + "+" : form.elements[k]?.selectedOptions?.[0]?.textContent || v;
    const active = Object.keys(filters).filter((k) => names[k]).length;
    el.querySelector("#fcount").textContent = active ? ` · ${active}` : "";
    el.querySelector("#chips-bar").hidden = !active;
    el.querySelector("#chips").innerHTML = Object.entries(filters).filter(([k]) => names[k])
      .map(([k, v]) => `<span class="filter-chip">${esc(names[k])}: ${esc(val(k, v))}<button type="button" data-unset="${k}" aria-label="Remove ${esc(names[k])} filter">×</button></span>`).join("");
  }

  function clearAll() {
    const q = filters.q;
    filters = q ? { q } : {};
    form.reset();
    for (const k of FIELDS) if (form.elements[k]) form.elements[k].value = k === "sort" ? "score" : "";
    el.querySelector("#quick-sort").value = "score";
    syncUrl();
    load();
  }

  el.querySelector("#chips").addEventListener("click", (e) => {
    const b = e.target.closest("[data-unset]");
    if (!b) return;
    delete filters[b.dataset.unset];
    if (form.elements[b.dataset.unset]) form.elements[b.dataset.unset].value = "";
    syncUrl();
    load();
  });
  form.addEventListener("submit", (e) => {
    e.preventDefault();
    filters = formFilters();
    syncUrl();
    load();
    setOpen(false);
  });
  el.querySelector("#reset").addEventListener("click", clearAll);

  const onSearch = (e) => {
    filters = { ...formFilters(), q: e.detail };
    if (!e.detail) delete filters.q;
    load();
  };
  document.addEventListener("ge:search", onSearch);
  const input = document.getElementById("q");
  if (filters.q && input) input.value = filters.q;
  await load();
  return () => document.removeEventListener("ge:search", onSearch);
}
