# Risposte che costano meno

*Piano — 28 Ott 2026. In attesa di approvazione. Nasce dalla memoria #304
(misurata riprendendo Overmind il 27 Ott) e chiude l'ultimo passo della
scrivania `la-cache-ha-un-orologio` ("valutare lo spreco dei testi con lettere
accentate"): l'analisi sta qui sotto, non in un file a parte, perché è corta e
serve solo a giustificare questo piano.*

## Il problema

Ogni ripresa di lavoro passa da `desk_read`, `get_context`, `recall`,
`desk_log`. Quello che restituiscono entra nel contesto e lo si ripaga a ogni
turno successivo della sessione. Due difetti lo gonfiano, in tutti i progetti.

### 1. `desk_read` restituisce tutto il registro

Il registro cresce di una voce a ogni tentativo e non si accorcia mai. Per
riprendere serve il piano, la prossima mossa e le ultime due o tre voci: le
altre sono storia.

| Scrivania | Testo | di cui registro |
|---|---|---|
| `m36` di Overmind, 27 Ott (28 voci dal 7 Set) | ~20 KB, ~7-8k token | quasi tutto |
| `m36a-i-freni` (oggi) | 4,5 KB | 2,3 KB, 3 voci (52%) |
| `la-cache-ha-un-orologio` (oggi) | 5,8 KB | 4,1 KB, 8 voci (72%) |

### 2. Il testo arriva serializzato due volte, con gli escape ASCII

Gli strumenti restituiscono una stringa JSON fatta con `json.dumps(…)`, cioè
con `ensure_ascii=True`. FastMCP (mcp 1.28) la avvolge poi in
`{"result": "<stringa>"}`, perché il tipo di ritorno è `str`. Sul filo `è`
diventa `\\u00e8` (7 caratteri), un a capo diventa `\\n`, una virgoletta `\\\"`.

Misurato su tutti i 325 `.md` del brain (1,25 M caratteri):

| Codifica | Caratteri sul filo | Sopra il testo |
|---|---|---|
| oggi | 1,36 M | **+9%** |
| solo `ensure_ascii=False` | 1,31 M | +5% |
| `ensure_ascii=False` + un solo livello | 1,27 M | **+2%** |

Le lettere accentate sono solo lo 0,7% dei caratteri: **lo spreco degli
accenti esiste, ma è il minore dei due.** In token pesa probabilmente più che in
caratteri, perché le sequenze di escape si spezzano male, ma questo non è
misurato (servirebbe `count_tokens`, cioè una chiave API: vedi passo 6).

## Cosa è possibile — verificato nel codice

- Tutti gli strumenti passano da un solo decoratore, `tool()` in
  `wadachi/server.py:95`, che chiama `mcp.tool(...)`. `FastMCP.tool` accetta
  `structured_output: bool | None`: con `False` sparisce l'involucro
  `{"result": …}` e resta solo il contenuto testuale. È **una riga**.
- In `server.py` ci sono 53 `json.dumps`: tutti diventano un `_dumps()` locale
  con `ensure_ascii=False`. Il cambiamento è meccanico.
- `read_desk` in `store.py:956` restituisce `text` intero. Le voci di registro
  sono le righe `- **`: questa regola è già usata e testata da
  `scripts/resume-desk.py`.

## Il piano

Test prima del codice, come nella PR #12.

1. **Test che falliscono.**
   - `desk_read` su una scrivania con 8 voci restituisce le ultime 3, più una
     riga che dice quante ne ha omesse e come averle (`full=True`).
   - Con `full=True` il testo è identico al file.
   - Piano, `Obiettivo`, `Fatto quando` e `Aperto` ci sono sempre, interi.
   - Nessuna risposta di uno strumento contiene `\u00`, e l'output non è
     avvolto in `{"result": …}`. Il test passa per il client in-memory di mcp,
     non per la funzione Python, altrimenti l'involucro non si vede.
2. **`desk_read(full: bool = False)`.** Il taglio si fa in `store.read_desk`,
   che restituisce anche `log_total` e `log_shown`. Il file su disco non si
   tocca. Tre voci di default: è il numero che `resume-desk.py` riesce già a
   mostrare sotto il suo tetto di 1,2k token.
3. **`_dumps()` con `ensure_ascii=False`** al posto dei 53 `json.dumps` di
   `server.py`. `web.py` e `store.py` restano come sono: scrivono su disco o
   sul browser, non nel contesto.
4. **`structured_output=False` nel decoratore `tool()`.** Prima su un solo
   strumento, provato dal vivo in Claude Code, per vedere che il testo arrivi
   leggibile. Poi su tutti.
5. **Manuale della scrivania.** Una regola dalla #304: niente passo-ombrello
   sopra i sotto-passi, perché `desk_log` restituirebbe sempre lo stesso passo
   e il cursore si blocca.
6. **Misura prima/dopo** sul brain vero, in caratteri, per `desk_read`,
   `get_context` e `recall`. Facoltativo: in token con `count_tokens` tramite
   `con-chiavi`. L'endpoint è gratuito ma usa la chiave, quindi si fa solo se
   Elia dice sì.
7. **CHANGELOG** sotto `[Unreleased]`, `/code-review medium`, ogni finding in un
   commit suo.

### Dopo il codice: sito e rilascio 0.17.0

8. **Sito e wiki** (`demo/`): oggi nessuna pagina parla di hook, statusline,
   guardia della cache o ripresa dopo `/clear`. Va aggiunta una pagina wiki
   `hooks.html`, generata da `wiki-src` come le altre, più una riga in
   `tools.html` per `desk_read(full=…)`. Il numero di versione si cambia solo
   quando PyPI ha davvero la 0.17.0 (lezione della #5).
9. **Rilascio 0.17.0**: versione in `pyproject.toml`, CHANGELOG datato, tag,
   PyPI, deploy del sito. Ogni passo che pubblica si fa solo con la conferma di
   Elia, al momento.

## Dove va

PR nuova, `feat/risposte-leggere`, da `main` **dopo** il merge della #12. La
#12 è già grande e ha un tema suo (il tempo della sessione), mentre questa
tocca il server MCP e non gli hook. Le due escono insieme nella 0.17.0.

## Cosa non si fa

- Non si accorcia il file della scrivania: il registro intero resta su disco ed
  è memoria.
- Non si cambia il formato di `get_context` (markdown denso): lì guadagna solo
  il punto 4, l'involucro.
- Non si cambia il tipo di ritorno degli strumenti da `str` a `dict`: sarebbe
  un secondo schema da mantenere, per lo stesso risultato del punto 4.

## Fatto quando

- `desk_read` sulla scrivania `la-cache-ha-un-orologio` restituisce meno della
  metà dei caratteri di oggi (6,7k), e `full=True` restituisce il file intero.
- Nessuna risposta MCP contiene `\u00` o l'involucro `{"result": …}`, provato
  dal vivo in Claude Code.
- Suite verde, CHANGELOG aggiornato, sito con la pagina degli hook, 0.17.0 su
  PyPI e sul sito.
