// IMPORT: CSV, JSON or pasted profile links → preview (dry run) → import. Duplicates are skipped and listed.
import { post } from "../api.js";
import { esc, icon, toast, busy, plural } from "../ui.js";

const TABS = [["csv", "CSV"], ["json", "JSON"], ["links", "Paste links"]];

export async function render(el, { query, navigate, refreshCounts, loadMeta }) {
  let tab = TABS.some(([k]) => k === query.tab) ? query.tab : "csv";
  let content = "";
  let fileName = "";

  const draw = () => {
    el.innerHTML = `<header class="page-head"><div><span class="eyebrow">Manual import</span><h1>Import leads</h1>
        <p class="sub">Bring in prospects you've found yourself. They join the same database, scoring and workflow as discovered leads. Duplicates (same platform + handle) are never added twice.</p></div>
        <div class="page-actions"><a class="btn" href="/api/import/template.csv" download>${icon.download}CSV template</a></div></header>
      <div class="seg" role="tablist" style="margin-bottom:18px">${TABS.map(([k, l]) => `<button type="button" role="tab" data-tab="${k}" aria-pressed="${k === tab}" aria-selected="${k === tab}">${esc(l)}</button>`).join("")}</div>
      <section class="panel"><div class="panel-body stack">
        ${tab === "links" ? `<label class="field"><span>Profile links, one per line</span>
            <textarea class="input mono" id="content" rows="9" placeholder="https://www.instagram.com/…&#10;https://www.tiktok.com/@…&#10;https://www.youtube.com/@…">${esc(content)}</textarea></label>
            <p class="hint" style="margin:0">Instagram, TikTok, YouTube, X, Audius, SoundCloud and Audiomack links. The handle and platform are read from each link.</p>`
          : `<label class="field"><span>${tab === "csv" ? "CSV file" : "JSON file"}</span>
            <input class="input" type="file" id="file" accept="${tab === "csv" ? ".csv,text/csv" : ".json,application/json"}"></label>
            ${fileName ? `<p class="small muted" style="margin:0">Loaded <b class="mono">${esc(fileName)}</b> · ${content.length.toLocaleString()} characters</p>` : ""}
            <details class="more" style="margin-top:0"><summary>Or paste ${tab.toUpperCase()}</summary>
              <textarea class="input mono" id="content" rows="8" style="margin-top:10px" placeholder="${tab === "csv" ? "name,handle,platform,profile_url,genre,location,followers,source,notes" : '[{"name": "…", "handle": "…", "platform": "instagram"}]'}">${esc(content)}</textarea></details>
            <p class="hint" style="margin:0">Columns: <code class="mono-inline">name</code> <code class="mono-inline">handle</code> <code class="mono-inline">platform</code> <code class="mono-inline">profile_url</code> <code class="mono-inline">genre</code> <code class="mono-inline">location</code> <code class="mono-inline">followers</code> <code class="mono-inline">source</code> <code class="mono-inline">notes</code>. Optional: <code class="mono-inline">bio</code> <code class="mono-inline">last_activity_at</code> <code class="mono-inline">last_release_at</code>. A row needs a handle or a profile URL.</p>`}
        <label class="field" style="max-width:420px"><span>Source label</span><input class="input" id="source" placeholder="${tab === "links" ? "Pasted links" : tab.toUpperCase() + " import"}"></label>
        <div class="row"><button class="btn btn-primary" type="button" id="preview">Preview import</button></div>
      </div></section>
      <section id="result" style="margin-top:22px"></section>`;
    wire();
  };

  function wire() {
    el.querySelectorAll("[data-tab]").forEach((b) => b.addEventListener("click", () => {
      tab = b.dataset.tab; content = ""; fileName = "";
      history.replaceState(null, "", "/import?tab=" + tab);
      draw();
    }));
    const file = el.querySelector("#file");
    file?.addEventListener("change", async () => {
      const f = file.files[0];
      if (!f) return;
      if (f.size > 4 * 1024 * 1024) { toast("File too large: keep imports under 4 MB.", { error: true }); return; }
      content = await f.text();
      fileName = f.name;
      draw();
    });
    el.querySelector("#content")?.addEventListener("input", (e) => { content = e.target.value; fileName = ""; });
    el.querySelector("#preview").addEventListener("click", (e) => run(e.currentTarget, true));
  }

  async function run(btn, dryRun) {
    if (!content.trim()) { toast(tab === "links" ? "Paste at least one link." : "Choose a file or paste the data first.", { error: true }); return; }
    const source = el.querySelector("#source")?.value || "";
    await busy(btn, dryRun ? "Checking" : "Importing", async () => {
      try {
        const res = await post("/api/import", { format: tab, content, dry_run: dryRun, source });
        el.querySelector("#result").innerHTML = resultView(res);
        el.querySelector("#commit")?.addEventListener("click", (ev) => run(ev.currentTarget, false));
        if (!dryRun) {
          toast(`Imported ${plural(res.stats.added, "lead")}.`);
          content = "";
          await loadMeta(true);
          refreshCounts();
        }
      } catch (err) {
        el.querySelector("#result").innerHTML = `<div class="banner err"><div><b>Import problem</b><p>${esc(err.message)}</p></div></div>`;
      }
    });
  }

  draw();
}

function resultView(res) {
  const s = res.stats;
  const outcome = { added: res.dry_run ? "Will add" : "Added", duplicate: "Duplicate", invalid: "Skipped" };
  const cls = { added: "b-verified", duplicate: "b-seen", invalid: "b-stale" };
  return `<div class="banner ${s.added ? "" : "neutral"}"><div>
      <b>${res.dry_run ? "Preview" : "Import complete"}</b>
      <p>${s.rows} rows · ${s.added} ${res.dry_run ? "new" : "added"} · ${s.duplicate} duplicate${s.duplicate === 1 ? "" : "s"} skipped · ${s.invalid} invalid</p>
    </div>${res.dry_run && s.added ? `<button class="btn btn-primary" type="button" id="commit" style="margin-left:auto">Import ${plural(s.added, "lead")}</button>` : ""}
    ${!res.dry_run && s.added ? `<a class="btn" href="/leads?provenance=import&sort=newest" data-link style="margin-left:auto">View imported →</a>` : ""}</div>
    <div class="panel table-wrap"><table class="table"><thead><tr><th>Row</th><th>Lead</th><th>Result</th><th class="hide-sm">Detail</th></tr></thead><tbody>
    ${res.results.map((r) => `<tr><td class="mono">${r.row}</td><td>${r.lead_id ? `<a href="/leads/${r.lead_id}" data-link>${esc(r.input)}</a>` : esc(r.input)}</td>
      <td><span class="badge ${cls[r.outcome]}">${esc(outcome[r.outcome])}</span></td><td class="hide-sm small muted">${esc(r.error || "")}</td></tr>`).join("")}
    </tbody></table></div>`;
}
