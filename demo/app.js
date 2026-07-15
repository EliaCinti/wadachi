/* ── wadachi 轍 landing — sumi-style hero ──────────────────────────
   A designed hub-and-spoke knowledge graph (SVG) that SELF-ASSEMBLES
   when it scrolls into view, reacts to the cursor (nodes repel with a
   springy jelly), then lives (particle flow + halo breathing). Plus a
   decoding headline, a terminal recall ticker, and faint glyph rain.
   Sumi palette: ink #E8E4DC on paper-night, vermilion seal #D9442B.
   The blur layer reads as nijimi — ink bleeding into the paper.
   Pure vanilla JS — no external libs.                                 */

(function () {
  "use strict";

  var V = "#E8E4DC" /* ink */, C = "#D9442B" /* vermilion */;
  var CAT = {
    architecture: "#8FA3B8", bugfix: "#C96A5A", config: "#C9972C",
    pattern: "#A08BB8", context: "#7A8B5E", reference: "#6FA3A0",
    decision: "#D0B054", entity: "#8A857B",
  };
  var reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;
  var SVGNS = "http://www.w3.org/2000/svg";
  var T0 = performance.now();
  var now = function () { return (performance.now() - T0) / 1000; };

  // ── 1 · curated graph model (hub → ring1 → ring2 + decisions) ───
  var W = 920, H = 680, cx = W * 0.60, cy = H / 2;
  var nodes = [], edges = [];

  function addNode(o) { o.id = nodes.length; nodes.push(o); return o.id; }

  // central hub
  var hub = addNode({ x: cx, y: cy, r: 13, color: C, label: "get_context", kind: "hub" });

  // ring 1 — the cognitive faculties
  var ring1Defs = [
    { label: "recall", cat: "reference" },
    { label: "decisions", cat: "decision" },
    { label: "constellation", cat: "entity" },
    { label: "beliefs", cat: "pattern" },
    { label: "reflect", cat: "context" },
    { label: "procedural", cat: "config" },
  ];
  var ring1 = [];
  ring1Defs.forEach(function (d, i) {
    var a = (i / ring1Defs.length) * Math.PI * 2 - Math.PI / 2;
    var id = addNode({
      x: cx + Math.cos(a) * 158, y: cy + Math.sin(a) * 158,
      r: 7.5, color: V, label: d.label, kind: "r1", ang: a,
    });
    ring1.push(id); edges.push({ a: hub, b: id, main: true });
  });

  // ring 2 — memories hanging off each faculty
  var leafLabels = [
    "CRDT merge", "Yjs vs Automerge", "WS reconnect", "Redis pub/sub",
    "schema v3", "auth token TTL", "rate-limit 429", "snapshot GC",
    "vector index", "cold-start fix", "Node 18 EOL", "p95 latency",
    "OKF export", "belief review", "sleep report", "embed cache",
    "wikilink parse", "index rebuild",
  ];
  var li = 0;
  ring1.forEach(function (pid, k) {
    var p = nodes[pid];
    var count = 3;
    for (var j = 0; j < count; j++) {
      var spread = 0.40;
      var a = p.ang + (j - (count - 1) / 2) * spread;
      var cat = ring1Defs[k].cat;
      var id = addNode({
        x: cx + Math.cos(a) * 272, y: cy + Math.sin(a) * 272,
        r: 4.6, color: CAT[cat] || V, label: leafLabels[li % leafLabels.length],
        kind: "r2",
      });
      li++;
      edges.push({ a: pid, b: id });
    }
  });
  // a few cross-links so it reads as a graph, not a tree
  edges.push({ a: ring1[0], b: ring1[1], cross: true });
  edges.push({ a: ring1[2], b: ring1[3], cross: true });
  edges.push({ a: ring1[4], b: ring1[5], cross: true });
  edges.push({ a: ring1[1], b: ring1[4], cross: true });
  edges.push({ a: ring1[0], b: ring1[3], cross: true });
  edges.push({ a: ring1[2], b: ring1[5], cross: true });

  // typed DECISION nodes (diamonds) — provenance is part of the graph
  var leafPreviews = [
    "CRDT merge strategy for the shared doc layer — chosen after the D3 benchmark.",
    "Yjs vs Automerge: payload 4x smaller, merge 3x faster on our doc sizes.",
    "WS reconnect with exponential backoff — fixed the mobile drop bug.",
    "Redis pub/sub fan-out keeps sync under the 80ms budget.",
    "Schema v3: soft-delete columns everywhere, migrations with backup.",
    "Auth token TTL bumped to 24h after the refresh-storm incident.",
    "Rate-limit 429 handling: retry with jitter, max 3 attempts.",
    "Snapshot GC runs nightly; keeps the last 30 days.",
    "Vector index rebuilt incrementally — full rebuild only on schema change.",
    "Cold-start fix: model preloaded at boot, first query 8x faster.",
    "Node 18 EOL: CI still on it — flagged stale by review_beliefs.",
    "p95 latency budget is 80ms end-to-end, measured at the gateway.",
    "The whole brain exports as an OKF bundle — plain markdown, portable.",
    "review_beliefs flagged 2 memories past their valid-until date.",
    "Last sleep run proposed merging 3 near-duplicate deploy notes.",
    "Embeddings cached in SQLite — recomputed only when content changes.",
    "[[wikilinks]] resolve to graph edges; the vault opens in Obsidian.",
    "index.md regenerated on every store — the wiki catalog stays fresh.",
  ];
  nodes.forEach(function (n, i) {
    if (n.kind === "r2") n.preview = leafPreviews[(i + leafPreviews.length) % leafPreviews.length];
    if (n.kind === "hub") n.preview = "One call loads project, memories, decisions and what needs review.";
    if (n.kind === "r1") n.preview = "Cognitive faculty — click-through in the real brain.";
  });

  var decDefs = [
    { label: "D3 · Yjs over Automerge", near: 1,
      preview: "WHY: smaller payload, faster merge. REJECTED: Automerge (memory footprint). Ask why() and the graph answers." },
    { label: "D7 · SQLite, not Postgres", near: 5,
      preview: "WHY: local-first, zero-config, one file. REJECTED: Postgres (overkill at this scale)." },
  ];
  var decIds = [];
  decDefs.forEach(function (d, i) {
    var pnode = nodes[ring1[d.near]];
    var a = pnode.ang + (i === 0 ? -0.62 : 0.62);
    var id = addNode({
      x: cx + Math.cos(a) * 252, y: cy + Math.sin(a) * 252,
      r: 6.2, color: CAT.decision, label: d.label, kind: "dec",
      preview: d.preview,
    });
    decIds.push(id);
    edges.push({ a: ring1[d.near], b: id });
  });
  // supersedes: la decisione D3 supera una vecchia memoria (arco vermiglio)
  edges.push({ a: decIds[0], b: ring1[0] + 1, rel: "supersedes" });

  // reveal order: hub, then ring1, then ring2
  var nodeOrder = nodes.map(function (n) { return n.id; });
  nodeOrder.sort(function (a, b) {
    var rank = { hub: 0, r1: 1, r2: 2, dec: 2 };
    return rank[nodes[a].kind] - rank[nodes[b].kind];
  });

  // ── 2 · render SVG skeleton ─────────────────────────────────────
  function mk(t) { return document.createElementNS(SVGNS, t); }

  var svg = document.getElementById("hero-svg");
  if (!svg) return;
  var gGlow = mk("g"), gEdges = mk("g"), gParticles = mk("g"), gNodes = mk("g");
  gGlow.style.filter = "blur(9px)";          // soft neon bloom layer, beneath all
  svg.appendChild(gGlow); svg.appendChild(gEdges); svg.appendChild(gParticles); svg.appendChild(gNodes);
  svg.style.transformOrigin = "50% 48%";
  svg.style.willChange = "transform";

  // dynamic per-node state: offset (ox,oy) + velocity (vx,vy) for repulsion
  nodes.forEach(function (n) { n.ox = 0; n.oy = 0; n.vx = 0; n.vy = 0; n.vis = 0; });

  // edges — plain lines, opacity-revealed, endpoints follow displaced nodes
  edges.forEach(function (e) {
    var ln = mk("line");
    ln.setAttribute("stroke", e.rel === "supersedes" ? "rgba(217,68,43,0.85)"
                    : e.cross ? "rgba(217,68,43,0.45)" : "rgba(232,228,220,0.45)");
    ln.setAttribute("stroke-width", e.rel === "supersedes" ? 1.8 : e.main ? 1.4 : 0.9);
    ln.setAttribute("stroke-linecap", "round");
    ln.setAttribute("opacity", "0");
    e.el = ln; e.vis = 0;
    gEdges.appendChild(ln);
    // one travelling particle per edge
    var pt = mk("circle");
    pt.setAttribute("r", e.main ? 2.2 : 1.6);
    pt.setAttribute("fill", (e.cross || e.rel === "supersedes") ? C : V);
    pt.setAttribute("opacity", "0");
    e.particle = pt; e.pPhase = Math.random();
    gParticles.appendChild(pt);
  });

  // nodes — bloom blob (blurred layer) + crisp group (halo, core, ring, label)
  nodes.forEach(function (n) {
    var glow = mk("circle");
    glow.setAttribute("r", n.r * 2.4); glow.setAttribute("fill", n.color);
    glow.setAttribute("opacity", "0");
    gGlow.appendChild(glow); n.glowEl = glow;

    var g = mk("g");
    g.setAttribute("class", "gnode");
    g.style.opacity = 0;
    g.style.transformOrigin = "0 0";           // scale about the node centre
    // halo
    var halo = mk("circle");
    halo.setAttribute("r", n.r + 6); halo.setAttribute("fill", n.color); halo.setAttribute("opacity", "0.14");
    g.appendChild(halo);
    // core
    var core = mk("circle");
    core.setAttribute("r", n.r); core.setAttribute("fill", n.color);
    g.appendChild(core);
    // decisioni: rombo al posto del cerchio
    if (n.kind === "dec") {
      core.setAttribute("transform", "rotate(45)");
      core.remove();
      var rect = mk("rect");
      rect.setAttribute("x", -n.r); rect.setAttribute("y", -n.r);
      rect.setAttribute("width", n.r * 2); rect.setAttribute("height", n.r * 2);
      rect.setAttribute("rx", 1.5); rect.setAttribute("transform", "rotate(45)");
      rect.setAttribute("fill", n.color);
      g.insertBefore(rect, halo.nextSibling);
    }
    // ring + label for hub/r1/dec
    if (n.kind !== "r2") {
      if (n.kind !== "dec") {
        var rg = mk("circle");
        rg.setAttribute("r", n.r + 3); rg.setAttribute("fill", "none");
        rg.setAttribute("stroke", n.color); rg.setAttribute("stroke-width", "1"); rg.setAttribute("opacity", "0.5");
        g.appendChild(rg);
      }
      var tx = mk("text");
      tx.textContent = n.label;
      tx.setAttribute("x", 0); tx.setAttribute("y", n.r + 15);
      tx.setAttribute("text-anchor", "middle");
      tx.setAttribute("class", "glabel " + (n.kind === "hub" ? "hub" : ""));
      g.appendChild(tx);
    }
    n.g = g; n.halo = halo;
    gNodes.appendChild(g);
  });

  // ── 3 · autonomous build timeline ───────────────────────────────
  var counterEl = document.getElementById("node-count");
  var progressEl = document.getElementById("build-progress");

  var LEAD = 480;      // ms before the first node appears
  var STAGGER = 120;   // ms between successive nodes
  var POP = 600;       // ms for one node / edge to ease in
  nodeOrder.forEach(function (id, i) { nodes[id].revealAt = LEAD + i * STAGGER; });
  edges.forEach(function (e) { e.revealAt = Math.max(nodes[e.a].revealAt, nodes[e.b].revealAt) + 80; });
  var BUILD_MS = LEAD + nodes.length * STAGGER + POP;

  var buildStart = null;
  function startBuild() { if (buildStart === null) buildStart = performance.now(); }

  function smooth(x) { return x <= 0 ? 0 : x >= 1 ? 1 : x * x * (3 - 2 * x); }
  function outBack(x) { if (x >= 1) return 1; var c1 = 1.70158, c3 = c1 + 1, y = x - 1; return 1 + c3 * y * y * y + c1 * y * y; }
  function nodeVis(n) {
    if (reduce) return 1;
    if (buildStart === null) return 0;
    return Math.min(1, Math.max(0, (performance.now() - buildStart - n.revealAt) / POP));
  }

  // ── 4 · cursor repulsion + subtle parallax lean ─────────────────
  var cur = { x: 0, y: 0, on: false };
  function toSvg(clientX, clientY) {
    var r = svg.getBoundingClientRect();
    return { x: (clientX - r.left) / r.width * W, y: (clientY - r.top) / r.height * H };
  }
  var tip = document.getElementById("node-tip");
  function updateTip(ev) {
    if (!tip) return;
    var best = null, bd = 30;
    nodes.forEach(function (n) {
      if (n.vis < 0.8) return;
      var dx = (n.x + n.ox) - cur.x, dy = (n.y + n.oy) - cur.y;
      var d = Math.sqrt(dx * dx + dy * dy);
      if (d < bd) { bd = d; best = n; }
    });
    if (best && best.preview) {
      tip.innerHTML = '<div class="tip-kind">' + (best.kind === "dec" ? "decision" : best.kind === "hub" ? "tool" : "memory") + '</div>' +
                      '<div class="tip-title">' + best.label + '</div>' +
                      '<div class="tip-body">' + best.preview + '</div>';
      tip.style.left = Math.min(ev.clientX + 16, innerWidth - 300) + "px";
      tip.style.top = (ev.clientY + 14) + "px";
      tip.classList.add("show");
    } else {
      tip.classList.remove("show");
    }
  }
  if (!reduce) {
    svg.addEventListener("pointermove", function (ev) {
      var c = toSvg(ev.clientX, ev.clientY); cur.x = c.x; cur.y = c.y; cur.on = true;
      updateTip(ev);
    }, { passive: true });
    svg.addEventListener("pointerleave", function () {
      cur.on = false;
      if (tip) tip.classList.remove("show");
    });
  }
  var pxTgt = 0, pyTgt = 0, pxCur = 0, pyCur = 0;
  if (!reduce) addEventListener("pointermove", function (ev) {
    pxTgt = (ev.clientX / window.innerWidth - 0.5) * 2;
    pyTgt = (ev.clientY / window.innerHeight - 0.5) * 2;
  }, { passive: true });

  var REP_R = 58, REP_PUSH = 0.7, SPRING = 0.11, DAMP = 0.84;

  function frame() {
    var t = now();
    var built = reduce ? 1 : (buildStart === null ? 0 : smooth(Math.min(1, (performance.now() - buildStart) / BUILD_MS)));
    var visCount = 0;

    // nodes: reveal + repulsion physics + draw
    nodes.forEach(function (n) {
      n.vis = nodeVis(n);
      if (n.vis > 0.5) visCount++;

      if (reduce) { n.ox = 0; n.oy = 0; }
      else {
        var fx = -SPRING * n.ox, fy = -SPRING * n.oy;
        if (cur.on && n.vis > 0.05) {
          var dx = (n.x + n.ox) - cur.x, dy = (n.y + n.oy) - cur.y;
          var d = Math.sqrt(dx * dx + dy * dy) || 0.001;
          if (d < REP_R) { var force = (1 - d / REP_R) * REP_PUSH; fx += dx / d * force; fy += dy / d * force; }
        }
        n.vx = (n.vx + fx) * DAMP; n.vy = (n.vy + fy) * DAMP;
        n.ox += n.vx; n.oy += n.vy;
      }

      var X = n.x + n.ox, Y = n.y + n.oy;
      var sc = 0.2 + 0.8 * outBack(n.vis);
      n.g.style.opacity = Math.min(1, n.vis * 1.3);
      n.g.style.transform = "translate(" + X.toFixed(2) + "px," + Y.toFixed(2) + "px) scale(" + sc.toFixed(3) + ")";
      var breathe = 0.1 + 0.09 * (0.5 + 0.5 * Math.sin(t * 1.7 + n.id));
      n.halo.setAttribute("opacity", (breathe * n.vis).toFixed(3));
      var gb = n.kind === "hub" ? 0.6 : n.kind === "r1" ? 0.42 : 0.3;
      n.glowEl.setAttribute("cx", X.toFixed(2)); n.glowEl.setAttribute("cy", Y.toFixed(2));
      n.glowEl.setAttribute("opacity", (gb * n.vis).toFixed(3));
    });

    // edges: follow displaced endpoints, reveal by opacity, flow particles
    edges.forEach(function (ed) {
      var na = nodes[ed.a], nb = nodes[ed.b];
      var ev = reduce ? 1 : (buildStart === null ? 0 : Math.min(1, Math.max(0, (performance.now() - buildStart - ed.revealAt) / POP)));
      ed.vis = ev;
      var ax = na.x + na.ox, ay = na.y + na.oy, bx = nb.x + nb.ox, by = nb.y + nb.oy;
      ed.el.setAttribute("x1", ax.toFixed(2)); ed.el.setAttribute("y1", ay.toFixed(2));
      ed.el.setAttribute("x2", bx.toFixed(2)); ed.el.setAttribute("y2", by.toFixed(2));
      ed.el.setAttribute("opacity", smooth(ev).toFixed(3));
      if (reduce || ev < 0.9) { ed.particle.setAttribute("opacity", "0"); return; }
      var f = (t * (ed.main ? 0.28 : 0.2) + ed.pPhase) % 1;
      ed.particle.setAttribute("cx", (ax + (bx - ax) * f).toFixed(2));
      ed.particle.setAttribute("cy", (ay + (by - ay) * f).toFixed(2));
      ed.particle.setAttribute("opacity", (0.85 * Math.sin(f * Math.PI)).toFixed(2));
    });

    if (counterEl) counterEl.textContent = visCount;
    if (progressEl) progressEl.style.width = (built * 100).toFixed(1) + "%";

    // subtle whole-graph lean toward the pointer + micro push-in while building
    var s = reduce ? 1 : (0.965 + 0.035 * built);
    if (!reduce) { pxCur += (pxTgt - pxCur) * 0.06; pyCur += (pyTgt - pyCur) * 0.06; }
    svg.style.transform = "translate(" + (-pxCur * 9).toFixed(1) + "px," + (-pyCur * 7).toFixed(1) + "px) scale(" + s.toFixed(3) + ")";
    gGlow.style.transform = "translate(" + (-pxCur * 5).toFixed(1) + "px," + (-pyCur * 4).toFixed(1) + "px)";

    requestAnimationFrame(frame);
  }
  requestAnimationFrame(frame);

  // kick off the build when the hero enters view (fallback timer too)
  if (!reduce) {
    var heroEl = document.getElementById("top");
    if ("IntersectionObserver" in window && heroEl) {
      var io = new IntersectionObserver(function (ents) {
        ents.forEach(function (en) { if (en.isIntersecting) { startBuild(); io.disconnect(); } });
      }, { threshold: 0.3 });
      io.observe(heroEl);
    }
    setTimeout(startBuild, 900);
  }

  // ── Apple-style: light up the key word in each section title on view ──
  (function () {
    var hls = [].slice.call(document.querySelectorAll("h2 .hl"));
    if (!hls.length) return;
    if (reduce || !("IntersectionObserver" in window)) {
      hls.forEach(function (el) { el.classList.add("lit"); });
      return;
    }
    var hlIO = new IntersectionObserver(function (ents) {
      ents.forEach(function (en) {
        if (en.isIntersecting) { en.target.classList.add("lit"); hlIO.unobserve(en.target); }
      });
    }, { threshold: 0.9, rootMargin: "0px 0px -10% 0px" });
    hls.forEach(function (el) { hlIO.observe(el); });
  })();

  // ── 5 · hero headline — words blur-in, then the key word lights up ──
  (function () {
    var h1 = document.getElementById("hero-h1");
    if (!h1) return;
    var words = [].slice.call(h1.querySelectorAll(".w"));
    var key = h1.querySelector(".hl");
    if (reduce || !words.length) {
      h1.classList.add("in"); if (key) key.classList.add("lit"); return;
    }
    words.forEach(function (w, i) { w.style.animationDelay = (140 + i * 95) + "ms"; });
    requestAnimationFrame(function () { requestAnimationFrame(function () { h1.classList.add("in"); }); });
    setTimeout(function () { if (key) key.classList.add("lit"); }, 140 + words.length * 95 + 640);
  })();

  // ── 6 · terminal recall ticker ──────────────────────────────────
  (function () {
    var qEl = document.getElementById("term-q");
    var rEl = document.getElementById("term-results");
    if (!qEl || !rEl) return;
    var QUERIES = [
      { q: 'recall("why Yjs over Automerge?")', r: [
        ["#D0B054", "decision_03 → Yjs: smaller payload, faster merge"],
        ["#8FA3B8", "architecture_11 ↔ CRDT layer mentions Yjs"],
        ["#9B958A", "note_02 → Automerge revisit if memory grows"]] },
      { q: 'get_context("realtime sync")', r: [
        ["#C9972C", "config_06 → Redis pub/sub fan-out"],
        ["#C96A5A", "bugfix_08 → WS reconnect backoff"],
        ["#7A8B5E", "context_01 → p95 latency budget = 80ms"]] },
      { q: 'recall_associative("stale beliefs")', r: [
        ["#D0B054", "config_04 ⚠ CI still on Node 18 (EOL)"],
        ["#A08BB8", "pattern_05 → supersede on schema bump"],
        ["#D9442B", "reflect → 2 memories flagged for review"]] },
    ];
    var qi = 0;
    function type(q, done) {
      qEl.textContent = ""; var i = 0;
      (function step() {
        if (i >= q.length) { setTimeout(done, 280); return; }   // beat before results
        var ch = q[i++]; qEl.textContent += ch;
        var d = 24 + Math.random() * 42;                        // humanised jitter
        if (ch === " ") d = 12;                                 // faster across spaces
        else if (ch === "(" || ch === ")" || ch === ",") d = 95;
        else if (ch === '"' || ch === "?") d = 165;             // linger on quotes / ?
        setTimeout(step, d);
      })();
    }
    function results(rs, done) {
      rEl.innerHTML = "";
      rs.forEach(function (r, i) {
        var d = document.createElement("div");
        d.className = "tres";
        d.innerHTML = '<span class="dot" style="background:' + r[0] + '"></span>' +
                      '<span>' + r[1] + "</span>";
        rEl.appendChild(d);
        setTimeout(function () { d.classList.add("show"); }, 120 + i * 200);
      });
      setTimeout(done, rs.length * 220 + 2600);
    }
    function cycle() {
      var e = QUERIES[qi % QUERIES.length]; qi++;
      type(e.q, function () { results(e.r, function () {
        qEl.textContent = ""; rEl.innerHTML = ""; setTimeout(cycle, 600);
      }); });
    }
    setTimeout(cycle, 1300);
  })();

  // ── 7 · faint glyph rain texture ────────────────────────────────
  (function () {
    var c = document.getElementById("rain");
    if (!c || reduce) return;
    var ctx = c.getContext("2d");
    var CH = "轍跡道憶識層ΨΣ∇λπ01∂∫";
    var Wd, Hd, drops;
    function rs() {
      Wd = c.width = c.offsetWidth; Hd = c.height = c.offsetHeight;
      drops = Array.from({ length: Math.floor(Wd / 22) }, function () { return (Math.random() * Hd / 16) | 0; });
    }
    function draw() {
      ctx.fillStyle = "rgba(16,16,18,0.16)"; ctx.fillRect(0, 0, Wd, Hd);
      ctx.fillStyle = "rgba(232,228,220,0.45)"; ctx.font = "12px 'JetBrains Mono',monospace";
      drops.forEach(function (y, i) {
        ctx.fillText(CH[(Math.random() * CH.length) | 0], i * 22, y * 16);
        if (y * 16 > Hd && Math.random() > 0.975) drops[i] = 0; else drops[i]++;
      });
    }
    rs(); setInterval(draw, 70); addEventListener("resize", rs);
  })();
})();
