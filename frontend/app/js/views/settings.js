// SETTINGS: discovery sources, automation, data and security.
import { get, put, post } from "../api.js";
import { state, esc, icon, toast, confirmBox, fmtDateTime, ago, busy } from "../ui.js";

const SETUP = {
  audius: "No key needed. Uses Audius's open API.",
  youtube: "Google Cloud console → enable “YouTube Data API v3” → Credentials → Create API key. Free quota ≈ 80 searches a day.",
  websearch: "Serper (serper.dev, Google results) or Brave Search API. Finds public Instagram and TikTok profiles through search results.",
};

export async function render(el, { loadMeta, refreshCounts }) {
  const s = await get("/api/settings");
  const enabled = new Set(state.meta.strategy.enabled_providers);
  el.innerHTML = `<header class="page-head"><div><span class="eyebrow">Private</span><h1>Settings</h1></div></header>
    <div class="stack-lg">
      <section class="panel" id="sources">
        <div class="panel-head"><h3 class="h3">Discovery sources</h3><span class="eyebrow">Keys live in environment variables</span></div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Source</th><th class="hide-sm">Platforms</th><th>Status</th><th class="hide-sm">Setup</th><th class="num">Use</th></tr></thead><tbody>
          ${s.providers.map((p) => `<tr>
            <td><b>${esc(p.label)}</b><div class="tiny faint">${esc(p.description)}</div></td>
            <td class="hide-sm mono small">${esc(p.platforms.join(", "))}</td>
            <td>${p.configured ? `<span class="badge b-verified"><i></i>${p.engine ? "Key set · " + esc(p.engine) : p.env.length ? "Key set" : "Ready"}</span>` : `<span class="badge b-stale">Needs key</span>`}</td>
            <td class="hide-sm small muted">${esc(SETUP[p.key] || "")}${p.env.length ? `<div class="mono tiny" style="margin-top:4px">${p.env.map((e) => `<code class="mono-inline">${esc(e)}</code>`).join(" or ")}</div>` : ""}</td>
            <td class="num">${p.configured ? `<button type="button" class="chip-toggle" data-prov="${p.key}" aria-pressed="${enabled.has(p.key)}" aria-label="${esc(p.label)} ${enabled.has(p.key) ? "on" : "off"}">${enabled.has(p.key) ? "On" : "Off"}</button>` : `<span class="eyebrow">Add key</span>`}</td></tr>`).join("")}
          <tr><td><b>Manual import</b><div class="tiny faint">CSV, JSON or pasted profile links. Always available.</div></td><td class="hide-sm mono small">any</td><td><span class="badge b-verified"><i></i>Ready</span></td><td class="hide-sm small muted"><a class="link" href="/import" data-link>Open import →</a></td><td></td></tr>
        </tbody></table></div>
        <div class="panel-body"><p class="hint" style="margin:0">Instagram's official API can't search other accounts, and TikTok's Research API is for academic use only, so Instagram and TikTok prospects come from public search results. To add a key: set it in <code class="mono-inline">.env</code> locally or in Vercel → Project → Settings → Environment Variables, then redeploy.</p></div>
      </section>

      <section class="panel">
        <div class="panel-head"><h3 class="h3">Daily drop automation</h3></div>
        <div class="panel-body stack">
          <dl class="kv">
            <dt>Schedule</dt><dd>${s.on_vercel ? "Vercel Cron · 05:00 UTC (06:00 Lagos) daily" : `Local server · after ${String(state.meta.strategy.drop_hour).padStart(2, "0")}:00 ${esc(state.meta.strategy.timezone)}`}</dd>
            <dt>Cron secret</dt><dd>${s.cron_configured ? `<span class="badge b-verified"><i></i>Set</span>` : `<span class="badge b-stale">Not set</span>`}</dd>
          </dl>
          <p class="hint" style="margin:0">${s.cron_configured ? "The scheduled drop runs once a day with your strategy and skips if a drop already ran." : "Set CRON_SECRET in the environment so Vercel's scheduled call is accepted. Until then, use Generate new batch."}</p>
        </div>
      </section>

      <section class="panel" id="data">
        <div class="panel-head"><h3 class="h3">Data</h3><span class="eyebrow">${esc(s.database)}</span></div>
        <div class="panel-body stack">
          <div class="row">
            <a class="btn" href="/import" data-link>${icon.import}Import leads</a>
            <a class="btn" href="/api/export.csv" download>${icon.download}Export all leads (CSV)</a>
            <a class="btn btn-ghost" href="/api/import/template.csv" download>Import template</a>
          </div>
          ${s.demo_count ? `<div class="banner" style="margin:0;border-color:rgba(231,163,94,.4);background:var(--warn-dim)"><div><b style="color:var(--warn)">Demo data present</b><p>${s.demo_count} fictional leads from the development seed are in this database.</p></div><button class="btn btn-sm" type="button" id="clear-demo">Remove demo data</button></div>`
            : `<p class="hint" style="margin:0">No demo data. Everything here came from discovery, import or manual entry.</p>`}
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h3 class="h3">Security</h3></div>
        <div class="panel-body stack">
          <dl class="kv">
            <dt>Signed in</dt><dd>${esc(fmtDateTime(s.signed_in_at))}</dd>
            <dt>Active sessions</dt><dd>${s.sessions}</dd>
            <dt>Password</dt><dd>Set by GODS_EYE_PASSWORD</dd>
          </dl>
          <p class="hint" style="margin:0">To change the password, update <code class="mono-inline">GODS_EYE_PASSWORD</code> where the app is hosted and redeploy, then sign out everywhere. Five wrong attempts lock that network out for 15 minutes.</p>
          <div class="row"><button class="btn" type="button" data-action="logout">${icon.logout}Sign out</button><button class="btn btn-danger" type="button" id="logout-all">Sign out everywhere</button></div>
        </div>
      </section>

      ${s.query_log.length ? `<section class="panel">
        <div class="panel-head"><h3 class="h3">Recent queries</h3><span class="eyebrow">rotation log</span></div>
        <div class="table-wrap"><table class="table"><thead><tr><th>Query</th><th class="num">Runs</th><th class="num">Last found</th><th class="hide-sm">Last run</th></tr></thead><tbody>
        ${s.query_log.map((q) => { let lbl = q.query; try { lbl = JSON.parse(q.query).label; } catch (e) { /* raw */ } return `<tr><td class="small">${esc(lbl)}</td><td class="num">${q.runs}</td><td class="num">${q.last_count}</td><td class="hide-sm small muted">${esc(ago(q.last_run_at))}</td></tr>`; }).join("")}
        </tbody></table></div></section>` : ""}
      <p class="eyebrow">GOD'S EYE v${esc(s.version)} · Built for OG-WAN</p>
    </div>`;

  el.querySelectorAll("[data-prov]").forEach((b) => b.addEventListener("click", async () => {
    const key = b.dataset.prov;
    const next = new Set(state.meta.strategy.enabled_providers);
    if (next.has(key)) next.delete(key); else next.add(key);
    try {
      await put("/api/strategy", { enabled_providers: [...next] });
      await loadMeta(true);
      b.setAttribute("aria-pressed", String(next.has(key)));
      b.textContent = next.has(key) ? "On" : "Off";
      toast(`${key === "websearch" ? "Web search" : key[0].toUpperCase() + key.slice(1)} ${next.has(key) ? "enabled" : "paused"}.`);
    } catch (e) { toast(e.message, { error: true }); }
  }));
  el.querySelector("#clear-demo")?.addEventListener("click", async (e) => {
    const ok = await confirmBox("Remove demo data", "Delete every lead marked as demo data? Real leads are not touched.", "Remove", true);
    if (!ok) return;
    try {
      const r = await post("/api/demo/clear");
      toast(`Removed ${r.removed} demo leads.`);
      await loadMeta(true);
      refreshCounts();
      render(el, { loadMeta, refreshCounts });
    } catch (err) { toast(err.message, { error: true }); }
  });
  el.querySelector("#logout-all").addEventListener("click", async (e) => {
    const ok = await confirmBox("Sign out everywhere", "End every GOD'S EYE session on every device, including this one?", "Sign out everywhere", true);
    if (!ok) return;
    await busy(e.target, "Signing out", async () => {
      try { await post("/api/logout-all"); } catch (err) { /* redirect anyway */ }
      location.replace("/login");
    });
  });
}
