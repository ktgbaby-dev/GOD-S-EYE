// Shared UI: escaping, formatting, icons, score rings, badges, lead cards, toasts, modals, clipboard.
import { post } from "./api.js";

export const state = { meta: null, tz: "Africa/Lagos" };

export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

// Only http(s) links are ever rendered as hrefs.
export function safeHref(u) {
  return /^https?:\/\//i.test(String(u || "")) ? esc(u) : "";
}

// ------------------------------------------------------------------ icons (stroke, currentColor)
const S = (d, extra = "") => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" ${extra}>${d}</svg>`;
export const icon = {
  dashboard: S('<rect x="3.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="3.5" width="7" height="7" rx="1.5"/><rect x="3.5" y="13.5" width="7" height="7" rx="1.5"/><rect x="13.5" y="13.5" width="7" height="7" rx="1.5"/>'),
  drop: S('<path d="M12 3.5l2.3 5.2 5.2 2.3-5.2 2.3L12 18.5l-2.3-5.2L4.5 11l5.2-2.3z"/><path d="M19 17v4M17 19h4"/>'),
  discover: S('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 12l5.5-5.5"/><circle cx="12" cy="12" r="0.8" fill="currentColor"/>'),
  leads: S('<circle cx="9" cy="8.5" r="3.5"/><path d="M2.8 19.5c.8-3.3 3.3-5 6.2-5s5.4 1.7 6.2 5"/><path d="M15.5 5.3a3.5 3.5 0 010 6.4M18.2 14.8c1.5.8 2.6 2.4 3 4.7"/>'),
  followups: S('<path d="M20 11.5A8 8 0 106.3 17.2"/><path d="M20 4.5v7h-7"/><path d="M12 8v4.5l3 2"/>'),
  analytics: S('<path d="M4 20V10M10 20V4M16 20v-7M22 20H2"/>'),
  strategy: S('<circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><path d="M12 1.5v4M12 18.5v4M1.5 12h4M18.5 12h4"/>'),
  settings: S('<path d="M4 7h10M18 7h2M4 17h4M12 17h8"/><circle cx="16" cy="7" r="2"/><circle cx="10" cy="17" r="2"/>'),
  import: S('<path d="M12 3.5v11M7.5 10l4.5 4.5 4.5-4.5"/><path d="M4 16.5v2a2 2 0 002 2h12a2 2 0 002-2v-2"/>'),
  more: S('<circle cx="5" cy="12" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="19" cy="12" r="1.2" fill="currentColor"/>'),
  copy: S('<rect x="8.5" y="8.5" width="11" height="11" rx="2"/><path d="M15.5 8.5V6a1.5 1.5 0 00-1.5-1.5H6A1.5 1.5 0 004.5 6v8A1.5 1.5 0 006 15.5h2.5"/>'),
  check: S('<path d="M5 12.5l4.5 4.5L19 7.5"/>', 'stroke-width="2"'),
  external: S('<path d="M14 4.5h5.5V10M19.5 4.5L11 13"/><path d="M18 14v4a1.5 1.5 0 01-1.5 1.5h-11A1.5 1.5 0 014 18V7.5A1.5 1.5 0 015.5 6H10"/>'),
  plus: S('<path d="M12 5v14M5 12h14"/>', 'stroke-width="2"'),
  logout: S('<path d="M14 4.5h4a1.5 1.5 0 011.5 1.5v12a1.5 1.5 0 01-1.5 1.5h-4"/><path d="M10 16l-4-4 4-4M6 12h10"/>'),
  scan: S('<path d="M4 8V5.5A1.5 1.5 0 015.5 4H8M16 4h2.5A1.5 1.5 0 0120 5.5V8M20 16v2.5a1.5 1.5 0 01-1.5 1.5H16M8 20H5.5A1.5 1.5 0 014 18.5V16M4 12h16"/>'),
  refresh: S('<path d="M19.5 12a7.5 7.5 0 11-2.2-5.3L19.5 9"/><path d="M19.5 4v5h-5"/>'),
  download: S('<path d="M12 4v11M7.5 10.5L12 15l4.5-4.5M4.5 19.5h15"/>'),
};

export const MARK = `<svg class="mark" viewBox="0 0 64 64" aria-hidden="true"><path d="M5 32C17 13 47 13 59 32C47 51 17 51 5 32Z" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/><circle class="iris" cx="32" cy="32" r="11.5" fill="none" stroke-width="1.6"/><circle class="groove" cx="32" cy="32" r="7" fill="none" stroke-width="1"/><circle class="pupil" cx="32" cy="32" r="2.6"/></svg>`;

// ------------------------------------------------------------------ formatting
function dt(iso) {
  if (!iso) return null;
  const d = new Date(iso);
  return isNaN(d) ? null : d;
}

export function fmtDate(iso, opts = { day: "numeric", month: "short", year: "numeric" }) {
  const d = dt(iso);
  if (!d) return "—";
  try { return new Intl.DateTimeFormat("en-GB", { timeZone: state.tz, ...opts }).format(d); }
  catch (e) { return d.toDateString(); }
}

export function fmtDateTime(iso) {
  return fmtDate(iso, { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

export function fmtTime(iso) {
  return fmtDate(iso, { hour: "2-digit", minute: "2-digit" });
}

export function ago(iso) {
  const d = dt(iso);
  if (!d) return "—";
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < -60) return "in " + until(iso);
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  if (s < 86400 * 2) return "yesterday";
  if (s < 86400 * 30) return `${Math.floor(s / 86400)}d ago`;
  if (s < 86400 * 365) return `${Math.floor(s / (86400 * 30))}mo ago`;
  return `${Math.floor(s / (86400 * 365))}y ago`;
}

export function until(iso) {
  const d = dt(iso);
  if (!d) return "—";
  const s = (d.getTime() - Date.now()) / 1000;
  if (s <= 0) return "now";
  if (s < 3600) return `${Math.ceil(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

export function todayLong() {
  try {
    return new Intl.DateTimeFormat("en-GB", { timeZone: state.tz, weekday: "long", day: "numeric", month: "long" }).format(new Date());
  } catch (e) { return new Date().toDateString(); }
}

export function plural(n, one, many) { return `${n} ${n === 1 ? one : (many || one + "s")}`; }

export function statusLabel(key) {
  const s = (state.meta?.statuses || []).find((x) => x.key === key);
  return s ? s.label : key;
}

export function handleText(lead) {
  const h = lead.handle || "";
  return /^UC[\w-]{20,}$/.test(h) ? h : "@" + h;
}

export function openLabel(platformLabel) {
  return platformLabel && platformLabel !== "Other" ? `Open ${platformLabel}` : "Open profile";
}

// ------------------------------------------------------------------ score
export function tier(score) {
  const th = state.meta?.strategy?.score_threshold ?? 70;
  if (score >= th) return { cls: "hi", label: "High intent" };
  if (score >= 50) return { cls: "", label: "Worth a look" };
  return { cls: "lo", label: "Low signal" };
}

export function ring(score, { large = false, withTier = true } = {}) {
  const r = 24, c = 2 * Math.PI * r;
  const off = c * (1 - Math.max(0, Math.min(100, score)) / 100);
  const t = tier(score);
  return `<div class="ring ${t.cls} ${large ? "ring-lg" : ""}" role="img" aria-label="Lead score ${score} of 100">
    <svg viewBox="0 0 56 56"><circle class="track" cx="28" cy="28" r="${r}" fill="none" stroke-width="${large ? 2.5 : 3.5}"/>
    <circle class="val" cx="28" cy="28" r="${r}" fill="none" stroke-width="${large ? 2.5 : 3.5}" stroke-dasharray="${c.toFixed(2)}" stroke-dashoffset="${off.toFixed(2)}"/></svg>
    <b>${score}${large ? "<small>/ 100</small>" : ""}</b></div>${withTier && !large ? `<span class="ring-tier">${t.label}</span>` : ""}`;
}

// ------------------------------------------------------------------ badges
export function freshBadge(lead) {
  if (lead.freshness === "new_today") return `<span class="badge b-fresh"><i></i>New today</span>`;
  if (lead.freshness === "stale") return `<span class="badge b-stale">Stale</span>`;
  return `<span class="badge b-seen">Seen before</span>`;
}

export function provBadge(lead) {
  if (lead.is_demo || lead.provenance === "demo") return `<span class="badge b-demo">Demo data</span>`;
  if (lead.provenance === "verified") return `<span class="badge b-verified" title="Found in a real public source: ${esc(lead.source)}">Source verified</span>`;
  if (lead.provenance === "import") return `<span class="badge b-import">Imported</span>`;
  return `<span class="badge b-manual">Manual entry</span>`;
}

export function statusBadge(status) {
  return `<span class="badge st st-${esc(status)}"><i></i>${esc(statusLabel(status))}</span>`;
}

export function statusSelect(lead) {
  const opts = (state.meta?.statuses || []).map((s) => `<option value="${s.key}" ${s.key === lead.status ? "selected" : ""}>${esc(s.label)}</option>`).join("");
  return `<label class="status-select st-${esc(lead.status)}" style="--c: var(--${statusVar(lead.status)})">
    <span class="sr-only">Status</span><select data-status="${lead.id}" data-current="${esc(lead.status)}" aria-label="Status for ${esc(lead.name)}">${opts}</select></label>`;
}

function statusVar(s) {
  return { new: "text", watching: "info", contact: "accent", contacted: "violet", follow_up: "warn", client: "good", not_fit: "text-3" }[s] || "text-2";
}

// ------------------------------------------------------------------ lead card
export function leadCard(lead, opts = {}) {
  const meta = [
    `<span>${esc(lead.platform_label)}</span>`,
    lead.genre ? `<span>${esc(lead.genre)}</span>` : "",
    lead.location ? `<span>${esc(lead.location)}</span>` : "",
    lead.followers_label ? `<span>${esc(lead.followers_label)} followers</span>` : `<span class="k">Audience unknown</span>`,
  ].join("");
  const reason = esc(lead.reason || "").replace(/Caution:([^.]*\.)/, '<span class="caution">Caution:$1</span>');
  const profile = safeHref(lead.profile_url);
  const source = lead.source_url && safeHref(lead.source_url)
    ? `<a href="${safeHref(lead.source_url)}" target="_blank" rel="noopener noreferrer">${esc(lead.source)}</a>` : esc(lead.source);
  const due = lead.follow_up_due ? `<span class="badge b-due">Follow-up ready</span>` : "";
  return `<article class="card" data-lead="${lead.id}">
    <div>${ring(lead.score)}</div>
    <div>
      <div class="card-top">
        <h3 class="card-name"><a href="/leads/${lead.id}" data-link>${esc(lead.name)}</a></h3>
        <div class="card-badges">${due}${freshBadge(lead)}${provBadge(lead)}</div>
      </div>
      <div class="handle-row">
        <span class="handle">${esc(handleText(lead))}<button class="copy" type="button" data-copy="${esc(handleText(lead))}" aria-label="Copy handle ${esc(handleText(lead))}" title="Copy handle">${icon.copy}</button></span>
      </div>
      <div class="meta-line">${meta}</div>
      <p class="reason">${reason}</p>
      <div class="source-line">via ${source} · found ${esc(ago(lead.discovered_at))}${lead.seen_count > 1 ? ` · seen ${lead.seen_count}×` : ""}</div>
      <div class="card-actions">
        ${profile ? `<a class="btn btn-sm" href="${profile}" target="_blank" rel="noopener noreferrer">${icon.external}${esc(openLabel(lead.platform_label))}</a>` : ""}
        ${opts.compact ? "" : (lead.status === "new" ? `<button class="btn btn-sm" type="button" data-act="watching" data-id="${lead.id}">Save lead</button>` : "")}
        ${opts.compact || lead.status === "not_fit" ? "" : `<button class="btn btn-sm btn-ghost" type="button" data-act="not_fit" data-id="${lead.id}">Not a fit</button>`}
        <span class="grow"></span>
        ${statusSelect(lead)}
      </div>
    </div>
  </article>`;
}

// Wire up copy / save / not-a-fit / status changes for every card inside `root`.
// onChange(lead, prevStatus) can return true to remove the card (e.g. "not a fit" in a feed).
export function bindCards(root, { onChange, removeWhen = [] } = {}) {
  root.addEventListener("click", async (e) => {
    const copyBtn = e.target.closest("[data-copy]");
    if (copyBtn) {
      e.preventDefault();
      copyText(copyBtn.dataset.copy, copyBtn);
      return;
    }
    const act = e.target.closest("[data-act]");
    if (act && act.dataset.id) {
      e.preventDefault();
      await changeStatus(root, act.dataset.id, act.dataset.act, { onChange, removeWhen });
    }
  });
  root.addEventListener("change", async (e) => {
    const sel = e.target.closest("select[data-status]");
    if (sel) await changeStatus(root, sel.dataset.status, sel.value, { onChange, removeWhen });
  });
}

async function changeStatus(root, id, status, { onChange, removeWhen }) {
  const card = root.querySelector(`[data-lead="${id}"]`);
  const prev = card?.querySelector("select[data-status]")?.dataset.current || null;
  if (prev === status) return;
  try {
    const lead = await post(`/api/leads/${id}/status`, { status });
    afterStatus(root, card, lead, { onChange, removeWhen, before: prev });
  } catch (err) {
    toast(err.message, { error: true });
    if (card) {
      const sel = card.querySelector("select[data-status]");
      if (sel && prev) sel.value = prev;
    }
  }
}

function afterStatus(root, card, lead, { onChange, removeWhen, before }) {
  const label = statusLabel(lead.status);
  const remove = removeWhen.includes(lead.status);
  if (card) {
    if (remove) {
      card.classList.add("leaving");
      setTimeout(() => card.remove(), 300);
    } else {
      const tmp = document.createElement("div");
      tmp.innerHTML = leadCard(lead);
      const fresh = tmp.firstElementChild;
      card.replaceWith(fresh);
    }
  }
  if (onChange) onChange(lead);
  const undoTo = before && before !== lead.status ? before : null;
  toast(lead.status === "not_fit" ? "Marked not a fit. Noise filtered." : `Moved to ${label}.`, undoTo ? {
    action: "Undo",
    onAction: async () => {
      try {
        const back = await post(`/api/leads/${lead.id}/status`, { status: undoTo });
        if (remove) {
          if (onChange) onChange(back, { restored: true });
        } else {
          const c = root.querySelector(`[data-lead="${lead.id}"]`);
          if (c) {
            const tmp = document.createElement("div");
            tmp.innerHTML = leadCard(back);
            c.replaceWith(tmp.firstElementChild);
          }
          if (onChange) onChange(back);
        }
      } catch (err) { toast(err.message, { error: true }); }
    },
  } : {});
}

// ------------------------------------------------------------------ clipboard
export async function copyText(text, btn) {
  let ok = false;
  try {
    await navigator.clipboard.writeText(text);
    ok = true;
  } catch (e) {
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { ok = document.execCommand("copy"); } catch (e2) { ok = false; }
    ta.remove();
  }
  if (ok) {
    toast(`Copied ${text}`);
    if (btn) {
      const old = btn.innerHTML;
      btn.classList.add("done");
      btn.innerHTML = icon.check;
      setTimeout(() => { btn.classList.remove("done"); btn.innerHTML = old; }, 1400);
    }
  } else {
    toast("Couldn't copy. Select the handle and copy it manually.", { error: true });
  }
  return ok;
}

// ------------------------------------------------------------------ toasts / modals
export function toast(message, { error = false, action = null, onAction = null, ms = 4200 } = {}) {
  const root = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = "toast" + (error ? " err" : "");
  el.setAttribute("role", error ? "alert" : "status");
  el.innerHTML = `<span>${esc(message)}</span>${action ? `<button class="btn btn-sm" type="button">${esc(action)}</button>` : ""}`;
  root.appendChild(el);
  const kill = () => el.remove();
  if (action) el.querySelector("button").addEventListener("click", () => { kill(); onAction && onAction(); });
  setTimeout(kill, action ? ms + 2500 : ms);
}

export function modal({ title, body, foot = "", wide = false, onClose } = {}) {
  const root = document.getElementById("sheet-root");
  const overlay = document.createElement("div");
  overlay.className = "overlay";
  overlay.innerHTML = `<div class="modal" role="dialog" aria-modal="true" aria-label="${esc(title)}" style="${wide ? "width:min(860px,100%)" : ""}">
    <div class="modal-head"><h2>${esc(title)}</h2><button class="close-x" type="button" aria-label="Close">×</button></div>
    <div class="modal-body">${body}</div>${foot ? `<div class="modal-foot">${foot}</div>` : ""}</div>`;
  const prevFocus = document.activeElement;
  const close = () => {
    overlay.remove();
    document.removeEventListener("keydown", onKey);
    document.body.style.overflow = "";
    if (prevFocus && prevFocus.focus) prevFocus.focus();
    onClose && onClose();
  };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  overlay.addEventListener("mousedown", (e) => { if (e.target === overlay) close(); });
  overlay.querySelector(".close-x").addEventListener("click", close);
  document.addEventListener("keydown", onKey);
  root.appendChild(overlay);
  document.body.style.overflow = "hidden";
  const first = overlay.querySelector("input, select, textarea, button:not(.close-x)");
  setTimeout(() => first && first.focus(), 30);
  return { el: overlay, close };
}

export function confirmBox(title, text, okLabel = "Confirm", danger = false) {
  return new Promise((resolve) => {
    let done = false;
    const m = modal({
      title,
      body: `<p class="muted" style="margin:0">${esc(text)}</p>`,
      foot: `<button class="btn btn-ghost" type="button" data-no>Cancel</button><button class="btn ${danger ? "btn-danger" : "btn-primary"}" type="button" data-yes>${esc(okLabel)}</button>`,
      onClose: () => { if (!done) resolve(false); },
    });
    m.el.querySelector("[data-no]").addEventListener("click", () => { done = true; m.close(); resolve(false); });
    m.el.querySelector("[data-yes]").addEventListener("click", () => { done = true; m.close(); resolve(true); });
  });
}

export function emptyState({ title, text, actions = "" , small = false }) {
  return `<div class="empty ${small ? "empty-sm" : ""}">${small ? "" : MARK}<h2>${esc(title)}</h2>${text ? `<p>${text}</p>` : ""}${actions ? `<div class="row">${actions}</div>` : ""}</div>`;
}

export function errorBox(err) {
  return `<div class="err-box"><b class="mono">Something went wrong.</b><p style="margin:6px 0 0">${esc(err?.message || err)}</p></div>`;
}

export function spinner() { return `<span class="spinner" aria-hidden="true"></span>`; }

export function debounce(fn, ms = 250) {
  let t;
  return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// Busy state for a button while a promise runs.
export async function busy(btn, label, fn) {
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `${spinner()}<span>${esc(label)}</span>`;
  try { return await fn(); }
  finally { btn.disabled = false; btn.innerHTML = old; }
}
