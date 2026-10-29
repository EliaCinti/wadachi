# La ripresa anche fuori da un progetto

*Piano — 28 Ott 2026. In attesa di approvazione. Nasce dalla prova dal vivo di
`/clear`, ultimo passo aperto della scrivania `la-cache-ha-un-orologio`: la
prova è fallita, e questo piano è la correzione.*

## Il problema

`resume-desk.py` (PR #12) inietta le scrivanie aperte dopo `/clear` e
all'avvio, ma solo se la directory della sessione appartiene a un progetto.
Elia apre spesso VSCode sulla home, `/Users/eliacinti`, e da lì la ripresa non
succede mai:

- `detect_project('/Users/eliacinti')` → `None` → `build()` restituisce `""`
  → l'hook esce 0, muto (`scripts/resume-desk.py:109-111`).
- Provato a mano lo stesso giorno: con `cwd=/Volumes/ExtremeSSD/wadachi`
  l'hook produce 614 caratteri, ~150 token, con le 3 scrivanie e il prossimo
  passo di ognuna.

Il costo, misurato sulla sessione del 28 Ott: dopo `/clear` sono servite **6
tool call** per ritrovare il filo, una sola delle quali (`desk_read`) ha
restituito ~6,7k caratteri. Con la ripresa funzionante sarebbero state zero.

C'è anche un'incoerenza: senza progetto, il **server** ripiega su `global`
(`server.py:1267`, `1297`, `1326`), mentre l'**hook** si ferma. Ripiegare su
`global` anche nell'hook non basterebbe: oggi avrebbe mostrato le due scrivanie
della homepage, non le due di wadachi su cui si stava lavorando.

## La proposta

Quando la directory non appartiene a nessun progetto, l'hook mostra **le
scrivanie aperte più recenti di tutti i progetti**, una riga ciascuna:

```
## Scrivanie aperte più recenti (nessun progetto in /Users/eliacinti)
- `la-cache-ha-un-orologio-…` (wadachi, oggi) — prossimo: …
- `risposte-che-costano-meno-…` (wadachi, oggi) — prossimo: …
- `homepage-costruzione-progressiva-…` (global, 2 g fa) — prossimo: …
- … e altre 2.
Non sceglierne una da solo: chiedi a Elia quale riprendere.

Iniettate all'avvio da resume-desk. Testo completo: desk_read(slug=…, project=…).
```

- **Al massimo 5**, ordinate per `updated_at` decrescente, come le dà già
  `store.list_desks(project=None)`. Le altre sono contate in una riga.
- **Progetto ed età su ogni riga.** Il progetto serve a riprendere, l'età a
  scegliere: una scrivania ferma da un mese non vale come una di stamattina.
- **Il piede dice `project=…`, non `cwd=…`.** Dalla home, `desk_read` con la
  `cwd` risolverebbe a `global` e non troverebbe le scrivanie di wadachi.
- **Dentro un progetto non cambia niente**: una scrivania → dettaglio, più
  scrivanie → elenco, nessuna → silenzio. Se sei in un progetto senza
  scrivanie aperte, le scrivanie degli altri progetti non ti riguardano.

Peso: 5 righe da ~150 caratteri più testa e piede fanno ~1k caratteri, ~250
token, sotto il tetto di 1,2k token che l'hook ha già.

## Il piano

Test prima del codice, come nella PR #12.

1. **Test che falliscono**, in `tests/test_resume_desk.py`:
   - cwd senza progetto, scrivanie aperte in due progetti → elenco con
     progetto ed età, ordine per data, piede con `project=`;
   - più di 5 scrivanie → 5 righe più "e altre N";
   - nessuna scrivania aperta da nessuna parte → silenzio;
   - cwd in un progetto senza scrivanie, con scrivanie altrove → silenzio
     (il comportamento di oggi, fissato da un test);
   - tetto di 1,2k token rispettato anche col fuori-progetto.
2. **`build()`**: il ramo `if not project` diventa `_recent(store, cwd)`, che
   usa `list_desks(project=None)` e `read_desk` solo per le prime 5 (serve il
   prossimo passo). Età calcolata da `updated_at`: "oggi", "ieri", "N g fa".
3. **Prova dal vivo**: VSCode aperto sulla home, `/clear`, il modello deve
   vedere le scrivanie nel contesto e saper dire su cosa si lavorava **senza
   tool call**.
4. **README** (sezione "Claude Code hooks") e **CHANGELOG** sotto
   `[Unreleased]`. `/code-review medium`, ogni finding in un commit suo.

## Dove va

PR piccola e sua, `feat/ripresa-fuori-progetto`, da `main`. Tocca solo l'hook
come la #12, mentre `feat/risposte-leggere` tocca il server MCP: temi diversi,
review più facili. **Si fa prima di `risposte-leggere`**, perché è piccola e
perché da domani ogni `/clear` dalla home costa di nuovo le stesse tool call.
Le due PR escono insieme nella 0.17.0, e la pagina `hooks.html` del sito
(passo 8 di `risposte-che-costano-meno`) descrive anche questo comportamento.

## Cosa non si fa

- Non si cambia il ripiego del server su `global`. Che le scrivanie aperte
  dalla home finiscano in `global` è un problema diverso, del momento in cui si
  **apre** una scrivania, non di quando la si riprende. Se serve, avrà un piano
  suo.
- Non si legge il dettaglio di una scrivania fuori progetto, nemmeno se è una
  sola: senza progetto non c'è modo di sapere quale delle tante sia quella
  giusta.
- Non si aggiunge un filtro per età: le 5 più recenti sono già il filtro, e
  l'età sulla riga basta per scegliere.

## Fatto quando

- Da `/Users/eliacinti`, dopo `/clear`, le scrivanie aperte più recenti sono
  nel contesto con progetto, età e prossimo passo, **provato dal vivo** in
  VSCode, e il modello riprende senza tool call di ricostruzione.
- Dentro un progetto il comportamento è identico a oggi, test compresi.
- Suite verde, README e CHANGELOG aggiornati, PR aperta.
