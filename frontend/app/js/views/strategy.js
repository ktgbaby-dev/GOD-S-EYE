// STRATEGY: what GOD'S EYE hunts for and how it scores. Stored server-side; saving rescores every lead.
import { get, put } from "../api.js";
import { state, esc, toast, busy, plural } from "../ui.js";

const PLATFORMS = [["instagram", "Instagram"], ["tiktok", "TikTok"], ["youtube", "YouTube"], ["audius", "Audius"], ["x", "X"], ["soundcloud", "SoundCloud"], ["audiomack", "Audiomack"], ["boomplay", "Boomplay"], ["spotify", "Spotify"]];
const TIMEZONES = ["Africa/Lagos", "Africa/Accra", "Europe/London", "Africa/Johannesburg", "Africa/Nairobi", "America/New_York", "UTC"];

export async function render(el, { loadMeta }) {
  const data = await get("/api/strategy");
  let st = structuredClone(data.strategy);
  const signals = data.signals;

  const chipList = (key) => `<div class="chips" id="chips-${key}">${st[key].map((v, i) => `<span class="chip">${esc(v)}<button type="button" data-remove="${key}" data-i="${i}" aria-label="Remove ${esc(v)}">×</button></span>`).join("") || `<span class="faint small">None. GOD'S EYE needs at least one.</span>`}</div>
    <form class="chip-add" data-add="${key}"><input class="input" name="v" placeholder="Add ${key === "target_genres" ? "a genre" : "a location"}" autocomplete="off"><button class="btn" type="submit">Add</button></form>`;

  const num = (key, label, hint, min, max, suffix = "") => `<label class="field"><span>${label}</span>
    <div class="row" style="flex-wrap:nowrap"><input class="input" type="number" name="${key}" value="${st[key]}" min="${min}" max="${max}" inputmode="numeric" style="max-width:120px">${suffix ? `<span class="muted small">${suffix}</span>` : ""}</div>
    <span class="hint" style="text-transform:none;letter-spacing:0;font-family:var(--sans)">${hint}</span></label>`;

  const draw = () => {
    let lastGroup = "";
    el.innerHTML = `<header class="page-head"><div><span class="eyebrow">Private strategy</span><h1>Strategy</h1>
        <p class="sub">What GOD'S EYE looks for, how much each signal is worth, and how many prospects you want a day. Saving rescores every lead.</p></div>
        <div class="page-actions"><button class="btn btn-primary" type="button" id="save">Save strategy</button></div></header>
      <div class="stack-lg">
        <section class="panel"><div class="panel-head"><h3 class="h3">Target genres</h3><span class="eyebrow">genre fit · ${signals.find((s) => s.code === "genre_fit").points} pts</span></div>
          <div class="panel-body">${chipList("target_genres")}</div></section>
        <section class="panel"><div class="panel-head"><h3 class="h3">Target locations</h3><span class="eyebrow">location fit · ${signals.find((s) => s.code === "location_fit").points} pts</span></div>
          <div class="panel-body">${chipList("target_locations")}<p class="hint" style="margin:10px 0 0">A country also matches its cities: “Nigeria” matches an artist in Lekki or Port Harcourt.</p></div></section>
        <section class="panel"><div class="panel-head"><h3 class="h3">Target platforms</h3></div>
          <div class="panel-body"><div class="seg" role="group" aria-label="Target platforms">${PLATFORMS.map(([k, l]) => `<button type="button" class="chip-toggle" data-plat="${k}" aria-pressed="${st.target_platforms.includes(k)}">${esc(l)}</button>`).join("")}</div>
          <p class="hint" style="margin:12px 0 0">The daily drop scans these platforms with whichever sources are live (Settings → Sources).</p></div></section>
        <section class="panel"><div class="panel-head"><h3 class="h3">Thresholds & rhythm</h3></div>
          <div class="panel-body form-grid">
            ${num("score_threshold", "Lead score threshold", "At or above this a prospect is HIGH PRIORITY.", 1, 100, "and up")}
            ${num("keep_min_score", "Keep from discovery", "Candidates below this are filtered as noise (you can still keep them).", 0, 100, "minimum")}
            ${num("daily_target", "Daily target", "How many prospects Today's Drop shows.", 1, 100, "leads / day")}
            ${num("follow_up_days", "Follow-up after", "Days after you mark someone contacted.", 1, 60, "days")}
            ${num("stale_days", "Stale after", "No activity (or not seen) for this long = STALE, pushed down.", 7, 365, "days")}
            ${num("max_queries_per_batch", "Queries per scan", "Caps paid API usage per batch.", 1, 30, "queries")}
            ${num("drop_hour", "Daily drop hour", "Local hour the automatic drop may run (local server). On Vercel the cron schedule in vercel.json decides.", 0, 23, ":00")}
            <label class="field"><span>Timezone</span><select class="input" name="timezone">${[...new Set([st.timezone, ...TIMEZONES])].map((z) => `<option ${z === st.timezone ? "selected" : ""}>${esc(z)}</option>`).join("")}</select>
              <span class="hint" style="text-transform:none;letter-spacing:0;font-family:var(--sans)">Defines “today” for drops and counts.</span></label>
          </div></section>
        <section class="panel" id="weights"><div class="panel-head"><h3 class="h3">Scoring signals</h3><button class="btn btn-sm btn-ghost" type="button" id="reset-w">Reset to defaults</button></div>
          <div class="panel-body">
            <p class="hint" style="margin:0 0 6px">A lead's score is the sum of the signals that fired, capped at 0–100. Negative points push noise down. Set a signal to 0 to ignore it.</p>
            <div class="weights">${signals.map((s) => {
              const g = s.group !== lastGroup ? `<div class="weight-group h3">${esc(s.group)}</div>` : "";
              lastGroup = s.group;
              const val = st.weights[s.code] ?? s.default;
              return `${g}<label class="weight ${val !== s.default ? "changed" : ""}"><span>${esc(s.label)}<small>default ${s.default > 0 ? "+" : ""}${s.default}</small></span>
                <input class="input" type="number" min="-50" max="50" step="1" data-w="${s.code}" data-default="${s.default}" value="${val}"></label>`;
            }).join("")}</div>
          </div></section>
      </div>`;
    wire();
  };

  function collect() {
    for (const k of ["score_threshold", "keep_min_score", "daily_target", "follow_up_days", "stale_days", "max_queries_per_batch", "drop_hour"]) {
      const v = el.querySelector(`[name="${k}"]`).value;
      st[k] = v === "" ? st[k] : Number(v);
    }
    st.timezone = el.querySelector('[name="timezone"]').value;
    const w = {};
    el.querySelectorAll("[data-w]").forEach((i) => {
      const n = Number(i.value);
      if (i.value !== "" && n !== Number(i.dataset.default)) w[i.dataset.w] = n;
    });
    st.weights = w;
  }

  function wire() {
    el.querySelectorAll("[data-add]").forEach((f) => f.addEventListener("submit", (e) => {
      e.preventDefault();
      const key = f.dataset.add;
      const v = f.elements.v.value.trim();
      if (!v) return;
      collect();
      if (!st[key].some((x) => x.toLowerCase() === v.toLowerCase())) st[key].push(v);
      draw();
      el.querySelector(`[data-add="${key}"] input`).focus();
    }));
    el.querySelectorAll("[data-remove]").forEach((b) => b.addEventListener("click", () => {
      collect();
      st[b.dataset.remove].splice(Number(b.dataset.i), 1);
      draw();
    }));
    el.querySelectorAll("[data-plat]").forEach((b) => b.addEventListener("click", () => {
      collect();
      const k = b.dataset.plat;
      st.target_platforms = st.target_platforms.includes(k) ? st.target_platforms.filter((x) => x !== k) : [...st.target_platforms, k];
      draw();
    }));
    el.querySelectorAll("[data-w]").forEach((i) => i.addEventListener("input", () => {
      i.closest(".weight").classList.toggle("changed", Number(i.value) !== Number(i.dataset.default));
    }));
    el.querySelector("#reset-w").addEventListener("click", () => {
      collect();
      st.weights = {};
      draw();
      toast("Signal points reset. Save to apply.");
    });
    el.querySelector("#save").addEventListener("click", async (e) => {
      collect();
      if (!st.target_genres.length || !st.target_locations.length) {
        toast("Keep at least one genre and one location.", { error: true });
        return;
      }
      await busy(e.currentTarget, "Saving", async () => {
        try {
          const res = await put("/api/strategy", st);
          st = structuredClone(res.strategy);
          await loadMeta(true);
          state.meta.strategy = res.strategy;
          draw();
          toast(`Strategy saved. ${plural(res.rescored, "lead")} rescored.`);
        } catch (err) { toast(err.message, { error: true }); }
      });
    });
  }

  draw();
}
