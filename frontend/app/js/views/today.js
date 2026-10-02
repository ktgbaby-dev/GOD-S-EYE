// Daily Drop: the freshest prospects discovered today, ordered by score and freshness.
import { get, post } from "../api.js";
import { state, esc, icon, leadCard, bindCards, emptyState, fmtDate, fmtTime, ago, plural, toast, busy } from "../ui.js";

export async function render(el, { navigate, refreshCounts }) {
  let lastRun = null;
  try {
    lastRun = JSON.parse(sessionStorage.getItem("ge:lastRun") || "null");
    sessionStorage.removeItem("ge:lastRun");
  } catch (e) { lastRun = null; }
  const d = await get("/api/today");
  draw(el, d, lastRun, { navigate, refreshCounts });
}

function draw(el, d, lastRun, ctx) {
  const live = state.meta.providers.filter((p) => p.enabled && p.configured);
  const dateLabel = fmtDate(new Date().toISOString(), { day: "numeric", month: "long" });
  const n = d.total_today;
  el.innerHTML = `<header class="page-head">
      <div>
        <div class="statusline"><span class="eyebrow">Daily drop</span>${d.last_scan ? `<span class="eyebrow">Last scan <b>${esc(fmtTime(d.last_scan.finished_at))}</b> · ${esc(ago(d.last_scan.finished_at))}</span>` : ""}</div>
        <h1>Today — <em>${esc(dateLabel)}</em></h1>
        <p class="sub mono" style="letter-spacing:.14em;text-transform:uppercase;font-size:13px">${n ? `${plural(n, "fresh prospect")}${d.high_priority ? ` · ${d.high_priority} high intent` : ""}${d.reviewed ? ` · ${d.reviewed} reviewed` : ""}` : "No fresh prospects yet today"}</p>
      </div>
      <div class="page-actions">
        <button class="btn btn-primary" type="button" id="refresh" ${live.length ? "" : "disabled"}>${icon.refresh}Refresh batch</button>
      </div>
    </header>
    <div id="run">${runSummary(lastRun)}</div>
    ${!live.length ? `<div class="banner neutral"><div><b>No discovery source live</b><p>Enable a source in <a class="link" href="/settings#sources" data-link>Settings</a>, or <a class="link" href="/import" data-link>import leads</a>.</p></div></div>` : ""}
    <section id="drop">${n ? `<div class="cards boxed">${d.items.map((l) => leadCard(l)).join("")}</div>
        ${d.overflow ? `<p class="hint" style="margin-top:12px">Showing the top ${d.target} (your daily target). ${d.overflow} more found today are in <a class="link" href="/leads?discovered=today" data-link>Leads</a>.</p>` : ""}
        ${d.dismissed ? `<p class="hint">${plural(d.dismissed, "prospect")} dismissed as not a fit today.</p>` : ""}`
      : emptyState({
          title: "No drop yet today",
          text: live.length ? `GOD'S EYE will scan ${esc(live.map((p) => p.label).join(", "))} using your strategy (${esc(state.meta.strategy.target_genres.slice(0, 3).join(", "))}${state.meta.strategy.target_genres.length > 3 ? "…" : ""}) and keep anything scoring ${state.meta.strategy.keep_min_score}+.`
            : "Connect a discovery source or import your first batch.",
          actions: `${live.length ? `<button class="btn btn-primary" type="button" id="gen">${icon.drop}Generate today's drop</button>` : ""}<a class="btn" href="/import" data-link>${icon.import}Import CSV</a>`,
        })}</section>
    ${d.earlier.length ? `<section style="margin-top:40px">
        <div class="spread" style="margin-bottom:14px"><h2 class="h2">Earlier this week · still unreviewed</h2><a class="link" href="/leads?status=new&discovered=7d" data-link>All ${d.earlier_total} →</a></div>
        <div class="cards boxed" id="earlier">${d.earlier.map((l) => leadCard(l)).join("")}</div></section>` : ""}
    ${batchLog(d.batches)}`;
  bindCards(el.querySelector("#drop"), { removeWhen: ["not_fit"], onChange: () => ctx.refreshCounts() });
  const earlier = el.querySelector("#earlier");
  if (earlier) bindCards(earlier, { removeWhen: ["not_fit"] });
  el.querySelectorAll("#refresh, #gen").forEach((btn) => btn.addEventListener("click", () => refresh(el, btn, ctx)));
}

async function refresh(el, btn, ctx) {
  await busy(btn, "Scanning…", async () => {
    try {
      const res = await post("/api/drop");
      draw(el, res.drop, res.run, ctx);
      ctx.refreshCounts();
      toast(res.run.stats.added ? `Fresh signals detected: ${plural(res.run.stats.added, "new prospect")}.` : "Scan finished. No new prospects this time.");
    } catch (e) {
      toast(e.message, { error: true });
    }
  });
}

function runSummary(run) {
  if (!run) return "";
  const st = run.stats || {};
  const err = (run.errors || []).length;
  if (!run.providers?.length) {
    return `<div class="banner err"><div><b>No source ran</b><p>${esc((run.notes || [])[0] || "Enable a discovery source in Settings.")}</p></div></div>`;
  }
  return `<div class="banner ${err && !st.found ? "err" : ""}"><div>
    <b>${st.added ? "Fresh signals detected" : "Scan complete"}</b>
    <p>${plural(st.added || 0, "new prospect")} · ${st.seen || 0} seen before · ${st.filtered || 0} noise filtered · ${plural(st.queries || 0, "query", "queries")} · ${run.seconds}s</p>
    ${err || (run.notes || []).length ? `<ul class="notes">${(run.errors || []).map((e) => `<li>${esc(e)}</li>`).join("")}${(run.notes || []).map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
  </div></div>`;
}

function batchLog(batches) {
  if (!batches.length) return "";
  return `<section style="margin-top:40px" class="panel">
    <div class="panel-head"><h3 class="h3">Today's scans</h3><span class="eyebrow">${batches.length}</span></div>
    <div class="table-wrap"><table class="table"><thead><tr><th>Time</th><th>Type</th><th class="num">Found</th><th class="num">New</th><th class="num">Seen</th><th class="num">Noise</th><th class="hide-sm">Notes</th></tr></thead>
    <tbody>${batches.map((b) => `<tr><td class="mono">${esc(fmtTime(b.started_at))}</td><td>${b.kind === "drop" ? "Daily drop" : "Discover scan"}</td>
      <td class="num">${b.stats.found ?? 0}</td><td class="num">${b.stats.added ?? 0}</td><td class="num">${b.stats.seen ?? 0}</td><td class="num">${b.stats.filtered ?? 0}</td>
      <td class="hide-sm small faint">${esc([...(b.errors || []), ...(b.notes || [])].join(" · ")) || "—"}</td></tr>`).join("")}</tbody></table></div>
  </section>`;
}
