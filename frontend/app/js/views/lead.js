// Lead detail: profile, copyable handles, the evidence behind the score, activity, private notes and actions.
import { get, post, patch, del } from "../api.js";
import { state, esc, icon, ring, freshBadge, provBadge, statusBadge, statusSelect, fmtDate, fmtDateTime, ago, until,
  copyText, toast, modal, confirmBox, busy, safeHref, handleText, openLabel, statusLabel, plural } from "../ui.js";

const PROVENANCE = {
  source: "Found by discovery",
  linked: "Listed on their profile · not verified",
  verified_link: "Linked and verified by the platform",
  manual: "Added by you",
  import: "Imported",
  demo: "Demo",
};
const ACTIVITY = { created: "Created", status: "Status", note: "Notes", edited: "Edited", seen_again: "Seen again", kept: "Kept" };

export async function render(el, { params, navigate, refreshCounts }) {
  let lead = await get(`/api/leads/${params.id}`);
  const draw = () => {
    el.innerHTML = view(lead);
    wire();
  };

  function wire() {
    el.querySelectorAll("[data-copy]").forEach((b) => b.addEventListener("click", () => copyText(b.dataset.copy, b)));
    el.querySelector("select[data-status]").addEventListener("change", (e) => setStatus(e.target.value));
    el.querySelector("#a-contacted").addEventListener("click", () => setStatus("contacted"));
    el.querySelector("#a-save").addEventListener("click", () => setStatus("watching"));
    el.querySelector("#a-contact").addEventListener("click", () => setStatus("contact"));
    el.querySelector("#a-notfit").addEventListener("click", () => setStatus("not_fit"));
    el.querySelector("#a-client").addEventListener("click", () => setStatus("client"));
    el.querySelector("#a-follow").addEventListener("click", followUp);
    el.querySelector("#a-edit").addEventListener("click", edit);
    el.querySelector("#a-delete").addEventListener("click", remove);
    const notes = el.querySelector("#notes");
    const save = el.querySelector("#save-notes");
    const state2 = el.querySelector("#notes-state");
    notes.addEventListener("input", () => { state2.textContent = "Unsaved"; save.disabled = false; });
    const doSave = async () => {
      if (save.disabled) return;
      await busy(save, "Saving", async () => {
        try {
          lead = await patch(`/api/leads/${lead.id}`, { notes: notes.value });
          state2.textContent = "Saved " + fmtDateTime(new Date().toISOString());
          el.querySelector("#timeline").innerHTML = timeline(lead.activities);
        } catch (e) { toast(e.message, { error: true }); }
      });
      save.disabled = true;
    };
    save.addEventListener("click", doSave);
    notes.addEventListener("blur", doSave);
  }

  async function setStatus(status, extra = {}) {
    if (status === lead.status && !extra.follow_up_at) return;
    const before = lead.status;
    try {
      lead = await post(`/api/leads/${lead.id}/status`, { status, ...extra });
      draw();
      refreshCounts();
      toast(`Moved to ${statusLabel(lead.status)}.`, before !== lead.status ? {
        action: "Undo", onAction: async () => { lead = await post(`/api/leads/${lead.id}/status`, { status: before }); draw(); refreshCounts(); },
      } : {});
    } catch (e) { toast(e.message, { error: true }); draw(); }
  }

  function followUp() {
    const days = state.meta.strategy.follow_up_days;
    const d = new Date(Date.now() + days * 86400000).toISOString().slice(0, 10);
    const m = modal({
      title: "Follow up",
      body: `<form id="fu" class="stack"><label class="field"><span>Follow up on</span><input class="input" type="date" name="date" value="${d}" required></label>
        <p class="hint" style="margin:0">The lead moves to FOLLOW-UP and shows as ready on that date. Pick today to flag it now.</p></form>`,
      foot: `<button class="btn btn-ghost" type="button" data-x>Cancel</button><button class="btn btn-primary" type="submit" form="fu">Schedule</button>`,
    });
    m.el.querySelector("[data-x]").addEventListener("click", m.close);
    m.el.querySelector("#fu").addEventListener("submit", async (e) => {
      e.preventDefault();
      const date = e.target.elements.date.value;
      m.close();
      await setStatus("follow_up", { follow_up_at: date });
    });
  }

  function edit() {
    const plats = state.meta.platforms.map((p) => `<option value="${p.key}" ${p.key === lead.platform ? "selected" : ""}>${esc(p.label)}</option>`).join("");
    const dateVal = (iso) => (iso ? String(iso).slice(0, 10) : "");
    const m = modal({
      title: "Edit lead",
      body: `<form id="ed" class="form-grid" novalidate>
        <label class="field"><span>Artist name</span><input class="input" name="name" value="${esc(lead.name)}"></label>
        <label class="field"><span>Handle</span><input class="input" name="handle" value="${esc(lead.handle)}" autocapitalize="off" spellcheck="false"></label>
        <label class="field"><span>Platform</span><select class="input" name="platform">${plats}</select></label>
        <label class="field"><span>Followers</span><input class="input" name="followers" value="${lead.followers ?? ""}" inputmode="decimal"></label>
        <label class="field span-2"><span>Profile URL</span><input class="input" name="profile_url" value="${esc(lead.profile_url)}" type="url"></label>
        <label class="field"><span>Genre</span><input class="input" name="genre" value="${esc(lead.genre)}"></label>
        <label class="field"><span>Location</span><input class="input" name="location" value="${esc(lead.location)}"></label>
        <label class="field"><span>Last active</span><input class="input" type="date" name="last_activity_at" value="${dateVal(lead.last_activity_at)}"></label>
        <label class="field"><span>Latest release</span><input class="input" type="date" name="last_release_at" value="${dateVal(lead.last_release_at)}"></label>
        <label class="field span-2"><span>Public bio / caption</span><textarea class="input" name="bio" rows="4">${esc(lead.bio)}</textarea></label>
        <p class="form-error span-2" id="ed-err" role="alert"></p>
      </form>`,
      foot: `<button class="btn btn-ghost" type="button" data-x>Cancel</button><button class="btn btn-primary" type="submit" form="ed" id="ed-save">Save changes</button>`,
    });
    m.el.querySelector("[data-x]").addEventListener("click", m.close);
    m.el.querySelector("#ed").addEventListener("submit", async (e) => {
      e.preventDefault();
      const data = Object.fromEntries(new FormData(e.target).entries());
      for (const k of ["last_activity_at", "last_release_at"]) if (!data[k]) data[k] = null;
      await busy(m.el.querySelector("#ed-save"), "Saving", async () => {
        try {
          lead = await patch(`/api/leads/${lead.id}`, data);
          m.close();
          draw();
          toast(`Saved · score ${lead.score}`);
        } catch (ex) { m.el.querySelector("#ed-err").textContent = ex.message; }
      });
    });
  }

  async function remove() {
    const ok = await confirmBox("Delete lead", `Permanently delete ${lead.name} (${handleText(lead)}) and its history from GOD'S EYE? If discovery finds them again they come back as a new lead. To just dismiss them, use Not a fit.`, "Delete", true);
    if (!ok) return;
    try {
      await del(`/api/leads/${lead.id}`);
      toast("Lead deleted.");
      refreshCounts();
      navigate("/leads");
    } catch (e) { toast(e.message, { error: true }); }
  }

  draw();
}

function view(l) {
  const bd = l.score_breakdown || {};
  const items = bd.items || [];
  const positives = items.filter((i) => i.points > 0);
  const negatives = items.filter((i) => i.points < 0);
  const profile = safeHref(l.profile_url);
  const others = (l.handles || []).filter((h) => !(h.platform === l.platform && h.handle.toLowerCase() === l.handle.toLowerCase()));
  return `<a class="link" href="/leads" data-link>← Leads</a>
  <header class="detail-head" style="margin-top:16px">
    <div>
      <div class="row">${freshBadge(l)}${provBadge(l)}${statusBadge(l.status)}${l.follow_up_due ? `<span class="badge b-due">Follow-up ready</span>` : ""}</div>
      <h1 class="detail-name">${esc(l.name)}</h1>
      <div class="row">
        <span class="handle handle-xl">${esc(handleText(l))}<button class="copy" type="button" data-copy="${esc(handleText(l))}" aria-label="Copy handle" title="Copy handle">${icon.copy}</button></span>
        <span class="mono muted">${esc(l.platform_label)}</span>
      </div>
      <div class="row" style="margin-top:14px">
        <button class="btn" type="button" data-copy="${esc(handleText(l))}">${icon.copy}Copy handle</button>
        ${profile ? `<a class="btn btn-primary" href="${profile}" target="_blank" rel="noopener noreferrer">${icon.external}${esc(openLabel(l.platform_label))}</a>` : ""}
      </div>
    </div>
    <div class="row">${statusSelect(l)}</div>
  </header>

  <div class="layout-detail">
    <div class="stack-lg">
      <section class="panel">
        <div class="panel-head"><h3 class="h3">Profile</h3><button class="btn btn-sm btn-ghost" type="button" id="a-edit">Edit</button></div>
        <div class="panel-body stack">
          <dl class="kv">
            <dt>Profile URL</dt><dd>${profile ? `<a href="${profile}" target="_blank" rel="noopener noreferrer" class="mono small">${esc(l.profile_url.replace(/^https?:\/\/(www\.)?/, ""))}</a>` : "—"}</dd>
            <dt>Location</dt><dd>${esc(l.location || "Unknown")}</dd>
            <dt>Genre</dt><dd>${esc(l.genre || "Unknown")}</dd>
            <dt>Audience</dt><dd>${l.followers_label ? `${esc(l.followers_label)} ${l.platform === "youtube" ? "subscribers" : "followers"}` : "Unknown"}</dd>
            <dt>Source</dt><dd>${safeHref(l.source_url) ? `<a href="${safeHref(l.source_url)}" target="_blank" rel="noopener noreferrer">${esc(l.source)}</a>` : esc(l.source)}</dd>
          </dl>
          ${l.bio ? `<div><span class="label">Public bio</span><p class="bio" style="margin-top:8px">${esc(l.bio)}</p></div>` : ""}
        </div>
      </section>

      ${others.length ? `<section class="panel">
        <div class="panel-head"><h3 class="h3">Other handles</h3><span class="eyebrow">${others.length}</span></div>
        <div class="mini-list">${others.map((h) => `<div class="mini"><div><b class="mono">@${esc(h.handle)}</b><span>${esc(h.platform_label)} · ${esc(PROVENANCE[h.provenance] || h.provenance)}${h.source ? " · " + esc(h.source) : ""}</span></div>
          <div class="row"><button class="copy" type="button" data-copy="@${esc(h.handle)}" aria-label="Copy @${esc(h.handle)}">${icon.copy}</button>${safeHref(h.url) ? `<a class="btn btn-sm" href="${safeHref(h.url)}" target="_blank" rel="noopener noreferrer">${esc(openLabel(h.platform_label))}</a>` : ""}</div></div>`).join("")}</div>
      </section>` : ""}

      <section class="panel">
        <div class="panel-head"><h3 class="h3">Why GOD'S EYE found them</h3><span class="eyebrow">${plural(positives.length, "signal")}</span></div>
        <div class="panel-body">
          ${items.length ? `<ul class="checklist">
            ${positives.map((i) => check(i, "")).join("")}
            ${negatives.map((i) => check(i, "neg")).join("")}
            ${(bd.unknown || []).map((u) => `<li><span class="tick unk">?</span><div><span class="lbl muted">${esc(u)}: unknown</span><span class="ev">No public data yet. Unknown earns no points.</span></div><span></span></li>`).join("")}
          </ul>` : `<p class="muted" style="margin:0">No signals detected yet. Add their public bio, a release date or follower count (Edit) and GOD'S EYE will rescore.</p>`}
          <p class="hint" style="margin:16px 0 0">${esc(l.reason)}</p>
        </div>
      </section>

      ${(l.evidence || []).length ? `<section class="panel">
        <div class="panel-head"><h3 class="h3">Evidence</h3><span class="eyebrow">${l.evidence.length} public source${l.evidence.length === 1 ? "" : "s"}</span></div>
        <div class="panel-body evidence">${l.evidence.map((e) => {
          const href = safeHref(e.url);
          const inner = `<span class="m">${esc(e.label || e.kind)}${e.date ? " · " + esc(fmtDate(e.date)) : ""}</span>${e.title ? `<span class="t">${esc(e.title)}</span>` : ""}${e.text ? `<span class="s">${esc(e.text)}</span>` : ""}`;
          return href ? `<a class="ev-item" href="${href}" target="_blank" rel="noopener noreferrer">${inner}</a>` : `<div class="ev-item" style="padding:12px 14px;border:1px solid var(--line);border-radius:8px">${inner}</div>`;
        }).join("")}</div>
      </section>` : ""}
    </div>

    <aside class="stack-lg">
      <section class="panel">
        <div class="panel-head"><h3 class="h3">Lead score</h3><span class="eyebrow">${esc(bd.scored_at ? "scored " + ago(bd.scored_at) : "")}</span></div>
        <div class="panel-body stack">
          <div style="display:grid;place-items:center;padding:6px 0 4px">${ring(l.score, { large: true })}</div>
          <table class="breakdown"><tbody>
            ${items.map((i) => `<tr><td class="g">${esc(i.group)}</td><td>${esc(i.label)}</td><td class="p ${i.points < 0 ? "neg" : ""}">${i.points > 0 ? "+" : ""}${i.points}</td></tr>`).join("") || `<tr><td colspan="3" class="faint">No signals yet</td></tr>`}
          </tbody><tfoot><tr><td></td><td>${bd.raw > 100 ? `Sum ${bd.raw}, capped at 100` : bd.raw < 0 ? `Sum ${bd.raw}, floored at 0` : "Total"}</td><td class="p">${l.score}</td></tr></tfoot></table>
          <p class="hint" style="margin:0">Points per signal are set on the <a class="link" href="/strategy#weights" data-link>Strategy</a> page.</p>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h3 class="h3">Actions</h3></div>
        <div class="panel-body actions-grid">
          ${profile ? `<a class="btn full" href="${profile}" target="_blank" rel="noopener noreferrer">${icon.external}Open profile</a>` : ""}
          <button class="btn btn-primary full" type="button" id="a-contacted">Mark contacted</button>
          <button class="btn" type="button" id="a-follow">Follow up</button>
          <button class="btn" type="button" id="a-save">Save</button>
          <button class="btn" type="button" id="a-contact">Contact ready</button>
          <button class="btn" type="button" id="a-client">Client</button>
          <button class="btn btn-ghost full" type="button" id="a-notfit">Not a fit</button>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h3 class="h3">Activity</h3></div>
        <div class="panel-body">
          <dl class="kv">
            <dt>Discovered</dt><dd>${esc(fmtDateTime(l.discovered_at))}</dd>
            <dt>Last seen</dt><dd>${esc(ago(l.last_seen_at))}${l.seen_count > 1 ? ` · ${l.seen_count}×` : ""}</dd>
            <dt>Last observed activity</dt><dd>${l.last_activity_at ? esc(fmtDate(l.last_activity_at)) + ` <span class="faint">(${esc(ago(l.last_activity_at))})</span>` : "Unknown"}</dd>
            <dt>Latest release</dt><dd>${l.last_release_at ? esc(fmtDate(l.last_release_at)) : "Unknown"}</dd>
            <dt>Last contacted</dt><dd>${l.last_contacted_at ? esc(fmtDateTime(l.last_contacted_at)) : "Never"}</dd>
            <dt>Follow-up</dt><dd>${l.follow_up_at ? esc(fmtDate(l.follow_up_at)) + (l.follow_up_due ? ` <span class="badge b-due">Due</span>` : ` <span class="faint">in ${esc(until(l.follow_up_at))}</span>`) : "—"}</dd>
          </dl>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h3 class="h3">Notes</h3><span class="eyebrow" id="notes-state">Private</span></div>
        <div class="panel-body stack">
          <label class="sr-only" for="notes">Private notes</label>
          <textarea class="input" id="notes" rows="6" placeholder="Only you see this. What you said, what they replied, what to pitch next.">${esc(l.notes)}</textarea>
          <div class="spread"><span class="hint">Saves when you click away.</span><button class="btn btn-sm" type="button" id="save-notes" disabled>Save notes</button></div>
        </div>
      </section>

      <section class="panel">
        <div class="panel-head"><h3 class="h3">Timeline</h3></div>
        <div class="panel-body"><ul class="timeline" id="timeline">${timeline(l.activities)}</ul></div>
      </section>
      <button class="btn btn-ghost btn-danger btn-sm" type="button" id="a-delete" style="justify-self:start">Delete lead</button>
    </aside>
  </div>`;
}

function check(i, cls) {
  const ev = i.url && safeHref(i.url) ? `<a href="${safeHref(i.url)}" target="_blank" rel="noopener noreferrer">${esc(i.evidence)}</a>` : esc(i.evidence);
  return `<li><span class="tick ${cls}">${cls ? "!" : "✓"}</span><div><span class="lbl">${esc(i.label)}</span><span class="ev">${ev}</span></div><span class="pts ${cls}">${i.points > 0 ? "+" : ""}${i.points}</span></li>`;
}

function timeline(acts) {
  return (acts || []).map((a) => `<li><time>${esc(fmtDateTime(a.created_at))}</time>${esc(ACTIVITY[a.kind] || a.kind)}${a.detail ? ` · <span class="muted">${esc(a.detail)}</span>` : ""}</li>`).join("") || `<li class="faint">No activity yet.</li>`;
}
