// ANALYTICS: computed from the lead database on every visit. No data = an honest empty state.
import { get } from "../api.js";
import { esc, icon, emptyState, fmtDate } from "../ui.js";

export async function render(el) {
  const a = await get("/api/analytics?days=30");
  if (a.empty) {
    el.innerHTML = `<header class="page-head"><div><span class="eyebrow">God's Eye activity</span><h1>Analytics</h1></div></header>
      ${emptyState({ title: "No activity to measure yet", text: "Analytics fill in from real leads only. Run a scan or import your first batch.",
        actions: `<a class="btn btn-primary" href="/discover" data-link>${icon.discover}Discover leads</a><a class="btn" href="/import" data-link>${icon.import}Import CSV</a>` })}`;
    return;
  }
  const t = a.totals;
  el.innerHTML = `<header class="page-head"><div><span class="eyebrow">God's Eye activity</span><h1>Analytics</h1>
      <p class="sub">${t.discovered.toLocaleString()} prospects discovered · ${t.contacted.toLocaleString()} contacted · ${t.follow_ups} follow-ups · ${t.clients} clients</p></div></header>
    <section class="kpis">
      ${kpi(t.discovered.toLocaleString(), "Prospects", "in the database")}
      ${kpi(t.contacted.toLocaleString(), "Contacted", "ever reached out")}
      ${kpi(t.follow_ups, "Follow-ups", "status follow-up")}
      ${kpi(t.clients, "Clients", "converted", true)}
      ${kpi(t.avg_score, "Avg score", "all leads")}
      ${kpi(t.conversion === null ? "—" : t.conversion + "%", "Conversion", "clients / contacted")}
    </section>
    <div class="charts">
      <section class="panel wide"><div class="panel-head"><h3 class="h3">Discovery volume · last ${a.days} days</h3>
        <div class="legend"><span><i style="background:var(--accent)"></i>Discovered</span><span><i style="background:var(--violet)"></i>Contacted</span></div></div>
        <div class="panel-body chart">${volumeChart(a.volume)}</div></section>
      <section class="panel wide"><div class="panel-head"><h3 class="h3">Pipeline</h3><span class="eyebrow">current status</span></div>
        <div class="panel-body funnel">${a.funnel.map((f) => `<div><b>${f.count}</b><span class="badge st st-${esc(f.key)}"><i></i>${esc(f.label)}</span></div>`).join("")}</div></section>
      <section class="panel"><div class="panel-head"><h3 class="h3">Leads by platform</h3></div><div class="panel-body">${bars(a.by_platform.map((p) => [p.label, p.count]), true)}</div></section>
      <section class="panel"><div class="panel-head"><h3 class="h3">Leads by genre</h3><span class="eyebrow">primary genre</span></div><div class="panel-body">${a.by_genre.length ? bars(a.by_genre.map((g) => [g.label, g.count])) : `<p class="muted small">No genres recorded yet.</p>`}${a.unknown_genre ? `<p class="hint" style="margin:12px 0 0">${a.unknown_genre} without a genre.</p>` : ""}</div></section>
      <section class="panel"><div class="panel-head"><h3 class="h3">Score distribution</h3></div><div class="panel-body">${bars(a.score_bands.map((b) => [b.label, b.count]))}</div></section>
      <section class="panel"><div class="panel-head"><h3 class="h3">Where leads came from</h3></div><div class="panel-body">${bars(a.by_source.map((s) => [s.label, s.count]))}
        <p class="hint" style="margin:12px 0 0">${t.scans} scans run · ${t.noise_filtered} candidates filtered as noise.</p></div></section>
    </div>`;
}

function kpi(num, label, sub, accent = false) {
  return `<div class="stat ${accent ? "accent" : ""}"><span class="stat-num">${esc(num)}</span><span class="stat-label">${esc(label)}</span><span class="stat-sub">${esc(sub)}</span></div>`;
}

function bars(rows, accent = false) {
  const max = Math.max(1, ...rows.map((r) => r[1]));
  return `<div class="bars">${rows.map(([label, n]) => `<div class="bar-row"><span class="lbl" title="${esc(label)}">${esc(label)}</span>
    <span class="track"><span class="fill ${accent ? "accent" : ""}" style="width:${(n / max * 100).toFixed(1)}%"></span></span><span class="v">${n}</span></div>`).join("")}</div>`;
}

function volumeChart(rows) {
  const W = 900, H = 220, P = { l: 30, r: 6, t: 10, b: 26 };
  const max = Math.max(4, ...rows.map((r) => Math.max(r.discovered, r.contacted)));
  const step = (W - P.l - P.r) / rows.length;
  const bw = Math.max(3, step * 0.36);
  const y = (v) => P.t + (H - P.t - P.b) * (1 - v / max);
  const ticks = [0, Math.round(max / 2), max];
  let svg = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Leads discovered and contacted per day">`;
  for (const t of ticks) svg += `<line class="grid" x1="${P.l}" x2="${W - P.r}" y1="${y(t)}" y2="${y(t)}"/><text x="${P.l - 6}" y="${y(t) + 3}" text-anchor="end">${t}</text>`;
  rows.forEach((r, i) => {
    const x = P.l + i * step + step / 2;
    if (r.discovered) svg += `<rect class="b1" x="${(x - bw - 1).toFixed(1)}" y="${y(r.discovered).toFixed(1)}" width="${bw.toFixed(1)}" height="${(H - P.b - y(r.discovered)).toFixed(1)}" rx="1.5"><title>${esc(r.date)}: ${r.discovered} discovered</title></rect>`;
    if (r.contacted) svg += `<rect class="b2" x="${(x + 1).toFixed(1)}" y="${y(r.contacted).toFixed(1)}" width="${bw.toFixed(1)}" height="${(H - P.b - y(r.contacted)).toFixed(1)}" rx="1.5"><title>${esc(r.date)}: ${r.contacted} contacted</title></rect>`;
    if (i % 5 === 0 || i === rows.length - 1) svg += `<text x="${x}" y="${H - 8}" text-anchor="middle">${esc(fmtDate(r.date + "T12:00:00Z", { day: "numeric", month: "short" }))}</text>`;
  });
  svg += `<line class="axis" x1="${P.l}" x2="${W - P.r}" y1="${H - P.b}" y2="${H - P.b}"/></svg>`;
  return svg;
}
