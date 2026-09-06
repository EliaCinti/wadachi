#!/usr/bin/env python3
"""
build-wiki.py — compila demo/wiki-src/*.md nella wiki del sito (demo/wiki/*.html).

La wiki è essa stessa un LLM Wiki: markdown con [[wikilink]], compilato in
HTML statico (stile Sumi, CSP-clean). L'ordine e i gruppi vivono in MANIFEST.

Uso:  venv/bin/python scripts/build-wiki.py
Richiede: pip install markdown (extra dev del venv).
"""

import html
import re
import sys
from pathlib import Path

try:
    import markdown
except ImportError:
    sys.exit("serve il pacchetto 'markdown': venv/bin/pip install markdown")

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "demo" / "wiki-src"
OUT = ROOT / "demo" / "wiki"

# (slug, gruppo) in ordine di navigazione
MANIFEST = [
    ("index",           "Start here"),
    ("harness",         "Start here"),
    ("installation",    "Start here"),
    ("connect",         "Start here"),
    ("brain",           "The brain"),
    ("memories",        "The brain"),
    ("projects",        "The brain"),
    ("decisions",       "The brain"),
    ("get-context",     "Intelligence"),
    ("search",          "Intelligence"),
    ("beliefs",         "Intelligence"),
    ("graph",           "Intelligence"),
    ("sleep",           "Maintenance"),
    ("consolidation",   "Maintenance"),
    ("time-travel",     "Maintenance"),
    ("obsidian-okf",    "Maintenance"),
    ("safety",          "Safety"),
    ("tools",           "Reference"),
    ("cli",             "Reference"),
    ("troubleshooting", "Reference"),
    ("faq",             "Reference"),
]

_WIKILINK = re.compile(r"\[\[([a-z0-9-]+)(?:\|([^\]]+))?\]\]")
_TITLE = re.compile(r"^#\s+(.+)$", re.M)

TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — wadachi wiki</title>
<meta name="description" content="{description}">
<link rel="canonical" href="https://wadachi.eliacinti.dev/wiki/{slug}.html">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Crect width='32' height='32' rx='7' fill='%23101012'/%3E%3Cpath d='M5 11.5C5 10.4 5.9 9.6 7 9.7L21 10.6C23.5 10.8 25.5 11.2 27 11.8C25.5 12.3 23.5 12.5 21 12.5L7 13.2C5.9 13.3 5 12.6 5 11.5Z' fill='%23E8E4DC'/%3E%3Cpath d='M5 19.5C5 18.4 5.9 17.6 7 17.7L19.5 18.6C22 18.8 24 19.2 25.5 19.8C24 20.3 22 20.5 19.5 20.5L7 21.2C5.9 21.3 5 20.6 5 19.5Z' fill='%23E8E4DC'/%3E%3Crect x='23' y='23' width='5' height='5' rx='1.4' fill='%23D9442B'/%3E%3C/svg%3E">
<link rel="stylesheet" href="../styles.css?v=10">
<style>
  .wk-wrap {{ max-width: 1280px; margin: 0 auto; padding: 96px clamp(18px,4vw,40px) 60px;
              display: grid; grid-template-columns: 235px 1fr; gap: clamp(24px,4vw,64px); }}
  .wk-nav {{ position: sticky; top: 90px; align-self: start; font-size: 13px;
             max-height: calc(100vh - 120px); overflow-y: auto; padding-right: 6px; }}
  .wk-nav .g {{ font-family: var(--mono); font-size: 10.5px; letter-spacing: 1.2px;
             text-transform: uppercase; color: var(--accent); margin: 18px 0 6px; }}
  .wk-nav a {{ display: block; color: var(--text-dim); padding: 3px 0 3px 10px;
             border-left: 1.5px solid var(--border); transition: color .15s, border-color .15s; }}
  .wk-nav a:hover {{ color: var(--text); border-color: var(--accent); }}
  .wk-nav a.on {{ color: var(--text); border-color: var(--accent); }}
  .wk-main {{ min-width: 0; }}
  .wk-main h1 {{ font-size: clamp(32px,3.6vw,46px); margin-bottom: 22px; }}
  .wk-main h2 {{ font-size: clamp(22px,2.4vw,29px); margin: 44px 0 12px; padding-top: 16px;
             border-top: 0.5px solid var(--border); }}
  .wk-main h3 {{ font-size: 17.5px; margin: 26px 0 8px; color: var(--text); }}
  .wk-main p, .wk-main li {{ font-size: 14.5px; color: var(--text-dim); line-height: 1.75; }}
  .wk-main p {{ margin-bottom: 13px; max-width: 730px; }}
  .wk-main ul, .wk-main ol {{ margin: 0 0 15px 20px; max-width: 710px; }}
  .wk-main li {{ margin-bottom: 6px; }}
  .wk-main strong {{ color: var(--text); }}
  .wk-main a {{ color: var(--accent); }}
  .wk-main a:hover {{ text-decoration: underline; }}
  .wk-main a.wl {{ color: var(--text); background: rgba(217,68,43,0.09);
             padding: 1px 7px 2px; border-radius: 6px; white-space: nowrap;
             transition: background .15s, color .15s; }}
  .wk-main a.wl::before {{ content: "\\203A\\00a0"; color: var(--accent); font-weight: 600; }}
  .wk-main a.wl:hover {{ background: rgba(217,68,43,0.18); color: var(--text);
             text-decoration: none; }}
  .wk-main pre {{ position: relative; font-family: var(--mono); font-size: 12.8px;
             line-height: 1.7; background: #17171B;
             border: 1px solid var(--border-2); border-radius: 11px;
             padding: 30px 17px 15px; color: #DDD8CC; overflow-x: auto;
             margin: 14px 0 18px; max-width: 730px;
             box-shadow: inset 0 1px 0 rgba(232,228,220,0.04); }}
  .wk-main pre::before {{ content: "\\276F code"; position: absolute; top: 8px; left: 14px;
             font-size: 9.5px; letter-spacing: 1.5px; text-transform: uppercase;
             color: var(--accent); opacity: 0.85; }}
  .wk-main pre code {{ background: none; padding: 0; font-size: inherit; color: inherit; }}
  .wk-main table {{ width: 100%; border-collapse: collapse; font-size: 13px; margin: 14px 0 22px; }}
  .wk-main th, .wk-main td {{ text-align: left; padding: 9px 12px;
             border-bottom: 0.5px solid var(--border); vertical-align: top; }}
  .wk-main th {{ font-family: var(--mono); font-size: 11px; text-transform: uppercase;
             letter-spacing: 0.6px; color: var(--text-faint); font-weight: 500; }}
  .wk-main td:first-child {{ font-family: var(--mono); font-size: 12.5px; color: var(--text); }}
  .wk-main td {{ color: var(--text-dim); }}
  .wk-main blockquote {{ border-left: 2px solid var(--accent); background: rgba(217,68,43,0.05);
             border-radius: 0 10px 10px 0; padding: 11px 16px; margin: 16px 0 20px;
             max-width: 710px; }}
  .wk-main blockquote p {{ margin: 0; font-size: 13.5px; }}
  .wk-foot {{ display: flex; justify-content: space-between; gap: 16px; margin-top: 56px;
             padding-top: 18px; border-top: 0.5px solid var(--border); font-size: 13.5px; }}
  .wk-foot a {{ color: var(--text-dim); }}
  .wk-foot a:hover {{ color: var(--accent); }}
  .tblw {{ overflow-x: auto; }}
  @media (max-width: 880px) {{ .wk-wrap {{ grid-template-columns: 1fr; }}
             .wk-nav {{ position: static; max-height: none; }} }}
</style>
</head>
<body>
<header class="nav">
  <a class="brand" href="../index.html">
    <span class="brand-mark" aria-hidden="true">
      <svg viewBox="40 130 470 310" xmlns="http://www.w3.org/2000/svg">
        <g fill="currentColor">
          <path d="M 74 184 C 64 166, 76 150, 96 150 C 170 146, 264 158, 344 174 C 394 183, 434 193, 462 205 C 434 211, 394 212, 344 208 C 264 202, 166 200, 96 212 C 80 214, 68 200, 74 184 Z"/>
          <path d="M 470 203 C 484 201, 494 201, 502 199 C 494 207, 484 209, 470 210 Z"/>
          <path d="M 74 300 C 64 282, 76 266, 96 266 C 170 262, 260 274, 336 290 C 382 299, 418 309, 444 319 C 418 325, 382 326, 336 322 C 260 316, 166 314, 96 328 C 80 330, 68 316, 74 300 Z"/>
          <path d="M 452 317 C 466 315, 476 315, 486 313 C 476 321, 466 323, 452 324 Z"/>
        </g>
        <rect x="410" y="376" width="56" height="56" rx="10" fill="#D9442B"/>
      </svg>
    </span>
    <span class="brand-name">wadachi</span>
  </a>
  <nav class="nav-links">
    <a href="../index.html">Home</a>
    <a href="index.html" style="color:var(--text)">Wiki</a>
    <a class="nav-gh" href="https://github.com/EliaCinti/wadachi" target="_blank" rel="noopener">GitHub ↗</a>
  </nav>
</header>
<div class="wk-wrap">
<nav class="wk-nav" aria-label="wiki">{sidebar}</nav>
<main class="wk-main">
{body}
<div class="wk-foot">{prev}{next}</div>
</main>
</div>
<footer class="footer">
  <p class="footer-note">wadachi 轍 wiki — a wiki about an LLM Wiki, built as one:
     markdown + wikilinks, compiled to HTML.
     <a href="https://github.com/EliaCinti/wadachi/tree/main/demo/wiki-src">source</a></p>
  <div class="footer-kanji" aria-hidden="true">轍</div>
</footer>
</body>
</html>
"""


def main() -> int:
    md = markdown.Markdown(extensions=["tables", "fenced_code"])
    pages = {}
    for slug, group in MANIFEST:
        path = SRC / f"{slug}.md"
        if not path.exists():
            sys.exit(f"manca {path}")
        text = path.read_text(encoding="utf-8")
        m = _TITLE.search(text)
        pages[slug] = {"group": group, "title": m.group(1) if m else slug, "src": text}

    def sidebar(current: str) -> str:
        out, last_group = [], None
        for slug, group in MANIFEST:
            if group != last_group:
                out.append(f'<div class="g">{html.escape(group)}</div>')
                last_group = group
            cls = ' class="on"' if slug == current else ""
            out.append(f'<a href="{slug}.html"{cls}>{html.escape(pages[slug]["title"])}</a>')
        return "\n".join(out)

    OUT.mkdir(exist_ok=True)
    order = [s for s, _ in MANIFEST]
    for i, slug in enumerate(order):
        page = pages[slug]
        src = _WIKILINK.sub(
            lambda m: f'<a class="wl" href="{m.group(1)}.html">'
                      f'{html.escape(m.group(2) or pages.get(m.group(1), {}).get("title", m.group(1)))}</a>',
            page["src"])
        md.reset()
        body = md.convert(src)
        body = body.replace("<table>", '<div class="tblw"><table>').replace("</table>", "</table></div>")
        first_p = re.search(r"<p>(.*?)</p>", body, re.S)
        desc = html.escape(re.sub(r"<[^>]+>", "", first_p.group(1))[:150]) if first_p else "wadachi wiki"
        prev_a = (f'<a href="{order[i-1]}.html">← {html.escape(pages[order[i-1]]["title"])}</a>'
                  if i > 0 else "<span></span>")
        next_a = (f'<a href="{order[i+1]}.html">{html.escape(pages[order[i+1]]["title"])} →</a>'
                  if i < len(order) - 1 else "<span></span>")
        (OUT / f"{slug}.html").write_text(TEMPLATE.format(
            title=html.escape(page["title"]), description=desc, slug=slug,
            sidebar=sidebar(slug), body=body, prev=prev_a, next=next_a,
        ), encoding="utf-8")
    print(f"  ✓ {len(order)} pagine wiki generate in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
