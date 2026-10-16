const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const fmt = n => n == null ? "n/a" : new Intl.NumberFormat("en", {notation:"compact", maximumFractionDigits:1}).format(n);
let queries = [], data = [];

function toast(t){const e=$("#toast");e.textContent=t;e.classList.add("on");setTimeout(()=>e.classList.remove("on"),1400)}
document.addEventListener("click", e => {
  const c = e.target.closest("code[data-copy]");
  if (c) navigator.clipboard.writeText(c.dataset.copy).then(() => toast("Copied " + c.dataset.copy));
});

$("#f").addEventListener("submit", async e => {
  e.preventDefault();
  queries = $("#q").value.split("\n").map(s => s.trim()).filter(Boolean);
  if (!queries.length) return;
  $("#go").disabled = true; $("#bar").hidden = true;
  $("#out").innerHTML = queries.map(() => '<div class="skel"></div>').join("");
  try {
    const r = await fetch("/api/batch", {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({queries})});
    if (!r.ok) throw new Error("Server returned " + r.status);
    data = (await r.json()).results;
    render();
  } catch (err) {
    $("#out").innerHTML = `<div class="err">${esc(err.message)}. Check that the server is running and try again.</div>`;
  } finally { $("#go").disabled = false; }
});

$("#csv").onclick = () => location.href = "/api/export.csv?" + queries.map(q => "q=" + encodeURIComponent(q)).join("&");

function render() {
  const ok = data.filter(d => !d.error);
  $("#bar").hidden = !ok.length;
  $("#count").textContent = `${ok.length} artist${ok.length === 1 ? "" : "s"}, ${ok.reduce((n, d) => n + d.songs.length, 0)} songs`;
  $("#out").innerHTML = data.map((d, i) => d.error
    ? `<div class="err">${esc(d.query)}: ${esc(d.error)}</div>`
    : `<section class="artist" data-i="${i}">
        <div class="ahead">
          ${d.artist.thumbnail ? `<img src="${esc(d.artist.thumbnail)}" alt="" referrerpolicy="no-referrer">` : ""}
          <div><h2>${esc(d.artist.name)}</h2><div class="meta">${esc(d.artist.subscribers || "")} <code data-copy="${esc(d.artist.id)}">${esc(d.artist.id)}</code></div></div>
          <div class="total">${fmt(d.total_plays)}<small>plays across ${d.songs.length} songs</small></div>
          <input type="search" placeholder="Filter songs" aria-label="Filter songs">
        </div>
        <div class="scroll"><table></table></div>
      </section>`).join("");
  document.querySelectorAll(".artist").forEach(sec => {
    const d = data[sec.dataset.i];
    const st = {key:"plays", dir:-1, filter:""};
    const draw = () => drawTable(sec.querySelector("table"), d, st);
    sec.querySelector("input").addEventListener("input", e => { st.filter = e.target.value.toLowerCase(); draw(); });
    sec.addEventListener("click", e => {
      const th = e.target.closest("th[data-k]"); if (!th) return;
      st.dir = st.key === th.dataset.k ? -st.dir : (th.dataset.k === "plays" ? -1 : 1); st.key = th.dataset.k; draw();
    });
    draw();
  });
}

function drawTable(t, d, st) {
  const max = Math.max(...d.songs.map(s => s.plays || 0), 1);
  const val = s => st.key === "plays" ? (s.plays ?? -1) : String(s[st.key] ?? "").toLowerCase();
  const rows = d.songs
    .filter(s => (s.title + " " + s.album).toLowerCase().includes(st.filter))
    .sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * st.dir);
  const th = (k, label) => `<th data-k="${k}" ${st.key === k ? `aria-sort="${st.dir > 0 ? "ascending" : "descending"}"` : ""}>${label}${st.key === k ? (st.dir > 0 ? " ↑" : " ↓") : ""}</th>`;
  t.innerHTML = `<thead><tr>${th("title","Song")}${th("plays","Plays")}${th("album","Album")}<th>Song ID</th><th>Album ID</th><th>Artist IDs</th></tr></thead><tbody>` +
    rows.map(s => `<tr>
      <td class="song">${s.thumbnail ? `<img src="${esc(s.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ""}<span title="${esc(s.title)}">${esc(s.title)}</span></td>
      <td class="plays"><i style="width:${((s.plays || 0) / max * 100).toFixed(1)}%"></i><b title="${s.plays?.toLocaleString() ?? ""}">${esc(s.plays_text || fmt(s.plays))}</b></td>
      <td>${esc(s.album || "")}</td>
      <td><code data-copy="${esc(s.video_id)}">${esc(s.video_id)}</code></td>
      <td>${s.album_id ? `<code data-copy="${esc(s.album_id)}">${esc(s.album_id.slice(0, 14))}...</code>` : ""}</td>
      <td>${s.artists.filter(a => a.id).map(a => `<code data-copy="${esc(a.id)}" title="${esc(a.name)}">${esc(a.name)}</code>`).join(" ")}</td>
    </tr>`).join("") + "</tbody>";
}
