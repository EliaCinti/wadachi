# wadachi 轍 — Brand Book

> **wadachi** (轍, ua-dà-ci): i solchi lasciati dalle ruote sulla strada.
> Le tracce di ciò che è passato, che guidano chi viene dopo.

Nome scelto il 13 Lug 2026 (naming workshop, decisione Engram #20).
Direzione visiva: **Sumi** — inchiostro zen su carta scura.

---

## 1. Concept e posizionamento

**One-liner (EN):** *Your sessions leave tracks. Future sessions follow them.*
**One-liner (IT):** *Le tue sessioni lasciano il segno. Le prossime lo seguono.*

**Descrittore prodotto:** Wadachi (轍) — self-hosted semantic memory for AI agents, over MCP.

**Posizionamento:** memoria che ragiona, non che archivia. Il memory server MCP
nativo per il pattern LLM Wiki: locale, privato, leggibile (Markdown + SQLite),
con un ciclo cognitivo vero (belief-revision, reflection, procedural).

**Tone of voice:** tecnico ma caldo · privacy-first · artigianale/indie · essenziale.
Frasi corte. Nessun hype. Il prodotto parla come un artigiano, non come una startup.

## 2. Palette

Dark-mode first (pubblico developer). Un solo accento: il vermiglio del sigillo.

| Ruolo              | Dark (default) | Light           | Nome            |
|--------------------|----------------|-----------------|-----------------|
| Sfondo             | `#101012`      | `#F5F1E8`       | carta notte / carta di riso |
| Sfondo rialzato    | `#18181B`      | `#ECE7DB`       | —               |
| Testo primario     | `#E8E4DC`      | `#1A1815`       | inchiostro      |
| Testo secondario   | `#6E6A62`      | `#8A857B`       | grigio pietra   |
| **Accento**        | `#D9442B`      | `#C33C22`       | vermiglio (shu) |
| Bordi/linee        | `#2A2A2E`      | `#DDD6C7`       | —               |

Regole: il vermiglio si usa **poco** (sigillo, link, CTA, un punto). Mai due accenti
nella stessa vista. Mai vermiglio su testo lungo.

## 3. Tipografia

Solo font liberi (Google Fonts, licenza OFL):

- **Display / titoli:** [Fraunces](https://fonts.google.com/specimen/Fraunces) — weight 400–600, optical size alto per i titoli grandi
- **Testo:** Inter — weight 400/500
- **Codice / dettagli tecnici:** JetBrains Mono — weight 400/500

Il logotype è "wadachi" in Fraunces 500, minuscolo, letter-spacing leggero,
con punto finale vermiglio opzionale (`wadachi.`).

## 4. Logo

Il logomark: **due pennellate sumi-e orizzontali** (i due solchi delle ruote) che si
assottigliano verso destra, + **sigillo hanko vermiglio** in basso a destra
(la firma dell'artigiano).

File master (SVG) in `assets/brand/`:

| File | Uso |
|---|---|
| `logomark.svg` | simbolo su sfondi scuri (inchiostro chiaro) |
| `logomark-light.svg` | simbolo su sfondi chiari (inchiostro scuro) |
| `logomark-mono.svg` | monocromatico, eredita `currentColor`, senza sigillo |
| `logo-horizontal.svg` | lockup simbolo + logotype (richiede font Fraunces) |
| `favicon.svg` + `favicon.ico` + `favicon-*.png` | favicon semplificato (2 solchi + sigillo su tile scura) |
| `apple-touch-icon.png` | 180×180 |
| `banner-github-1280x640.png` | social preview GitHub (master: `banner-github.html`, render con Chrome headless) |

**Do:**
- usare il logomark da solo quando lo spazio è poco (il favicon regge a 16px)
- mantenere il sigillo vermiglio solo se lo sfondo lo fa respirare
- rigenerare i raster dagli SVG/HTML master, mai editarli a mano

**Don't:**
- non ruotare/inclinare le pennellate, non cambiarne il colore fuori palette
- non mettere il logomark su sfondi colorati o fotografici
- non usare il kanji 轍 come logo primario (è un elemento decorativo secondario)
- non aggiungere ombre, gradienti o outline

**Rigenerare il banner:**
```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless \
  --disable-gpu --hide-scrollbars --window-size=1280,640 \
  --virtual-time-budget=12000 \
  --screenshot=assets/brand/banner-github-1280x640.png \
  "file://$(pwd)/assets/brand/banner-github.html"
```

## 5. Badge README

Stile flat, colori brand:

```markdown
![PyPI](https://img.shields.io/pypi/v/wadachi?style=flat&color=D9442B&labelColor=18181B)
![CI](https://img.shields.io/github/actions/workflow/status/EliaCinti/wadachi/ci.yml?style=flat&labelColor=18181B)
![License](https://img.shields.io/badge/license-MIT-E8E4DC?style=flat&labelColor=18181B)
```

## 6. Template post social (LinkedIn/X)

Derivare da `banner-github.html`: stesso sfondo `#101012`, logomark in alto a
sinistra ridotto, titolo del post in Fraunces, footer `wadachi.dev` in JetBrains
Mono grigio pietra. Formato 1200×630 (OG) o 1080×1080 (quadrato).
