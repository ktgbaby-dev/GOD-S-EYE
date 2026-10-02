// DISCOVER: an on-demand scan against the configured sources, plus manual recon links for OG-WAN's own browser.
import { post } from "../api.js";
import { state, esc, icon, leadCard, bindCards, emptyState, plural, toast, safeHref, ring, handleText } from "../ui.js";

const PLATFORM_KEYS = [["all", "All"], ["instagram", "Instagram"], ["tiktok", "TikTok"], ["youtube", "YouTube"], ["audius", "Audius"]];

export async function render(el, { navigate, refreshCounts }) {
  const m = state.meta;
  const st = m.strategy;
  const prov = m.providers;
  const livePlatforms = new Set(prov.filter((p) => p.enabled && p.configured).flatMap((p) => p.platforms));
  const opt = (arr, sel) => arr.map(([v, l]) => `<option value="${esc(v)}" ${v === sel ? "selected" : ""}>${esc(l)}</option>`).join("");
  el.innerHTML = `<header class="page-head">
      <div><span class="eyebrow">Active search</span><h1>Discover</h1>
      <p class="sub">Scan real public sources for artists who match what you're looking for. New finds are saved as NEW leads with their source; anything already in GOD'S EYE is marked seen, never duplicated.</p></div>
    </header>
    <form id="scan" class="panel" novalidate>
      <div class="panel-body">
        <div class="form-grid">
          <label class="field"><span>Looking for</span><select class="input" name="looking_for">${opt(m.looking_for.map((x) => [x.key, x.label]), "artists")}</select></label>
          <label class="field"><span>Genre</span><select class="input" name="genre">${opt([["", "All target genres"], ...st.target_genres.map((g) => [g, g])], st.target_genres[0] || "")}</select></label>
          <label class="field"><span>Location</span><select class="input" name="location">${opt([["", "All target locations"], ...st.target_locations.map((g) => [g, g])], "")}</select></label>
          <div class="field span-3"><span>Platform</span>
            <div class="seg" role="group" aria-label="Platform">${PLATFORM_KEYS.map(([k, l]) => {
              const ok = k === "all" ? livePlatforms.size > 0 : livePlatforms.has(k);
              return `<button type="button" data-platform="${k}" aria-pressed="${k === "all"}" ${ok ? "" : "disabled"} title="${ok ? "" : "Needs a source: see Settings"}">${esc(l)}${ok ? "" : " · off"}</button>`;
            }).join("")}</div>
          </div>
          <label class="field"><span>Signal</span><select class="input" name="signal">${opt(m.signals.map((x) => [x.key, x.label]), "recent_release")}</select></label>
          <div class="field span-2"><span>Minimum score</span>
            <div class="range-row"><input type="range" name="min_score" min="0" max="100" step="5" value="${st.keep_min_score}" aria-label="Minimum score"><output id="min-out">${st.keep_min_score}</output></div>
          </div>
        </div>
      </div>
      <div class="filter-foot">
        <span class="hint">${livePlatforms.size ? `Live sources: ${esc(prov.filter((p) => p.enabled && p.configured).map((p) => p.label).join(" · "))}. Up to ${st.max_queries_per_batch} queries per scan.` : "No source is live. Add a key in Settings, or use manual recon below."}</span>
        <button class="btn btn-primary btn-lg" type="submit" id="go" ${livePlatforms.size ? "" : "disabled"}>${icon.scan}Scan for prospects</button>
      </div>
    </form>
    <section id="results" style="margin-top:26px"></section>
    ${recon(st)}`;

  const form = el.querySelector("#scan");
  const out = el.querySelector("#min-out");
  form.elements.min_score.addEventListener("input", () => { out.textContent = form.elements.min_score.value; });
  let platform = "all";
  form.querySelectorAll("[data-platform]").forEach((b) => b.addEventListener("click", () => {
    platform = b.dataset.platform;
    form.querySelectorAll("[data-platform]").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
  }));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = el.querySelector("#go");
    const body = {
      looking_for: form.elements.looking_for.value,
      genres: form.elements.genre.value ? [form.elements.genre.value] : [],
      locations: form.elements.location.value ? [form.elements.location.value] : [],
      platforms: platform === "all" ? [...livePlatforms] : [platform],
      signal: form.elements.signal.value,
      min_score: Number(form.elements.min_score.value),
    };
    btn.disabled = true;
    const results = el.querySelector("#results");
    results.innerHTML = scanning(body);
    results.scrollIntoView({ behavior: "smooth", block: "start" });
    try {
      const res = await post("/api/discover", body);
      results.innerHTML = renderBatch(res.run, res.batch);
      bindCards(results, {});
      wireKeep(results, navigate);
      refreshCounts();
    } catch (err) {
      results.innerHTML = `<div class="banner err"><div><b>Scan failed</b><p>${esc(err.message)}</p></div></div>`;
    } finally {
      btn.disabled = false;
    }
  });
}

function scanning(body) {
  const prov = state.meta.providers.filter((p) => p.enabled && p.configured && p.platforms.some((x) => body.platforms.includes(x)));
  const lines = [
    `target  ${body.genres[0] || "all target genres"} · ${body.locations[0] || "all target locations"} · ${body.looking_for}`,
    `signal  ${(state.meta.signals.find((s) => s.key === body.signal) || {}).label || body.signal}`,
    ...prov.map((p) => `query   ${p.label}`),
    `filter  minimum score ${body.min_score}`,
  ];
  return `<div class="console scanline" role="status" aria-live="polite"><div class="hd">SCANNING…</div>
    ${lines.map((l, i) => `<div class="ln" style="animation-delay:${0.25 + i * 0.35}s">${esc(l)}</div>`).join("")}
    <div class="ln" style="animation-delay:${0.25 + lines.length * 0.35}s"><span class="caret"></span></div></div>`;
}

function renderBatch(run, batch) {
  const st = run.stats;
  const items = batch.items;
  const added = items.filter((i) => i.outcome === "added" || i.outcome === "kept");
  const seen = items.filter((i) => i.outcome === "seen");
  const filtered = items.filter((i) => i.outcome === "filtered");
  const errs = run.errors || [];
  const summary = `<div class="banner ${errs.length && !st.found ? "err" : ""}"><div>
      <b>${st.added ? "Fresh signals detected" : st.found ? "Scan complete" : "No candidates returned"}</b>
      <p>${plural(st.found, "candidate")} · ${st.added} new · ${st.seen} seen before · ${st.filtered} noise filtered · ${plural(st.queries, "query", "queries")} · ${run.seconds}s</p>
      ${errs.length || run.notes.length ? `<ul class="notes">${errs.map((e) => `<li>${esc(e)}</li>`).join("")}${run.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>` : ""}
      ${run.queries.length ? `<ul class="notes">${run.queries.map((q) => `<li class="mono tiny">${esc(q.label)} → ${q.error ? esc(q.error) : q.found + " found"}</li>`).join("")}</ul>` : ""}
    </div></div>`;
  if (!items.length) {
    return summary + emptyState({ small: true, title: "Nothing new on this pass", text: "Every query has a resume point, so the next scan continues further down the results. Try another signal, genre or location." });
  }
  return `${summary}
    ${added.length ? `<h2 class="h2" style="margin:8px 0 14px">New prospects <span class="faint">· ${added.length}</span></h2>
      <div class="cards boxed">${added.map((i) => leadCard(i.lead)).join("")}</div>` : ""}
    ${seen.length ? `<h2 class="h2" style="margin:32px 0 14px">Seen before <span class="faint">· ${seen.length}</span></h2>
      <p class="hint" style="margin:-6px 0 12px">Already in GOD'S EYE. Their public stats and evidence were refreshed; they stay where they are in your pipeline.</p>
      <div class="cards boxed">${seen.map((i) => leadCard(i.lead)).join("")}</div>` : ""}
    ${filtered.length ? `<details class="panel" style="margin-top:32px"><summary class="panel-head" style="cursor:pointer;list-style:none"><h3 class="h3">Noise filtered · ${filtered.length}</h3><span class="eyebrow">Below score ${batch.params.min_score}</span></summary>
      <div class="table-wrap"><table class="table"><thead><tr><th>Score</th><th>Artist</th><th class="hide-sm">Platform</th><th class="hide-sm">Location</th><th></th></tr></thead><tbody>
      ${filtered.map((i) => {
        const p = i.preview;
        return `<tr><td>${ring(i.score, { withTier: false })}</td><td><b>${esc(p.name)}</b><div class="mono tiny faint">${esc(handleText(p))}${p.followers_label ? " · " + esc(p.followers_label) : ""}</div></td>
          <td class="hide-sm">${esc(p.platform_label)}</td><td class="hide-sm">${esc(p.location || "—")}</td>
          <td class="num"><div class="row" style="justify-content:flex-end">${safeHref(p.profile_url) ? `<a class="btn btn-sm btn-ghost" href="${safeHref(p.profile_url)}" target="_blank" rel="noopener noreferrer">View</a>` : ""}<button class="btn btn-sm" type="button" data-keep="${i.candidate_id}">Keep</button></div></td></tr>`;
      }).join("")}</tbody></table></div></details>` : ""}`;
}

function wireKeep(root, navigate) {
  root.addEventListener("click", async (e) => {
    const b = e.target.closest("[data-keep]");
    if (!b) return;
    b.disabled = true;
    try {
      const res = await post(`/api/candidates/${b.dataset.keep}/keep`);
      b.outerHTML = `<a class="btn btn-sm btn-primary" href="/leads/${res.lead_id}" data-link>Kept · open</a>`;
      toast("Kept. Added to your leads as NEW.");
    } catch (err) {
      b.disabled = false;
      toast(err.message, { error: true });
    }
  });
}

// Links OG-WAN opens in his own browser. GOD'S EYE doesn't fetch these pages.
function recon(st) {
  const g = st.target_genres[0] || "afrobeats";
  const loc = st.target_locations[0] || "";
  const tag = (s) => s.toLowerCase().replace(/[^a-z0-9]/g, "");
  const links = [
    ["Instagram", `#${tag(g)}artist`, `https://www.instagram.com/explore/tags/${encodeURIComponent(tag(g) + "artist")}/`],
    ["Instagram", `#${tag(loc || "naija")}artist`, `https://www.instagram.com/explore/tags/${encodeURIComponent(tag(loc || "naija") + "artist")}/`],
    ["Instagram", "#newmusicfriday", "https://www.instagram.com/explore/tags/newmusicfriday/"],
    ["TikTok", `${g} new artist`, `https://www.tiktok.com/search?q=${encodeURIComponent(`${g} new artist ${loc}`.trim())}`],
    ["TikTok", `${g} snippet`, `https://www.tiktok.com/search?q=${encodeURIComponent(`${g} snippet unreleased`)}`],
    ["YouTube", `${g} official video · this week`, `https://www.youtube.com/results?search_query=${encodeURIComponent(`${g} official video ${loc}`.trim())}&sp=EgIIAw%253D%253D`],
    ["Google", `"looking for a producer" ${g}`, `https://www.google.com/search?q=${encodeURIComponent(`"looking for a producer" ${g} ${loc}`.trim())}&tbs=qdr:w`],
    ["X", `need beats ${g}`, `https://x.com/search?q=${encodeURIComponent(`"need beats" ${g}`)}&f=live`],
  ];
  return `<section class="panel" style="margin-top:34px">
    <div class="panel-head"><h3 class="h3">Manual recon</h3><span class="eyebrow">Opens in your browser</span></div>
    <div class="panel-body stack">
      <p class="hint" style="margin:0">Hand-picked searches built from your strategy. When you find someone, paste their profile link into <b>+ Add lead</b> (handle and platform fill in automatically) or paste a batch of links into <a class="link" href="/import?tab=links" data-link>Import</a>.</p>
      <div class="row">${links.map(([p, label, href]) => `<a class="btn btn-sm" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${icon.external}<span class="faint">${esc(p)}</span> ${esc(label)}</a>`).join("")}</div>
    </div>
  </section>`;
}
