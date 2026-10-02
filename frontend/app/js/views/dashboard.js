// Dashboard: today's opportunities (live counts) and "Who should OG-WAN know about today?"
import { get, post } from "../api.js";
import { state, esc, icon, leadCard, bindCards, emptyState, fmtDateTime, ago, todayLong, plural, toast, busy, handleText } from "../ui.js";

export async function render(el, { navigate, refreshCounts }) {
  const d = await get("/api/dashboard");
  const s = d.stats;
  const providers = state.meta.providers;
  const live = providers.filter((p) => p.enabled && p.configured);
  const last = d.last_scan;

  if (!s.total) {
    el.innerHTML = `${head(d, last)}
      ${emptyState({
        title: "No fresh prospects yet",
        text: `Connect a discovery source or import your first batch. ${live.length ? `${esc(live.map((p) => p.label).join(", "))} ${live.length === 1 ? "is" : "are"} ready to scan now.` : ""}`,
        actions: `<a class="btn btn-primary" href="/discover" data-link>${icon.discover}Discover leads</a>
                  <a class="btn" href="/import" data-link>${icon.import}Import CSV</a>
                  ${live.length ? `<button class="btn" type="button" id="gen">${icon.drop}Generate today's drop</button>` : ""}`,
      })}`;
    wireGenerate(el, navigate);
    return;
  }

  const sinceVisit = d.previous_visit ? `since ${ago(d.previous_visit)} (${fmtDateTime(d.previous_visit)})` : "first visit: counting from now";
  el.innerHTML = `${head(d, last)}
    <section class="stats" aria-label="Today's opportunities">
      <a class="stat accent" href="/today" data-link><span class="stat-num">${s.new_today}</span><span class="stat-label">New prospects</span><span class="stat-sub">discovered today</span></a>
      <a class="stat" href="/leads?status=active&min_score=${state.meta.strategy.score_threshold}&freshness=fresh" data-link><span class="stat-num">${s.high_priority}</span><span class="stat-label">High priority</span><span class="stat-sub">score ${state.meta.strategy.score_threshold}+ · not yet contacted</span></a>
      <a class="stat" href="/leads?sort=newest" data-link><span class="stat-num">${s.new_since_visit}</span><span class="stat-label">New since last visit</span><span class="stat-sub">${esc(sinceVisit)}</span></a>
      <a class="stat" href="/follow-ups" data-link><span class="stat-num">${s.follow_up_ready}</span><span class="stat-label">Follow-up ready</span><span class="stat-sub">${s.contact_ready ? `${s.contact_ready} more contact ready` : "due now"}</span></a>
    </section>
    <div class="layout-main">
      <section aria-labelledby="q-title">
        <h2 class="question" id="q-title">Who should OG-WAN know about <em>today?</em></h2>
        <p class="question-sub">${d.prospects.length ? `Ranked by lead score and freshness. ${s.unreviewed ? `${plural(s.unreviewed, "prospect")} still unreviewed.` : ""}` : ""}</p>
        <div id="prospects">${d.prospects.length
          ? `<div class="cards boxed">${d.prospects.map((l) => leadCard(l)).join("")}</div>
             <div class="row" style="margin-top:16px"><a class="link" href="/today" data-link>Open today's drop →</a><span class="faint">·</span><a class="link" href="/leads?status=active" data-link>All open leads →</a></div>`
          : emptyState({ small: true, title: "Nothing open right now", text: "Every prospect has been reviewed. Generate a new batch to keep the pipeline fresh.",
              actions: `<button class="btn btn-primary" type="button" id="gen2">${icon.drop}Generate new batch</button>` })}</div>
      </section>
      <aside class="side">
        ${followPanel(d.follow_ups, s.follow_up_ready)}
        ${scanPanel(last, d.drop_ran_today, s)}
        ${sourcesPanel(providers)}
      </aside>
    </div>`;
  const list = el.querySelector("#prospects");
  bindCards(list, { removeWhen: ["not_fit"], onChange: () => refreshCounts() });
  wireGenerate(el, navigate);
}

function head(d, last) {
  return `<header class="page-head">
    <div>
      <div class="statusline">
        <span class="eyebrow">${esc(todayLong())}</span>
        <span class="eyebrow">Last scan <b>${last ? esc(ago(last.finished_at)) : "never"}</b></span>
      </div>
      <h1>Today's <em>opportunities</em></h1>
    </div>
    <div class="page-actions">
      <a class="btn" href="/discover" data-link>${icon.discover}Discover</a>
      <button class="btn btn-primary" type="button" id="gen-head">${icon.drop}Generate new batch</button>
    </div>
  </header>`;
}

function followPanel(items, due) {
  return `<section class="panel">
    <div class="panel-head"><h3 class="h3">Follow-up ready</h3><a class="link" href="/follow-ups" data-link>${due ? `All ${due} →` : "Open →"}</a></div>
    ${items.length ? `<div class="mini-list">${items.map((l) => `<a class="mini" href="/leads/${l.id}" data-link><div><b>${esc(l.name)}</b><span>${esc(handleText(l))} · ${esc(l.platform_label)} · contacted ${esc(ago(l.last_contacted_at))}</span></div><span class="badge b-due">Due</span></a>`).join("")}</div>`
      : `<div class="panel-body"><p class="muted small" style="margin:0">No one is waiting on a follow-up. Mark a lead contacted and GOD'S EYE schedules the next touch.</p></div>`}
  </section>`;
}

function scanPanel(last, ranToday, s) {
  const st = last?.stats || {};
  return `<section class="panel">
    <div class="panel-head"><h3 class="h3">Last scan</h3><span class="eyebrow">${last ? esc(ago(last.finished_at)) : "—"}</span></div>
    <div class="panel-body">
      ${last ? `<div class="run-stats"><div><b>${st.added ?? 0}</b><span>New</span></div><div><b>${st.seen ?? 0}</b><span>Seen</span></div><div><b>${st.filtered ?? 0}</b><span>Noise</span></div><div><b>${st.queries ?? 0}</b><span>Queries</span></div></div>
        ${(last.errors || []).length ? `<p class="small" style="color:var(--bad);margin:0 0 12px">${esc(last.errors[0])}</p>` : ""}`
        : `<p class="muted small" style="margin:0 0 14px">No scan has run yet.</p>`}
      <p class="hint" style="margin:0 0 12px">${ranToday ? "Today's drop has run." : "Today's drop hasn't run yet."} ${s.noise_filtered_today ? `${s.noise_filtered_today} candidates filtered as noise today.` : ""}</p>
      <button class="btn btn-primary" type="button" id="gen-side" style="width:100%">${icon.drop}Generate new batch</button>
    </div>
  </section>`;
}

function sourcesPanel(providers) {
  return `<section class="panel">
    <div class="panel-head"><h3 class="h3">Sources</h3><a class="link" href="/settings#sources" data-link>Manage →</a></div>
    <div class="panel-body source-list">${providers.map((p) => `<div class="source-item"><span><i class="dot ${p.enabled && p.configured ? "on" : p.configured ? "warn" : "off"}"></i>${esc(p.label)}</span><span class="eyebrow">${p.enabled && p.configured ? "Live" : p.configured ? "Paused" : "Needs key"}</span></div>`).join("")}
      <div class="source-item"><span><i class="dot on"></i>Manual import</span><span class="eyebrow">Ready</span></div>
    </div>
  </section>`;
}

function wireGenerate(el, navigate) {
  el.querySelectorAll("#gen, #gen2, #gen-head, #gen-side").forEach((btn) => btn.addEventListener("click", () => runDrop(btn, navigate)));
}

export async function runDrop(btn, navigate) {
  await busy(btn, "Scanning…", async () => {
    try {
      const res = await post("/api/drop");
      const st = res.run.stats;
      try { sessionStorage.setItem("ge:lastRun", JSON.stringify(res.run)); } catch (e) { /* summary is optional */ }
      toast(st.added ? `Fresh signals detected: ${plural(st.added, "new prospect")}.` : "Scan finished. No new prospects this time.");
      navigate("/today");
    } catch (e) {
      toast(e.message, { error: true });
    }
  });
}
