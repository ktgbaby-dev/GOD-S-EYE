// + ADD LEAD — manual entry. The server validates, de-duplicates by platform + handle and scores it.
import { post } from "../api.js";
import { state, esc, modal, toast, busy } from "../ui.js";

const URL_RULES = [
  [/instagram\.com\/([A-Za-z0-9._]{1,30})\/?(?:[?#].*)?$/i, "instagram"],
  [/tiktok\.com\/@([A-Za-z0-9._]{2,30})/i, "tiktok"],
  [/youtube\.com\/@([A-Za-z0-9._-]{3,30})/i, "youtube"],
  [/(?:twitter|x)\.com\/([A-Za-z0-9_]{1,15})\/?(?:[?#].*)?$/i, "x"],
  [/audius\.co\/([A-Za-z0-9._-]+)\/?$/i, "audius"],
  [/soundcloud\.com\/([A-Za-z0-9._-]+)\/?$/i, "soundcloud"],
  [/audiomack\.com\/([A-Za-z0-9._-]+)\/?$/i, "audiomack"],
];

function fromUrl(url) {
  for (const [rx, platform] of URL_RULES) {
    const m = String(url).match(rx);
    if (m && !["p", "reel", "reels", "explore", "stories"].includes(m[1].toLowerCase())) return { platform, handle: m[1] };
  }
  return null;
}

export function openAddLead({ navigate, prefill = {} }) {
  const st = state.meta.strategy;
  const platforms = state.meta.platforms.map((p) => `<option value="${p.key}" ${p.key === (prefill.platform || "instagram") ? "selected" : ""}>${esc(p.label)}</option>`).join("");
  const genres = st.target_genres.map((g) => `<option value="${esc(g)}">`).join("");
  const locations = st.target_locations.map((g) => `<option value="${esc(g)}">`).join("");
  const body = `<form id="add-form" class="stack" novalidate>
    <div class="form-grid">
      <label class="field span-2"><span>Profile URL</span><input class="input" name="profile_url" type="url" inputmode="url" placeholder="https://www.instagram.com/…" autocomplete="off"></label>
      <label class="field"><span>Artist name</span><input class="input" name="name" required autocomplete="off" placeholder="Stage name"></label>
      <label class="field"><span>Handle</span><input class="input" name="handle" required autocomplete="off" autocapitalize="off" spellcheck="false" placeholder="@handle"></label>
      <label class="field"><span>Platform</span><select class="input" name="platform">${platforms}</select></label>
      <label class="field"><span>Followers</span><input class="input" name="followers" inputmode="decimal" placeholder="e.g. 12.4K"></label>
      <label class="field"><span>Genre</span><input class="input" name="genre" list="dl-genres" placeholder="Afrobeats"><datalist id="dl-genres">${genres}</datalist></label>
      <label class="field"><span>Location</span><input class="input" name="location" list="dl-locs" placeholder="Lagos, Nigeria"><datalist id="dl-locs">${locations}</datalist></label>
      <label class="field span-2"><span>Source</span><input class="input" name="source" placeholder="Where you found them, e.g. Instagram explore, a friend's repost"></label>
      <label class="field span-2"><span>Notes (private)</span><textarea class="input" name="notes" rows="3" placeholder="Only you see this."></textarea></label>
    </div>
    <details class="more">
      <summary>Signals for scoring (optional)</summary>
      <div class="form-grid" style="margin-top:12px">
        <label class="field span-2"><span>Public bio or a recent caption</span><textarea class="input" name="bio" rows="3" placeholder="Paste what they wrote publicly. GOD'S EYE reads it for signals like “new EP loading” or “producers DM”."></textarea></label>
        <label class="field"><span>Last active</span><input class="input" name="last_activity_at" type="date"></label>
        <label class="field"><span>Latest release</span><input class="input" name="last_release_at" type="date"></label>
      </div>
    </details>
    <p class="form-error" id="add-error" role="alert"></p>
  </form>`;
  const foot = `<button class="btn btn-ghost" type="button" data-cancel>Cancel</button><button class="btn btn-primary" type="submit" form="add-form" id="add-submit">Save lead</button>`;
  const m = modal({ title: "Add lead", body, foot });
  const form = m.el.querySelector("#add-form");
  const err = m.el.querySelector("#add-error");
  for (const [k, v] of Object.entries(prefill)) if (form.elements[k]) form.elements[k].value = v;
  m.el.querySelector("[data-cancel]").addEventListener("click", m.close);
  // Fill platform + handle from the URL; keep following the URL while the fields still hold what we filled in.
  let auto = { handle: "", name: "" };
  form.elements.profile_url.addEventListener("input", () => {
    const hit = fromUrl(form.elements.profile_url.value.trim());
    if (!hit) return;
    form.elements.platform.value = hit.platform;
    for (const k of ["handle", "name"]) {
      if (!form.elements[k].value || form.elements[k].value === auto[k]) {
        form.elements[k].value = hit.handle;
        auto[k] = hit.handle;
      }
    }
  });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    err.textContent = "";
    const data = Object.fromEntries(new FormData(form).entries());
    if (!data.handle && !data.profile_url) {
      err.textContent = "Add a handle or a profile URL.";
      return;
    }
    for (const k of ["last_activity_at", "last_release_at"]) if (!data[k]) delete data[k];
    const btn = m.el.querySelector("#add-submit");
    await busy(btn, "Saving", async () => {
      try {
        const res = await post("/api/leads", data);
        m.close();
        toast(`Added ${res.lead.name} · score ${res.lead.score}`);
        navigate(`/leads/${res.id}`);
      } catch (ex) {
        if (ex.status === 409 && ex.data.lead_id) {
          err.innerHTML = `${esc(ex.message)}. <a href="/leads/${ex.data.lead_id}" data-link class="link">Open existing lead</a>`;
          err.querySelector("a").addEventListener("click", () => m.close());
        } else {
          err.textContent = ex.message;
        }
      }
    });
  });
}
