// FOLLOW-UPS: who is due another touch, and who's coming up.
import { get, post } from "../api.js";
import { esc, icon, emptyState, fmtDate, ago, until, toast, safeHref, handleText, openLabel, copyText, plural } from "../ui.js";

export async function render(el, { refreshCounts }) {
  const d = await get("/api/follow-ups");
  draw(el, d);

  const onClick = async (e) => {
    const c = e.target.closest("[data-copy]");
    if (c) { copyText(c.dataset.copy, c); return; }
    const b = e.target.closest("[data-fu]");
    if (!b) return;
    const id = b.dataset.id;
    const act = b.dataset.fu;
    b.disabled = true;
    try {
      if (act === "snooze") {
        const date = new Date(Date.now() + 3 * 86400000).toISOString().slice(0, 10);
        await post(`/api/leads/${id}/status`, { status: "follow_up", follow_up_at: date });
        toast("Snoozed 3 days.");
      } else {
        await post(`/api/leads/${id}/status`, { status: act });
        toast(act === "contacted" ? "Logged. Next follow-up scheduled." : act === "client" ? "Converted. Welcome aboard." : "Closed as not a fit.");
      }
      draw(el, await get("/api/follow-ups"));
      refreshCounts();
    } catch (err) {
      b.disabled = false;
      toast(err.message, { error: true });
    }
  };
  el.addEventListener("click", onClick);
  return () => el.removeEventListener("click", onClick);
}

function row(l, due) {
  const profile = safeHref(l.profile_url);
  return `<div class="card" data-lead="${l.id}" style="grid-template-columns:minmax(0,1fr)">
    <div>
      <div class="card-top">
        <h3 class="card-name"><a href="/leads/${l.id}" data-link>${esc(l.name)}</a></h3>
        <div class="card-badges">${due ? `<span class="badge b-due">Due ${l.follow_up_at ? esc(ago(l.follow_up_at)) : "now"}</span>` : `<span class="badge">In ${esc(until(l.follow_up_at))}</span>`}</div>
      </div>
      <div class="handle-row"><span class="handle">${esc(handleText(l))}<button class="copy" type="button" data-copy="${esc(handleText(l))}" aria-label="Copy handle">${icon.copy}</button></span><span class="mono small muted">${esc(l.platform_label)}</span></div>
      <div class="meta-line"><span>Last contacted ${l.last_contacted_at ? esc(fmtDate(l.last_contacted_at)) : "—"}</span><span>Follow up ${l.follow_up_at ? esc(fmtDate(l.follow_up_at)) : "now"}</span><span>Score ${l.score}</span></div>
      ${l.notes ? `<p class="reason muted">“${esc(l.notes.slice(0, 220))}${l.notes.length > 220 ? "…" : ""}”</p>` : ""}
      <div class="card-actions">
        ${profile ? `<a class="btn btn-sm" href="${profile}" target="_blank" rel="noopener noreferrer">${icon.external}${esc(openLabel(l.platform_label))}</a>` : ""}
        <button class="btn btn-sm btn-primary" type="button" data-fu="contacted" data-id="${l.id}">Contacted again</button>
        <button class="btn btn-sm" type="button" data-fu="client" data-id="${l.id}">Client</button>
        ${due ? `<button class="btn btn-sm" type="button" data-fu="snooze" data-id="${l.id}">Snooze 3d</button>` : ""}
        <button class="btn btn-sm btn-ghost" type="button" data-fu="not_fit" data-id="${l.id}">Not a fit</button>
      </div>
    </div>
  </div>`;
}

function draw(el, d) {
  el.innerHTML = `<header class="page-head"><div><span class="eyebrow">Pipeline</span><h1>Follow-ups</h1>
      <p class="sub">${d.due.length ? `${plural(d.due.length, "artist")} waiting on another touch.` : "Nobody is waiting on you."} ${d.upcoming.length ? `${d.upcoming.length} scheduled.` : ""}</p></div></header>
    <section>
      <h2 class="h2" style="margin-bottom:14px">Ready now <span class="faint">· ${d.due.length}</span></h2>
      ${d.due.length ? `<div class="cards boxed">${d.due.map((l) => row(l, true)).join("")}</div>`
        : emptyState({ small: true, title: "Nothing due", text: "When you mark a lead contacted, GOD'S EYE schedules the next touch and lists it here on the day." })}
    </section>
    <section style="margin-top:36px">
      <h2 class="h2" style="margin-bottom:14px">Coming up <span class="faint">· ${d.upcoming.length}</span></h2>
      ${d.upcoming.length ? `<div class="cards boxed">${d.upcoming.map((l) => row(l, false)).join("")}</div>` : `<p class="muted">No follow-ups scheduled.</p>`}
    </section>
    ${d.recent_clients.length ? `<section style="margin-top:36px"><h2 class="h2" style="margin-bottom:14px">Converted this week</h2>
      <div class="panel mini-list">${d.recent_clients.map((l) => `<a class="mini" href="/leads/${l.id}" data-link><div><b>${esc(l.name)}</b><span>${esc(handleText(l))} · ${esc(l.platform_label)}</span></div><span class="badge st st-client"><i></i>Client</span></a>`).join("")}</div></section>` : ""}`;
}
