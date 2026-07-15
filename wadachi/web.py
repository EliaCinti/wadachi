"""
Wadachi Web — local brain graph visualization.

Usage:
    python -m wadachi.web              # opens http://localhost:8420
    python -m wadachi.web --port 9000  # custom port

Reads live from the brain dir (BRAIN_DIR, default ~/.wadachi — legacy ~/.engram still works).
No extra dependencies — uses Python's built-in http.server.
"""

import json
import os
import sys
import webbrowser
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from wadachi.store import MemoryStore


def get_graph_data(store: MemoryStore) -> dict:
    """Nodes + links dal VERO MemoryGraph: archi tipizzati, decisioni, tempo.

    Il grafo web non è più un'euristica sui tag: è la stessa struttura dati
    che alimenta recall associativo, why() e il sonno (Fase 7.B).
    """
    from wadachi.graph import MemoryGraph
    from wadachi.entities import EntityGraph

    g = MemoryGraph(store).build()
    eg = EntityGraph(store)
    if eg.graph_json.exists():
        try:
            g.load_entity_edges(str(eg.graph_json))
        except Exception:  # noqa: BLE001 — best-effort
            pass

    mem_meta = {m["id"]: m for m in store.list_memories()}
    dec_meta = {d["id"]: d for d in store.list_decisions(limit=100000)}

    def key(nid: int) -> str:
        return f"d{-nid}" if nid < 0 else f"m{nid}"

    nodes = []
    for nid, n in g.nodes.items():
        if n.ntype == "decision":
            d = dec_meta.get(-nid, {})
            nodes.append({
                "id": key(nid), "title": n.title[:70], "type": "decision",
                "project": d.get("project", "global"), "category": "",
                "tags": [], "created_at": d.get("created_at", ""),
                "why": d.get("rationale", ""),
                "alternatives": d.get("alternatives", ""),
                "context": d.get("context", ""),
                "preview": n.content[:200],
            })
        else:
            m = mem_meta.get(nid, {})
            nodes.append({
                "id": key(nid), "title": n.title, "type": "memory",
                "project": m.get("project", "global"), "category": n.category,
                "tags": n.tags, "created_at": m.get("created_at", ""),
                "preview": n.content[:220] + ("..." if len(n.content) > 220 else ""),
            })

    links = [{
        "source": key(e.src), "target": key(e.dst),
        "kind": e.kind, "rel": e.rel, "strength": round(e.weight, 2),
    } for e in g.edges]

    return {
        "nodes": nodes,
        "links": links,
        "stats": store.stats(),
        "graph_stats": {"citation": sum(1 for e in g.edges if e.kind == "citation"),
                        "semantic": sum(1 for e in g.edges if e.kind == "semantic"),
                        "entity": sum(1 for e in g.edges if e.kind == "entity")},
        "projects": [p["name"] for p in store.list_projects()],
    }


# ── HTML Template ─────────────────────────────────────────────

GRAPH_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>wadachi 轍 — Brain Graph</title>
<style>
  :root {
    --bg: #fafaf8; --bg2: #f0efe8; --bg3: #e8e7e0;
    --text: #2c2c2a; --text2: #5f5e5a; --text3: #888780;
    --border: rgba(0,0,0,0.1); --border2: rgba(0,0,0,0.06);
    --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1a1a1e; --bg2: #26262b; --bg3: #323238;
      --text: #e0dfd8; --text2: #9c9a92; --text3: #6e6d68;
      --border: rgba(255,255,255,0.1); --border2: rgba(255,255,255,0.05);
    }
  }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: var(--font); background: var(--bg); color: var(--text); }

  .header {
    padding: 20px 24px 16px;
    border-bottom: 0.5px solid var(--border);
    display: flex; align-items: center; justify-content: space-between;
  }
  .header h1 { font-size: 18px; font-weight: 500; letter-spacing: -0.3px; }
  .header .subtitle { font-size: 12px; color: var(--text3); margin-top: 2px; }

  .stats-bar {
    display: flex; gap: 24px; padding: 12px 24px;
    border-bottom: 0.5px solid var(--border2);
    font-size: 12px; color: var(--text3);
  }
  .stats-bar .stat-val { font-weight: 500; color: var(--text); margin-right: 4px; font-size: 14px; }

  .toolbar {
    display: flex; gap: 6px; padding: 12px 24px;
    border-bottom: 0.5px solid var(--border2);
    flex-wrap: wrap; align-items: center;
  }
  .toolbar .label { font-size: 11px; color: var(--text3); text-transform: uppercase; letter-spacing: 0.5px; margin-right: 4px; }
  .filter-btn {
    padding: 4px 12px; border-radius: 6px; border: 0.5px solid var(--border);
    background: transparent; color: var(--text2); cursor: pointer; font-size: 12px;
    font-family: var(--font); transition: all .15s;
  }
  .filter-btn:hover { border-color: var(--text3); }
  .filter-btn.active { background: var(--bg3); color: var(--text); border-color: var(--text3); }

  #graph-container {
    width: 100%; height: calc(100vh - 180px); min-height: 500px;
    position: relative; overflow: hidden;
  }
  #graph-container svg { width: 100%; height: 100%; }

  .detail-panel {
    position: absolute; top: 16px; right: 16px; width: 260px;
    background: var(--bg); border: 0.5px solid var(--border);
    border-radius: 10px; padding: 16px; font-size: 12px;
    opacity: 0; transition: opacity .2s; pointer-events: none;
    box-shadow: 0 4px 24px rgba(0,0,0,0.08);
  }
  @media (prefers-color-scheme: dark) {
    .detail-panel { box-shadow: 0 4px 24px rgba(0,0,0,0.3); }
  }
  .detail-panel.show { opacity: 1; pointer-events: auto; }
  .dp-close { position:absolute; top:8px; right:10px; cursor:pointer; color:var(--text3); font-size:16px; border:none; background:none; padding:4px; }
  .dp-close:hover { color: var(--text); }
  .dp-type { font-size:10px; color:var(--text3); text-transform:uppercase; letter-spacing:0.5px; margin-bottom:6px; }
  .dp-title { font-weight:500; font-size:14px; margin-bottom:8px; line-height:1.4; }
  .dp-project { font-size:11px; margin-bottom:8px; }
  .dp-project span { padding:2px 8px; border-radius:4px; background:var(--bg2); color:var(--text2); }
  .dp-tags { display:flex; flex-wrap:wrap; gap:4px; margin-bottom:10px; }
  .dp-tag { font-size:10px; padding:2px 6px; border-radius:4px; background:var(--bg2); color:var(--text3); }
  .dp-content { font-size:12px; color:var(--text2); line-height:1.6; max-height:200px; overflow-y:auto; white-space: pre-wrap; }
  .dp-content::-webkit-scrollbar { width:3px; }
  .dp-content::-webkit-scrollbar-thumb { background:var(--border); border-radius:3px; }

  .footer {
    padding: 8px 24px; border-top: 0.5px solid var(--border2);
    font-size: 11px; color: var(--text3);
    display: flex; justify-content: space-between; align-items: center;
  }
  .legend { display: flex; gap: 14px; align-items: center; }
  .legend-item { display:flex; align-items:center; gap:4px; }
  .legend-dot { width:8px; height:8px; border-radius:50%; }
  .legend-diamond { width:8px; height:8px; transform:rotate(45deg); border-radius:1px; }
</style>
</head>
<body>
  <div class="header">
    <div>
      <h1>wadachi 轍</h1>
      <div class="subtitle">Typed knowledge graph · citation / semantic / entity · time-aware</div>
    </div>
    <div style="font-size:11px;color:var(--text3)">
      <span id="search-mode"></span>
    </div>
  </div>

  <div class="stats-bar">
    <div><span class="stat-val" id="s-mem">0</span>memories</div>
    <div><span class="stat-val" id="s-dec">0</span>decisions</div>
    <div><span class="stat-val" id="s-proj">0</span>projects</div>
    <div><span class="stat-val" id="s-conn">0</span>connections</div>
  </div>

  <div class="toolbar">
    <span class="label">Project</span>
    <button class="filter-btn active" data-project="all">All</button>
    <span class="label" style="margin-left:18px">As of</span>
    <input type="range" id="timeline" min="0" max="1000" value="1000" style="width:150px;accent-color:#D9442B">
    <span id="timeline-label" style="font-size:11px;color:var(--text3);min-width:78px">oggi</span>
  </div>

  <div id="graph-container">
    <div class="detail-panel" id="detail">
      <button class="dp-close" onclick="hideDetail()">&times;</button>
      <div class="dp-type" id="dp-type"></div>
      <div class="dp-title" id="dp-title"></div>
      <div class="dp-project" id="dp-project"></div>
      <div class="dp-tags" id="dp-tags"></div>
      <div class="dp-content" id="dp-content"></div>
    </div>
  </div>

  <div class="footer">
    <div class="legend" id="legend"></div>
    <div>Scroll to zoom · Drag to rearrange · Hover for labels · Click for connections</div>
  </div>

<script src="https://cdnjs.cloudflare.com/ajax/libs/d3/7.8.5/d3.min.js"></script>
<script>
const PROJECT_COLORS = {
  feynotes:'#EF9F27', global:'#888780', laplacebo:'#378ADD',
  engram:'#97C459', 'math-tutor':'#D85A30'
};
const FALLBACK_COLOR = '#AFA9EC';
const DECISION_COLOR = '#D4537E';
const dark = matchMedia('(prefers-color-scheme:dark)').matches;

let allNodes, allLinks, sim, nodeEl, linkEl;
let currentProject = 'all', timeCutoff = null, dateMin = 0, dateMax = 0;

function linkColor(l) {
  if (l.rel === 'supersedes')  return '#D9442B';
  if (l.rel === 'contradicts') return '#E08A00';
  if (l.kind === 'citation')   return dark ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.35)';
  if (l.kind === 'entity')     return dark ? 'rgba(151,196,89,0.4)'  : 'rgba(110,150,60,0.35)';
  return dark ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.09)';   /* semantic: tessuto di fondo */
}
function linkDash(l) {
  if (l.rel === 'contradicts') return '4,3';
  if (l.kind === 'entity')     return '2,3';
  return null;
}
function linkWidth(l) {
  return l.rel === 'supersedes' ? 2.4 : Math.max(0.8, Math.min(l.strength * 1.2, 3));
}
function nodeVisible(d) {
  if (currentProject !== 'all' && d.project !== currentProject) return false;
  if (timeCutoff && d.created_at && new Date(d.created_at).getTime() > timeCutoff) return false;
  return true;
}
function applyFilters() {
  hideDetail();
  nodeEl.attr('display', d => nodeVisible(d) ? null : 'none');
  linkEl.attr('display', l => {
    const s = typeof l.source==='object' ? l.source : allNodes.find(n=>n.id===l.source);
    const t = typeof l.target==='object' ? l.target : allNodes.find(n=>n.id===l.target);
    return (s && t && nodeVisible(s) && nodeVisible(t)) ? null : 'none';
  });
  sim.alpha(0.25).restart();
}

fetch('/api/graph').then(r=>r.json()).then(data => {
  allNodes = data.nodes;
  allLinks = data.links;

  // Stats
  document.getElementById('s-mem').textContent = data.stats.memories;
  document.getElementById('s-dec').textContent = data.stats.decisions;
  document.getElementById('s-proj').textContent = data.stats.projects;
  document.getElementById('s-conn').textContent = allLinks.length;

  // Project filter buttons
  const toolbar = document.querySelector('.toolbar');
  data.projects.forEach(p => {
    const btn = document.createElement('button');
    btn.className = 'filter-btn';
    btn.dataset.project = p;
    btn.textContent = p;
    btn.addEventListener('click', () => filterProject(p));
    toolbar.appendChild(btn);
  });

  // Legend
  const legend = document.getElementById('legend');
  data.projects.forEach(p => {
    const c = PROJECT_COLORS[p] || FALLBACK_COLOR;
    legend.innerHTML += '<span class="legend-item"><span class="legend-dot" style="background:'+c+'"></span>'+p+'</span>';
  });
  legend.innerHTML += '<span class="legend-item"><span class="legend-diamond" style="background:'+DECISION_COLOR+';opacity:.7"></span>decision</span>';
  legend.innerHTML += '<span class="legend-item"><span style="display:inline-block;width:16px;height:0;border-top:2.4px solid #D9442B"></span>supersedes</span>';
  legend.innerHTML += '<span class="legend-item"><span style="display:inline-block;width:16px;height:0;border-top:2px dashed #E08A00"></span>contradicts</span>';
  legend.innerHTML += '<span class="legend-item"><span style="display:inline-block;width:16px;height:0;border-top:1.5px solid '+(dark?'rgba(255,255,255,0.45)':'rgba(0,0,0,0.35)')+'"></span>citation</span>';

  // Timeline as_of: la dimensione temporale del grafo
  const dates = allNodes.map(n => n.created_at ? new Date(n.created_at).getTime() : null).filter(Boolean);
  dateMin = Math.min(...dates); dateMax = Math.max(...dates);
  const tl = document.getElementById('timeline');
  tl.addEventListener('input', () => {
    const f = tl.value / 1000;
    timeCutoff = f >= 1 ? null : dateMin + (dateMax - dateMin) * f;
    document.getElementById('timeline-label').textContent =
      timeCutoff ? new Date(timeCutoff).toISOString().slice(0,10) : 'oggi';
    applyFilters();
  });

  buildGraph();
});

document.querySelector('[data-project="all"]').addEventListener('click', () => filterProject('all'));

function buildGraph() {
  const container = document.getElementById('graph-container');
  const W = container.clientWidth, H = container.clientHeight;

  const svg = d3.select('#graph-container').append('svg').attr('viewBox', `0 0 ${W} ${H}`);
  const g = svg.append('g');
  svg.call(d3.zoom().scaleExtent([0.2, 4]).on('zoom', e => g.attr('transform', e.transform)));

  // Project cluster positions — spread projects into quadrants
  const projList = [...new Set(allNodes.map(n=>n.project))];
  const projPositions = {};
  projList.forEach((p,i) => {
    const angle = (i / projList.length) * 2 * Math.PI - Math.PI/2;
    projPositions[p] = { x: W/2 + Math.cos(angle)*W*0.22, y: H/2 + Math.sin(angle)*H*0.22 };
  });

  sim = d3.forceSimulation(allNodes)
    .force('link', d3.forceLink(allLinks).id(d=>d.id).distance(d => 110/(d.strength+0.3)).strength(d => Math.min(d.strength*0.1, 0.3)))
    .force('charge', d3.forceManyBody().strength(-220))
    .force('center', d3.forceCenter(W/2, H/2).strength(0.05))
    .force('collision', d3.forceCollide().radius(d => (d.type==='decision'?8:12)+30))
    .force('clusterX', d3.forceX(d => (projPositions[d.project]||{x:W/2}).x).strength(0.12))
    .force('clusterY', d3.forceY(d => (projPositions[d.project]||{y:H/2}).y).strength(0.12));

  linkEl = g.append('g').selectAll('line').data(allLinks).join('line')
    .attr('stroke', linkColor)
    .attr('stroke-dasharray', linkDash)
    .attr('stroke-width', linkWidth);

  nodeEl = g.append('g').selectAll('g').data(allNodes).join('g')
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (e,d) => { if(!e.active) sim.alphaTarget(0.3).restart(); d.fx=d.x; d.fy=d.y; })
      .on('drag', (e,d) => { d.fx=e.x; d.fy=e.y; })
      .on('end', (e,d) => { if(!e.active) sim.alphaTarget(0); d.fx=null; d.fy=null; })
    );

  nodeEl.each(function(d) {
    const el = d3.select(this);
    if (d.type === 'decision') {
      el.append('rect').attr('class','node-shape')
        .attr('width', 12).attr('height', 12).attr('x', -6).attr('y', -6)
        .attr('rx', 2).attr('transform', 'rotate(45)')
        .attr('fill', DECISION_COLOR).attr('opacity', 0.75)
        .attr('stroke', dark?'rgba(255,255,255,0.2)':'rgba(0,0,0,0.12)')
        .attr('stroke-width', 0.5);
    } else {
      el.append('circle').attr('class','node-shape')
        .attr('r', 10)
        .attr('fill', PROJECT_COLORS[d.project] || FALLBACK_COLOR)
        .attr('opacity', 0.9)
        .attr('stroke', dark?'rgba(255,255,255,0.2)':'rgba(0,0,0,0.12)')
        .attr('stroke-width', 0.5);
    }
  });

  // Labels hidden by default — appear on hover or when node is selected
  const labelG = nodeEl.append('g').attr('class','node-label')
    .style('opacity', 0).style('pointer-events','none')
    .style('transition','opacity 0.15s');

  labelG.append('rect').attr('class','label-bg')
    .attr('x', d => d.type==='decision'?11:14).attr('y', -10).attr('rx', 4)
    .attr('height', 20).attr('width', d => d.title.length * 6.5 + 14)
    .attr('fill', dark ? 'rgba(26,26,30,0.88)' : 'rgba(255,255,255,0.92)')
    .attr('stroke', dark ? 'rgba(255,255,255,0.1)' : 'rgba(0,0,0,0.08)')
    .attr('stroke-width', 0.5);

  labelG.append('text')
    .text(d => d.title)
    .attr('x', d => d.type==='decision'?18:21).attr('y', 4)
    .attr('font-size','12.5px').attr('font-family','var(--font)').attr('font-weight','450')
    .attr('fill', dark ? 'rgba(255,255,255,0.9)' : 'rgba(0,0,0,0.8)');

  // Hover: show label
  nodeEl.on('mouseenter', function() {
    if (activeNode) return;
    d3.select(this).select('.node-label').style('opacity', 1);
    d3.select(this).select('.node-shape').attr('stroke-width', 2);
  });
  nodeEl.on('mouseleave', function() {
    if (activeNode) return;
    d3.select(this).select('.node-label').style('opacity', 0);
    d3.select(this).select('.node-shape').attr('stroke-width', 0.5);
  });

  nodeEl.on('click', (e,d) => { e.stopPropagation(); showDetail(d); });
  svg.on('click', () => hideDetail());

  sim.on('tick', () => {
    linkEl.attr('x1',d=>d.source.x).attr('y1',d=>d.source.y).attr('x2',d=>d.target.x).attr('y2',d=>d.target.y);
    nodeEl.attr('transform', d => `translate(${d.x},${d.y})`);
  });
}

let activeNode = null;

function showDetail(d) {
  activeNode = d.id;
  document.getElementById('dp-type').textContent = d.type + (d.category ? ' \u00b7 ' + d.category : '');
  document.getElementById('dp-title').textContent = d.title;
  document.getElementById('dp-project').innerHTML = '<span>' + d.project + '</span>';
  document.getElementById('dp-tags').innerHTML = (d.tags||[]).map(t => '<span class="dp-tag">'+t+'</span>').join('');
  if (d.type === 'decision') {
    let s = '';
    if (d.why) s += 'PERCH\u00c9\\n' + d.why + '\\n\\n';
    if (d.alternatives) s += 'ALTERNATIVE SCARTATE\\n' + d.alternatives + '\\n\\n';
    if (d.context) s += 'CONTESTO\\n' + d.context;
    document.getElementById('dp-content').textContent = s || d.preview;
  } else {
    document.getElementById('dp-content').textContent = d.preview;
  }
  document.getElementById('detail').classList.add('show');

  const connected = new Set([d.id]);
  allLinks.forEach(l => {
    const sid = typeof l.source==='object' ? l.source.id : l.source;
    const tid = typeof l.target==='object' ? l.target.id : l.target;
    if (sid===d.id) connected.add(tid);
    if (tid===d.id) connected.add(sid);
  });

  const nodeColor = PROJECT_COLORS[d.project] || FALLBACK_COLOR;
  nodeEl.select('.node-shape')
    .attr('opacity', n => connected.has(n.id) ? 1 : 0.1)
    .attr('stroke-width', n => n.id===d.id ? 2.5 : (connected.has(n.id) ? 1.5 : 0.5));
  nodeEl.select('.node-label').style('opacity', n => connected.has(n.id) ? 1 : 0);

  linkEl
    .attr('stroke', l => {
      const sid = typeof l.source==='object' ? l.source.id : l.source;
      const tid = typeof l.target==='object' ? l.target.id : l.target;
      return (sid===d.id || tid===d.id) ? nodeColor : linkColor(l);
    })
    .attr('stroke-width', l => {
      const sid = typeof l.source==='object' ? l.source.id : l.source;
      const tid = typeof l.target==='object' ? l.target.id : l.target;
      return (sid===d.id || tid===d.id) ? 2.5 : Math.max(0.8, Math.min(l.strength * 1.2, 3));
    })
    .attr('opacity', l => {
      const sid = typeof l.source==='object' ? l.source.id : l.source;
      const tid = typeof l.target==='object' ? l.target.id : l.target;
      return (sid===d.id || tid===d.id) ? 0.8 : 0.03;
    });
}

function hideDetail() {
  activeNode = null;
  document.getElementById('detail').classList.remove('show');
  nodeEl.select('.node-shape').attr('opacity', d => d.type==='decision' ? 0.75 : 0.9).attr('stroke-width', 0.5);
  nodeEl.select('.node-label').style('opacity', 0);
  linkEl
    .attr('stroke', linkColor)
    .attr('stroke-dasharray', linkDash)
    .attr('stroke-width', linkWidth)
    .attr('opacity', 1);
}

function filterProject(proj) {
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  document.querySelector(`[data-project="${proj}"]`).classList.add('active');
  currentProject = proj;
  applyFilters();
}
</script>
</body>
</html>"""


class BrainHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for the brain graph."""

    store: MemoryStore = None  # set before serving

    def do_GET(self):
        path = urlparse(self.path).path

        if path == "/" or path == "/graph":
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(GRAPH_HTML.encode("utf-8"))

        elif path == "/api/graph":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            data = get_graph_data(self.store)
            self.wfile.write(json.dumps(data).encode("utf-8"))

        elif path == "/api/stats":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(self.store.stats()).encode("utf-8"))

        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not found")

    def log_message(self, format, *args):
        """Cleaner log output."""
        msg = format % args
        if "GET /api/" not in msg:  # don't spam API calls
            print(f"  {msg}")


def main():
    parser = argparse.ArgumentParser(description="wadachi brain graph viewer")
    parser.add_argument("--port", type=int, default=8420, help="Port (default: 8420)")
    parser.add_argument("--no-open", action="store_true", help="Don't auto-open browser")
    args = parser.parse_args()

    store = MemoryStore()
    BrainHandler.store = store

    stats = store.stats()
    server = HTTPServer(("127.0.0.1", args.port), BrainHandler)

    print(f"""
┌─────────────────────────────────────────┐
│        轍  w a d a c h i  轍            │
│          Brain graph viewer             │
├─────────────────────────────────────────┤
│  Memories:    {stats['memories']:<4}                     │
│  Decisions:   {stats['decisions']:<4}                     │
│  Projects:    {stats['projects']:<4}                     │
│  Brain dir:   {str(store.brain_dir):<25}│
├─────────────────────────────────────────┤
│  → http://localhost:{args.port}/graph           │
│  Press Ctrl+C to stop                   │
└─────────────────────────────────────────┘
""")

    if not args.no_open:
        webbrowser.open(f"http://localhost:{args.port}/graph")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Shutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
