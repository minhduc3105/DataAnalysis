import csv
import json

from .common import now_iso
from .graph import GRAPH_DIR

VIEWER_PATH = GRAPH_DIR / "viewer.html"


def _read(name: str) -> list[dict]:
    with (GRAPH_DIR / name).open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def build() -> None:
    entities = [e for e in _read("entities.csv") if e["n_relations"] != "0"]
    keep = {e["entity_id"] for e in entities}
    evidence: dict[str, dict] = {}
    for ev in _read("evidence.csv"):
        evidence.setdefault(ev["relation_id"], ev)
    relations = []
    for r in _read("relations.csv"):
        if r["source_entity_id"] in keep and r["target_entity_id"] in keep:
            ev = evidence.get(r["relation_id"], {})
            relations.append([r["source_entity_id"], r["target_entity_id"], r["relation_type"], r["role_detail"], int(r["n_documents"] or 0), ev.get("quote", ""), ev.get("url", "")])
    nodes = [[e["entity_id"], e["entity_type"], e["canonical_name"], e["aliases"], e["verification_status"], int(e["n_relations"])] for e in entities]
    data = json.dumps({"nodes": nodes, "edges": relations, "built": now_iso()}, ensure_ascii=False, separators=(",", ":"))
    VIEWER_PATH.write_text(TEMPLATE.replace("__DATA__", data.replace("</", "<\\/")), encoding="utf-8")
    print(f"Đã tạo {VIEWER_PATH} ({len(nodes)} node, {len(relations)} cạnh); mở file bằng trình duyệt.")


TEMPLATE = """<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mạng lưới âm nhạc Việt</title>
<script src="https://unpkg.com/vis-network@9.1.9/standalone/umd/vis-network.min.js"></script>
<style>
:root { --bg:#fafafa; --panel:#fff; --text:#1f2328; --muted:#656d76; --line:#d0d7de; }
@media (prefers-color-scheme: dark) { :root { --bg:#0d1117; --panel:#161b22; --text:#e6edf3; --muted:#8d96a0; --line:#30363d; } }
* { box-sizing:border-box; }
body { margin:0; font:14px/1.45 system-ui, -apple-system, "Segoe UI", sans-serif; background:var(--bg); color:var(--text); display:flex; height:100vh; }
#side { width:340px; min-width:280px; border-right:1px solid var(--line); background:var(--panel); padding:14px; overflow:auto; }
#net { flex:1; }
h1 { font-size:16px; margin:0 0 8px; }
input[type=search] { width:100%; padding:8px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--text); }
.muted { color:var(--muted); font-size:12px; }
.types label { display:inline-block; margin:2px 8px 2px 0; font-size:12px; }
.legend span { display:inline-block; margin:2px 6px 2px 0; font-size:12px; }
.dot { display:inline-block; width:10px; height:10px; border-radius:50%; margin-right:4px; vertical-align:middle; }
#info { margin-top:12px; border-top:1px solid var(--line); padding-top:10px; }
#info a { color:#2f81f7; word-break:break-all; }
ul { padding-left:18px; margin:6px 0; }
li { margin:2px 0; cursor:pointer; }
button { padding:6px 10px; border:1px solid var(--line); border-radius:6px; background:var(--bg); color:var(--text); cursor:pointer; }
@media (max-width:700px) { body { flex-direction:column; } #side { width:auto; height:45vh; border-right:0; border-bottom:1px solid var(--line); } }
</style>
</head>
<body>
<div id="side">
  <h1>Mạng lưới âm nhạc Việt</h1>
  <div class="muted" id="stats"></div>
  <p><input type="search" id="q" list="names" placeholder="Tìm nghệ sĩ, bài hát, công ty…"><datalist id="names"></datalist></p>
  <div class="muted">Độ sâu: <label><input type="radio" name="depth" value="1" checked> 1 bước</label> <label><input type="radio" name="depth" value="2"> 2 bước (chỉ người–người)</label></div>
  <p class="types" id="types"></p>
  <div class="legend" id="legend"></div>
  <p><button id="top">Mạng hợp tác của 150 nghệ sĩ nhiều cạnh nhất</button></p>
  <div id="info" class="muted">Gõ tên rồi chọn trong danh sách. Bấm vào node để mở rộng, bấm vào cạnh để xem bằng chứng.</div>
</div>
<div id="net"></div>
<script>
const DATA = __DATA__;
const COLORS = {Person:"#2f81f7", Group:"#8957e5", Song:"#3fb950", Album:"#1a7f37", Company:"#d29922", Brand:"#f85149", Show:"#db61a2", Event:"#bf8700"};
const nodes = new Map(DATA.nodes.map(n => [n[0], {id:n[0], type:n[1], name:n[2], aliases:n[3], status:n[4], deg:n[5]}]));
const adj = new Map();
DATA.edges.forEach((e, i) => { [e[0], e[1]].forEach(k => { if (!adj.has(k)) adj.set(k, []); adj.get(k).push(i); }); });
const relTypes = [...new Set(DATA.edges.map(e => e[2]))].sort();
const active = new Set(relTypes);
document.getElementById("stats").textContent = `${nodes.size} node có cạnh · ${DATA.edges.length} cạnh · dựng lúc ${DATA.built}`;
document.getElementById("legend").innerHTML = Object.entries(COLORS).map(([t,c]) => `<span><i class="dot" style="background:${c}"></i>${t}</span>`).join("");
document.getElementById("types").innerHTML = relTypes.map(t => `<label><input type="checkbox" value="${t}" checked> ${t}</label>`).join("");
document.getElementById("names").innerHTML = [...nodes.values()].sort((a,b) => b.deg - a.deg).slice(0, 4000).map(n => `<option value="${n.name.replace(/"/g,'&quot;')}">${n.type}</option>`).join("");
const byName = new Map(); nodes.forEach(n => { const k = n.name.toLowerCase(); if (!byName.has(k) || byName.get(k).deg < n.deg) byName.set(k, n); });

const vn = new vis.DataSet(), ve = new vis.DataSet();
const net = new vis.Network(document.getElementById("net"), {nodes:vn, edges:ve}, {
  physics:{solver:"forceAtlas2Based", stabilization:{iterations:200, updateInterval:50}},
  nodes:{shape:"dot", font:{size:12, color:getComputedStyle(document.body).color}},
  edges:{arrows:{to:{enabled:true, scaleFactor:0.4}}, color:{opacity:0.45}, smooth:false},
  interaction:{hover:true, tooltipDelay:150}
});

// Chỉ chạy mô phỏng lực để sắp xếp rồi tắt, để graph đứng yên và node kéo đi đâu nằm đó.
net.on("stabilizationIterationsDone", () => net.setOptions({physics:false}));
function settle() { net.setOptions({physics:{enabled:true}}); net.stabilize(200); }
function addNode(id) { const n = nodes.get(id); if (!n || vn.get(id)) return; vn.add({id, label:n.name, color:COLORS[n.type], size:8 + Math.min(22, Math.sqrt(n.deg) * 2), title:`${n.type} · ${n.deg} cạnh`}); }
function addEdge(i) { const e = DATA.edges[i]; if (!active.has(e[2]) || ve.get(i)) return; addNode(e[0]); addNode(e[1]); ve.add({id:i, from:e[0], to:e[1], title:e[2], arrows: e[2] === "COLLABORATED_WITH" ? "" : "to", width: 1 + Math.min(4, e[4] / 3)}); }
function expand(id, depth) {
  addNode(id);
  (adj.get(id) || []).forEach(i => addEdge(i));
  if (depth > 1) (adj.get(id) || []).forEach(i => { const e = DATA.edges[i]; const o = e[0] === id ? e[1] : e[0]; const t = nodes.get(o).type; if (t === "Person" || t === "Group") (adj.get(o) || []).forEach(j => { const f = DATA.edges[j]; const p = f[0] === o ? f[1] : f[0]; const pt = nodes.get(p).type; if (pt === "Person" || pt === "Group") addEdge(j); }); });
}
function show(id) { vn.clear(); ve.clear(); expand(id, +document.querySelector("input[name=depth]:checked").value); net.once("stabilized", () => net.focus(id, {scale:1, animation:true})); settle(); info(id); }
function info(id) {
  const n = nodes.get(id); const rels = (adj.get(id) || []).map(i => DATA.edges[i]);
  const counts = {}; rels.forEach(e => counts[e[2]] = (counts[e[2]] || 0) + 1);
  document.getElementById("info").innerHTML = `<b>${n.name}</b> <span class="muted">(${n.type}, ${n.status}, ${n.id})</span>` +
    (n.aliases ? `<div class="muted">Tên khác: ${n.aliases}</div>` : "") +
    `<ul>${Object.entries(counts).map(([t,c]) => `<li>${t}: ${c}</li>`).join("")}</ul>` +
    `<div class="muted">Láng giềng (bấm để mở):</div><ul>${rels.slice(0, 60).map(e => { const o = e[0] === id ? e[1] : e[0]; return `<li data-id="${o}">${e[2]} — ${nodes.get(o).name}</li>`; }).join("")}</ul>`;
  document.querySelectorAll("#info li[data-id]").forEach(li => li.onclick = () => show(li.dataset.id));
}
document.getElementById("q").addEventListener("change", ev => { const n = byName.get(ev.target.value.trim().toLowerCase()); if (n) show(n.id); });
document.getElementById("types").addEventListener("change", ev => { ev.target.checked ? active.add(ev.target.value) : active.delete(ev.target.value); });
document.getElementById("top").onclick = () => {
  vn.clear(); ve.clear();
  const top = [...nodes.values()].filter(n => n.type === "Person" || n.type === "Group").sort((a,b) => b.deg - a.deg).slice(0, 150);
  const ids = new Set(top.map(n => n.id));
  DATA.edges.forEach((e, i) => { if (e[2] === "COLLABORATED_WITH" && ids.has(e[0]) && ids.has(e[1])) addEdge(i); });
  settle();
  document.getElementById("info").innerHTML = "Mạng COLLABORATED_WITH giữa 150 nghệ sĩ/nhóm có nhiều cạnh nhất. Bấm vào một node để xem chi tiết.";
};
net.on("click", p => {
  if (p.nodes.length) { const id = p.nodes[0]; const before = vn.length; expand(id, 1); if (vn.length > before) settle(); info(id); }
  else if (p.edges.length) { const e = DATA.edges[p.edges[0]];
    document.getElementById("info").innerHTML = `<b>${nodes.get(e[0]).name}</b> —${e[2]}→ <b>${nodes.get(e[1]).name}</b><div class="muted">${e[3]} · ${e[4]} tài liệu</div><p>“${e[5]}”</p>${e[6] ? `<a href="${e[6]}" target="_blank" rel="noopener">${e[6]}</a>` : ""}`; }
});
document.getElementById("top").click();
</script>
</body>
</html>
"""
