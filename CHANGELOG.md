# Changelog

All notable changes to this project are documented here.
Format: [Keep a Changelog](https://keepachangelog.com) · versioning: [SemVer](https://semver.org) (pre-1.0: minor = può rompere).

## [0.14.0] — 2026-07-20

### Added — accesso concorrente (multi-client)
- **Il brain è ora sicuro sotto accesso concorrente** da più client MCP
  contemporaneamente (es. più agenti di Overmind in parallelo). Il DB gira in
  **WAL** con `busy_timeout`: i lettori non bloccano mai lo scrittore, e uno
  scrittore *aspetta* il lock invece di fallire con "database is locked".
- **Scritture su file atomiche**: `index.md` viene riscritto via file
  temporaneo + `os.replace`, e i file memoria vengono creati con
  `O_CREAT|O_EXCL` — due scritture concorrenti con lo stesso titolo ottengono
  file distinti invece che una sovrascriva l'altra (era una race TOCTOU).

### Fixed — interazioni con il WAL
- `wadachi export` archivia ora uno **snapshot completo** del DB (`VACUUM INTO`,
  legge anche il WAL) restando **rigorosamente read-only** sul brain sorgente.
- `restore`/`restore --replace` e il backup pre-migrazione ripuliscono/consolidano
  i sidecar `brain.db-wal`/`-shm` così un brain ripristinato non eredita mai un
  WAL stantìo del brain precedente.

## [0.13.0] — 2026-07-15

### Added
- **`wadachi restore --replace`** — "riparti da qui": sostituisce il brain
  ATTIVO con un export precedente, in un comando. Prima di toccare qualsiasi
  cosa, lo stato corrente viene esportato in `backups/pre-restore-<ts>.tar.gz`
  — anche il viaggio nel passato è reversibile. `backups/` e `logs/` correnti
  sono preservati; il MANIFEST non resta nel brain vivo.

## [0.12.0] — 2026-07-15

### Added — la rete di sicurezza
- **`wadachi export`** — archivio portabile e datato dell'intero brain
  (markdown + DB + MANIFEST.json con versione, conteggi, schema).
  **Rigorosamente read-only**: nessuna migrazione parte, il brain resta
  byte-identico — sicuro anche su un brain dell'era Engram, PRIMA
  dell'upgrade. Il percorso prudente: installa → esporta → poi migra.
- **`wadachi restore <archivio> --to <dir>`** — ripristino in una cartella
  nuova (rifiuta destinazioni non vuote senza `--force`), con guardia
  path-traversal. Roundtrip testato: il brain ripristinato è subito usabile.

### Changed
- Cartelle canoniche su disco rinominate (`wadachi/`, `wadachi-brain/`)
  con symlink di compatibilità dai vecchi nomi.

### Tests
- 6 test nuovi (131 totali), incluso il caso "brain Engram legacy esportato
  senza che nulla lo tocchi".

## [0.11.0] — 2026-07-15

### Added
- **`wadachi obsidian`** — SU RICHIESTA (mai automatico): genera i wikilink
  `[[slug]]` per il grafo di Obsidian, appendendo una sezione `Links` marcata
  in coda ai file che citano altre memorie per id. La prosa non si tocca mai;
  ogni riscrittura è versionata (memory_versions) e invalida l'embedding del
  file. `--dry-run` per vedere prima. Sul brain reale: 46 wikilink in 30 file.
- **Release automatica** (`.github/workflows/release.yml`): su ogni tag `vX.Y.Z`
  → test → build → pubblicazione su PyPI via Trusted Publishing (OIDC, zero
  token). Richiede il setup una-tantum del publisher su pypi.org.
- **`scripts/deploy-site.sh`**: deploy della landing con pill di versione
  allineata automaticamente al package e bump opzionale del cache-buster.
- **`scripts/backup-brain.sh`**: backup del brain con rotazione (pensato per
  l'hook Stop di Claude Code).

### Sito
- Grafo hero "dezoomato": viewBox più ampio, 35 nodi (nuovo anello di
  satelliti), label più grandi e nitide; repulsione al cursore ammorbidita.

## [0.10.0] — 2026-07-15

### Added — il brain propone
- **Le proposte in `get_context`**: a inizio sessione il brain dice cosa
  suggerisce di fare — insight in attesa di giudizio, risultati dell'ultimo
  sonno ("N gruppi da fondere, M memorie in decadimento"), o l'invito a far
  girare il sonno se non gira da tempo. Il software propone spiegando cosa e
  perché; l'umano decide. Sezione "## il brain propone" nel formato denso.
- **CLI `wadachi sleep`**: il job periodico (perfetto in cron/launchd) — report
  umano leggibile + cache che alimenta le proposte del prossimo get_context.

### Sito (Fase 6 — non impatta il package)
- **Hero full-screen**: il grafo tipizzato full-bleed è il protagonista (27
  nodi: memorie, facoltà, decisioni a rombo, arco *supersedes* vermiglio),
  hover su un nodo → card col dettaglio; repulsione al cursore ricalibrata
  (morbida). Motore vanilla esteso — niente d3, la CSP resta senza CDN.
- **Sezione "Why wadachi"**: confronto onesto con Mem0/Zep/Supermemory,
  colonna wadachi con velo di tinta.
- **Coerenza Sumi**: un solo accento — via il verde/rosso isolati dei kicker;
  layout allargato a 1280px.
- **SEO**: og:image, canonical, JSON-LD SoftwareApplication.
- **Scena problema→soluzione**: il loop dell'amnesia (terminale spettrale che
  ridigita le stesse spiegazioni, contatore che sale) contro "One call.
  Everything back." — attraversati dalle due pennellate wadachi.

## [0.9.0] — 2026-07-15

### Added — Fase 7.B (parte 2): sonno, scoping, vetrina (31 tool)
- **`sleep`** — il "sonno" del brain (read-only): community detection sul grafo
  (label propagation pesata, puro Python) → gruppi di memorie ridondanti come
  candidati merge; foglie senza link espliciti, mai richiamate e in decadimento
  → candidati flag_stale; orfani. Propone, non tocca nulla. Sul brain reale:
  12 community tematicamente coerenti, il cluster del progetto CEM concluso
  emerso come candidato naturale al consolidamento.
- **Evidence scoping**: i risultati di recall portano `project`, e nelle
  ricerche scoped l'evidenza cross-cutting è dichiarata (`scope: global`) —
  l'inferenza sa da dove viene ogni prova.
- **La vetrina** (`python -m wadachi.web`): il grafo D3 non è più un'euristica
  sui tag — mostra il VERO MemoryGraph: decisioni come rombi, archi tipizzati
  (supersedes vermiglio, contradicts tratteggiato, citation/semantic/entity),
  **slider temporale "As of"** (as_of visualizzato), click su una decisione →
  pannello con perché/alternative scartate/contesto (why visualizzato).

### Fixed
- I candidati decay del sonno contano solo i link ESPLICITI (citation/entity):
  i kNN semantici automatici davano grado a tutto, nascondendo le foglie vere.

### Tests
- 6 test nuovi (117 totali).

## [0.8.0] — 2026-07-15

### Added — Fase 7.B roadmap (parte 1): il grafo funzionale (30 tool)
- **Nodi tipizzati**: le decisioni entrano nel grafo come nodi veri (esagoni nel
  Mermaid). "decisione #19" in prosa e `[[D19]]` diventano archi; il razionale
  di una decisione che cita "memoria #82" crea l'arco inverso. Le supersession
  dei belief (`superseded_by`) diventano archi tipizzati **supersedes** — le
  contraddizioni nel tempo sono struttura, non rumore.
- **Graph-aware recall**: `recall(neighbors=True)` allega a ogni risultato i
  vicini più forti a 1 hop con la relazione tipizzata — ciò che è CONNESSO
  emerge anche quando non è testualmente simile.
- **`why(question)`** — la provenienza interrogabile: "perché usiamo X e non Y?"
  → decisione, razionale, alternative scartate, contesto, e le memorie che la
  citano nel grafo come evidenza.
- **`as_of(date, query)`** — time-travel: cosa credeva il brain a una certa
  data, con il contenuto ricostruito dalla cronologia non-distruttiva delle
  versioni e le memorie già superate/scadute annotate.

### Rimandati alla parte 2
Consolidamento "sonno" (Louvain), evidence scoping formale, vetrina web del
grafo tipizzato (si incastra con la Fase 6 — sito).

### Tests
- 12 test nuovi (111 totali).

## [0.7.0] — 2026-07-14

### Added — Fase 7.A roadmap: LLM Wiki + OKF (il posizionamento)
- **Pattern LLM Wiki (Karpathy)**: il brain è ora un wiki mantenuto dall'agente —
  `index.md` (catalogo generato, una riga per memoria con wikilink), `log.md`
  (cronologia append-only, grep-abile), `SCHEMA.md` (le convenzioni del brain,
  create da `wadachi init`, editabili dall'utente: "the schema file is everything").
- **Wikilink Obsidian**: `[[slug-del-file]]` (con alias `[[slug|testo]]`) e
  `[[#id]]` diventano archi *citation* del grafo, insieme alla prosa storica
  "memoria #42". Chiuso un gap latente: i link di provenienza scritti da
  `merge_memories`/`accept_insight` non generavano archi. **Il brain dir è un
  vault Obsidian valido**: grafo nativo gratis, zero lock-in.
- **Conformità OKF** (Open Knowledge Format, Google): il frontmatter canonico
  include `type` (l'unico campo richiesto dalla spec); il brain è un bundle OKF
  conforme. `wadachi doctor --fix` porta i brain pre-OKF alla conformità in
  place, senza mai toccare i contenuti.

### Changed
- Le scritture dei file memoria passano da `mdio.render_memory_file` (unica
  fonte di verità del formato, prima erano f-string duplicate in store.py).

### Added — Fase 5 (parziale): community
- `CONTRIBUTING.md`, issue templates (bug report integrato con `wadachi doctor`
  + log), **"Share your setup"** (feedback loop privacy-first), template PR.

### Tests
- 11 test nuovi (99 totali).

## [0.6.0] — 2026-07-14

### Added — Fase 4 roadmap: efficienza token (28 tool)
- **`get_context` a livelli** (4.12/4.14): default in formato **denso** — righe
  compatte con puntatori `#id`, categoria e score invece del JSON verboso.
  Sul brain reale: **~3.600 → ~430 token (-89%)**. `format="json"` resta come
  escape hatch.
- **Budget esplicito** (4.13): `get_context(max_tokens=N)` tronca **per
  rilevanza** (mai per età): prima si accorciano needs_review e decisioni, poi
  le memorie dalla coda; header, stats e footer sopravvivono sempre.
- **`expand_memory(ids)`**: drill-down batch dal contesto compatto al contenuto
  completo.
- **Consolidamento** (4.15): `consolidate()` propone gruppi di memorie
  ridondanti (similarità coseno, read-only); `merge_memories(...)` salva la TUA
  sintesi e marca le fonti *superseded* via belief system — mai cancellate,
  sempre recuperabili, con provenienza `[[#id]]` automatica.
- **Decay score** (4.16): migrazione **0002** (access_count + last_accessed);
  ogni `get_memory`/`expand_memory` ringiovanisce la memoria; le memorie mai
  richiamate perdono fino al 12% di score (-2%/mese oltre il primo), in modo
  trasparente (campo `decay` nei risultati).

### Changed
- Prima migrazione incrementale reale: i brain a schema v1 passano a v2 con
  backup automatico (validato sul brain di produzione, 100 memorie).

### Tests
- 15 test nuovi (88 totali); i test delle migrazioni sono ora version-agnostic.

## [0.5.0] — 2026-07-14

### Added — Fase 3 roadmap: robustezza
- **Parser Markdown tollerante** (`wadachi/mdio.py`): i file memoria si leggono
  sempre — frontmatter assente, malformato o non chiuso, tag in JSON/YAML/CSV,
  `---` nel corpo: mai un'eccezione. Usato da `get_memory` al posto dello split
  fragile. **Backfill**: riscrittura trasparente nel formato canonico usando i
  metadata del DB come fonte autorevole (il contenuto non si tocca mai).
- **Logging strutturato** (`wadachi/log.py`): stderr per i soli WARNING+ (mai
  stdout: è il canale MCP), file rotante `<brain>/logs/wadachi.log` con livello
  da `$WADACHI_LOG`. Ogni tool è strumentato: durata a DEBUG, errori con
  traceback completo — un utente può allegare un log leggibile a una segnalazione.
- **`wadachi doctor`**: diagnostica di config, permessi, DB (integrity_check,
  versione schema vs migrazioni disponibili), file .md (mancanti / orfani /
  frontmatter rotto), fastembed, registrazione in Claude Code. La diagnosi è
  **read-only** (DB aperto in modalità ro, nessuna migrazione applicata);
  `--fix` ripara solo ciò che è sicuro: directory mancanti e frontmatter
  (backfill dal DB). Exit code 0/1.

### Tests
- 16 test nuovi (73 totali): parser su input degeneri, doctor su brain sano /
  DB corrotto / file mancanti / orfani, garanzia read-only della diagnosi.

## [0.4.0] — 2026-07-14

### Added — Fase 2 roadmap: distribuzione
- **CLI `wadachi init`** — setup guidato in un comando: crea la brain dir
  (default `~/.wadachi`, rispetta un `~/.engram` legacy), porta il DB all'ultima
  versione dello schema (con backup automatico se esisteva già), registra il
  server MCP in Claude Code (`claude mcp add`) e scrive la config Antigravity.
  Idempotente. `wadachi` senza argomenti resta il server MCP (compatibilità
  con le config esistenti). `wadachi --version`.
- **Packaging da prodotto**: metadata pyproject completi (authors, classifiers,
  Homepage → wadachi.eliacinti.dev), installabile via `pipx install wadachi` /
  `uv tool install wadachi`; le migrazioni viaggiano dentro il wheel.
- **README**: quickstart in 3 comandi, badge PyPI, sezione *Upgrading* (le
  memorie sopravvivono sempre: migrazioni versionate + backup automatico).

## [0.3.0] — 2026-07-14

### Added — Fase 1 roadmap: fondamenta
- **Migrazioni DB versionate** (`wadachi/migrations/`): tabella `schema_version`,
  runner all'avvio che applica gli script `000N_*.py` in ordine, ognuno nella sua
  transazione (BEGIN/COMMIT espliciti, rollback su errore). **Backup automatico**
  del `.db` in `backups/` prima di ogni migrazione su un DB non vuoto. I DB
  pre-esistenti vengono adottati dal baseline idempotente senza toccare i dati.
- **Suite pytest**: 51 test su migrazioni, store e tutti i 25 tool MCP — DB vuoto,
  DB corrotto, ID inesistenti, titoli duplicati/malformati, versioning, beliefs,
  insights, progetti. Hermetic (BRAIN_DIR temporanei), gira anche senza fastembed.
- **CI GitHub Actions**: test a ogni push/PR, matrice Python 3.11–3.14.

### Fixed
- `recall_associative` senza fastembed non crasha più il tool MCP: restituisce un
  errore chiaro + i risultati del fallback keyword (bug trovato dalla nuova suite).
- Il rollback delle migrazioni è garantito anche per le DDL (il modulo sqlite3 di
  Python committa implicitamente fuori transazione: ora BEGIN/COMMIT sono espliciti
  e `executescript` è vietato negli script di migrazione).

## [0.2.0] — 2026-07-14

### Changed — Rebrand: Engram → wadachi 轍 (Fase 0 roadmap)
- **Nuovo nome: wadachi** (轍 — i solchi che le ruote lasciano sulla strada). Scelto dopo un
  naming workshop con verifica sistematica di ~30 candidati (PyPI, domini, GitHub, collisioni
  nello spazio AI/memory). Nome PyPI riservato: [pypi.org/project/wadachi](https://pypi.org/project/wadachi/).
- **Package Python rinominato**: `engram` → `wadachi` (`from wadachi.store import …`).
- **Server MCP rinominato**: si registra come `wadachi` (era `engram`).
- **Entry point**: `wadachi` (+ alias legacy `engram`, così le config MCP esistenti che puntano
  a `venv/bin/engram` continuano a funzionare).
- **BRAIN_DIR default**: ora `~/.wadachi`; un brain legacy esistente in `~/.engram` viene
  rilevato e continua a funzionare senza modifiche.
- **Repo GitHub rinominato**: `EliaCinti/engram` → `EliaCinti/wadachi` (redirect automatici).
- **Sito**: engram.eliacinti.dev → **wadachi.eliacinti.dev** (301 dal vecchio dominio).

### Added
- **Brand identity "Sumi"** (`BRAND.md` + `assets/brand/`): palette inchiostro/vermiglio,
  tipografia Fraunces + Inter + JetBrains Mono, logomark a due pennellate con sigillo hanko,
  favicon, banner GitHub 1280×640.
- **Landing rebrandizzata** in stile Sumi (font self-hosted per CSP rigida, grafo hero
  ricolorato: hub vermiglio, nodi inchiostro, categorie in toni terra).
- Questo CHANGELOG.

## [0.1.0] — 2026-06-29

Stato pre-rebrand ("Engram 2.0"): 25 tool MCP — memoria persistente versionata (markdown +
SQLite), ricerca semantica locale (fastembed), auto-contesto, decision log, Constellation
(recall associativo con spreading activation + grafo entità via Graphify/claude-cli),
belief revision, reflection & insights, memoria procedurale, visualizzatore web del grafo.
