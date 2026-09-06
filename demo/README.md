# Wadachi — public demo site

A self-contained, static landing page + interactive knowledge-graph demo for
**Wadachi**, the persistent-memory MCP server. Meant to live at
`wadachi.eliacinti.dev`.

Dark, product-style landing à la graphifylabs.ai: a hub-and-spoke knowledge
graph that **builds as you scroll**, a decoding headline, a live recall
terminal, then problem/solution, a feature grid, "how it works", and a
quick-start CTA.

> The graph shows a **100% fictional** example brain. It never touches the real
> `~/.wadachi/brain.db`, and every number on the page is honest (the counter
> reports the nodes actually drawn — nothing inflated). See *Dataset* below.

---

## Files

| File | What it is | Published? |
|------|------------|:---:|
| `index.html` | The landing page (structure + sections). | yes |
| `styles.css` | All styling (dark theme, no framework). | yes |
| `app.js` | The whole hero engine: builds the SVG graph on scroll, decodes the headline, runs the recall terminal, animates particles. The small curated demo graph is defined inline here. | yes |
| `docs.html` | A redirect to `wiki/index.html` — the docs outgrew a single page. | yes |
| `og.png`, `fonts/` | Social card and self-hosted faces. | yes |
| `wiki/` | The compiled wiki, **generated** — never edit by hand. | yes |
| `wiki-src/` | The wiki's markdown sources with `[[wikilinks]]`, compiled by `scripts/build-wiki.py`. | **no** |
| `README.md` | This file. | **no** |

The landing itself has no build step and **no external runtime dependencies** —
`app.js` is pure vanilla JS and carries its own curated graph. The wiki does have
one: `wiki/` is compiled from `wiki-src/`, and the two right-hand `no`s are
deliberate — the deploy publishes an explicit list of files, so sources and this
README stay off the public site.

---

## Local preview

From inside this directory:

```bash
python3 -m http.server 8000
# open http://localhost:8000
```

If you touched anything under `wiki-src/`, rebuild first or you will be previewing
the previous wiki:

```bash
cd .. && venv/bin/python scripts/build-wiki.py
```

---

## How the hero works

- **Scroll-build** — the hero is a tall track with a `sticky` stage. Scroll
  progress (0→1) reveals nodes/edges in order and ticks the "nodes indexed"
  counter. An initial auto-build plays on load so it's never empty.
- **Decoding headline** — the `<h1>` scrambles Greek/math/block glyphs into the
  title on load.
- **Recall terminal** — a looping ticker that types `recall(...)` queries and
  reveals the connected results.
- **Perpetual life** — particles flow along every visible edge, node halos
  breathe, and a faint glyph-rain canvas sits behind it all.
- Everything honours `prefers-reduced-motion` (static, fully readable fallback).

Palette is Wadachi's own violet `#8b7cf6` / cyan `#34d3ee` on near-black
`#07080c`, matching the README and `eliacinti.dev`.

---

## Deploy

**One command, from the repository root:**

```bash
scripts/deploy-site.sh          # add --bump only if you edited styles.css or app.js
```

It aligns the version pill to `wadachi/__init__.py`, rsyncs an **explicit list** of
files (`index.html docs.html styles.css app.js og.png fonts wiki`) to the served
directory, and verifies the result with `curl`. The list is explicit on purpose:
that is what keeps `wiki-src/` and this README off the public site, and it is why
the script uses no `--delete`.

Three things the script does **not** do, and one it leaves behind:

1. **It does not build the wiki.** Run `venv/bin/python scripts/build-wiki.py`
   first whenever `wiki-src/` changed, or you will publish the old pages.
2. **It does not commit anything.** After a deploy, `demo/index.html` carries the
   rewritten version pill — commit it, or the next deploy rewrites it again.
3. **It does not push.** `main` is a **protected branch**: `git push` straight to
   it is refused with `GH006 — changes must be made through a pull request`.
   Every change here, including a one-line pill, goes through a PR.

> **The served directory is still called `engram`** — the name predates the
> rebrand, and there is **no `wadachi` directory on the server**. The real
> destination lives in one place, `DEST` in `scripts/deploy-site.sh`; renaming it
> means moving the bind mount and the `root` in the server block together. Until
> someone does that, `engram` is correct, and this note exists so nobody "fixes"
> it into a broken deploy.

### nginx — a reference block, not the deployed one

The live configuration lives on the VPS, bind-mounted read-only into the nginx
container, and it is **not reproduced here**:
an earlier version of this file claimed a `try_files … /index.html` fallback that
the running server does not have, which sent a real 404 while the docs promised a
200. A copy of a config is a claim that goes stale silently — read the live one.

What follows is a **reference block for someone self-hosting their own copy** of
this site. It is not a description of `wadachi.eliacinti.dev`.

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name wadachi.example.com;

    root /var/www/wadachi;   # wherever you put the files
    index index.html;

    # static site — try the file, else fall back to index.html
    location / {
        try_files $uri $uri/ /index.html;
    }

    # long cache for the immutable assets, short for HTML
    location ~* \.(js|css|json|svg|woff2?)$ {
        expires 7d;
        add_header Cache-Control "public, max-age=604800";
    }
    location = /index.html {
        add_header Cache-Control "no-cache";
    }

    # Content-Security-Policy — fully self-hosted, no CDN needed.
    # 'unsafe-inline' for styles only (inline style attributes set from JS).
    add_header Content-Security-Policy "default-src 'self'; \
        script-src 'self'; \
        style-src 'self' 'unsafe-inline'; \
        img-src 'self' data:; \
        font-src 'self' data:; \
        connect-src 'self'; \
        base-uri 'self'; \
        frame-ancestors 'none'" always;

    add_header X-Content-Type-Options "nosniff" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
}
```

Add a `listen 443 ssl;` block with your own cert paths for origin TLS; the
`location` blocks and headers stay identical.

> Fonts: the page uses only system + monospace fonts, so there are **no external
> font requests** and the CSP above needs no `fonts.googleapis.com` exception.

---

## Dataset (what's fictional)

The hero graph is a small curated brain for **"Tideflow"** — an imaginary
open-source CRDT real-time-sync engine (Yjs core, WebSocket server, Redis
fan-out, Postgres snapshots, React hooks). None of it is real; no person, repo,
or path belongs to Elia.

- A central **`get_context`** hub wired to Wadachi's six faculties
  (recall · decisions · constellation · beliefs · reflect · procedural).
- A ring of **memories** hanging off each faculty, plus a few cross-links so it
  reads as a graph, not a tree.
- The recall terminal cycles real-shaped Wadachi queries
  (`recall(...)`, `get_context(...)`, `recall_associative(...)`) returning
  connected memories/decisions — including one `stale` belief flagged for review.

To change the showcase, edit the model arrays at the top of `app.js`
(`ring1Defs`, `leafLabels`) and the `QUERIES` list in the terminal block.

---

Built by Elia Cinti — [eliacinti.dev](https://eliacinti.dev)
