# La cache ha un orologio

*Piano — 26 Ott 2026. In attesa di approvazione. Segue
[2026-09-22-quando-cambiare-sessione](2026-09-22-quando-cambiare-sessione.md)
e va nella stessa PR (#12).*

## Il problema

Il piano del 22 settembre misura **quanto** pesa una sessione. Non guarda
**da quanto è ferma**, e lo spreco più grosso dipende dal tempo, non dal peso.

Il contesto di una sessione sta nella cache dei prompt per **un'ora dall'ultimo
turno**. Ogni turno la rinnova. Cosa costa un turno dipende quindi da quando
arriva (rapporti di prezzo pubblicati per le API: rilettura dalla cache 0,1×,
scrittura in cache da un'ora 2×, output 5×; sull'abbonamento i limiti non
sono pubblicati al token, ma seguono lo stesso principio):

| Con un contesto da 132k (misurato, sessione del 25–26 Ott) | Costo in token equivalenti |
|---|---|
| turno con cache calda | ~13k |
| **turno dopo più di 60 minuti di pausa**: tutto riscritto in cache | **~264k ≈ 20 turni caldi** |
| `/compact` prima di una pausa: lettura + riassunto + ricarica al ritorno | ~60k, con perdita di dettaglio |
| `/clear` con scrivania aggiornata, più ripresa | ~20k, senza perdite: la scrivania tiene tutto |

Due conseguenze:

1. **Il turno a cache fredda è lo spreco da colpire.** Arriva quando ci si
   alza e si torna, cioè di continuo, e nessuno lo vede.
2. **L'hook di settembre sbaglia i conti di un fattore 10.** Dice "continuare
   costa ~110k a turno", ma con la cache calda ne costa ~11k. Anche la formula
   del punto di pareggio di quel piano ignora la cache. Quel piano non si
   corregge (è datato): da qui in poi valgono questi conti.

## Cosa è possibile — verificato nel binario di Claude Code 2.1.280

- `UserPromptSubmit` accetta `decision: "block"`
  (`getUserPromptSubmitHookBlockingMessage`, "UserPromptSubmit operation blocked
  by hook"). Un messaggio bloccato **non arriva al modello**, quindi costa zero.
- `SessionStart` scatta anche dopo `/clear` ("SessionStart hooks after /clear").
  Il suo `additionalContext` entra nel contesto della sessione nuova.
- Il transcript registra un `timestamp` su ogni record dell'assistente, con il
  suo `usage`.

## Il piano

Tutto in `scripts/`, tutto aritmetica su file. Nessuna chiamata a un modello,
nessun tool MCP nuovo, nessuna modifica allo schema del brain.

### 1. La guardia della cache fredda — `session-weight.py`

Prima di ogni messaggio, l'hook legge il `timestamp` dell'ultimo turno
dell'assistente. Se sono passati più di `WADACHI_CACHE_TTL` secondi (default
3600) **e** il contesto supera `WADACHI_GUARD_MIN` (default 40k), il messaggio
riscriverebbe tutto in cache. In quel caso l'hook **lo blocca**, e il motivo
lo vede Elia, non il modello:

> Cache scaduta da 2 h 14 min: questo messaggio riscriverebbe 132k token
> (≈ 20 turni normali). Scrivania `il-loop-di-overmind…` aggiornata alle 06:12,
> dopo l'ultimo turno → `/clear` riparte da lì. Per proseguire comunque,
> rimanda il messaggio.

- **Blocca una volta sola per pausa.** Il marker è legato al timestamp
  dell'ultimo turno, quindi il secondo invio passa.
- **Dice se la scrivania è aggiornata.** Se l'ultimo `updated` è precedente
  all'ultimo turno, lo dice ("ferma da prima dell'ultimo turno: valuta prima di
  `/clear`"). La decisione resta di Elia.
- `WADACHI_CACHE_GUARD=off` la spegne.
- Qualunque errore (transcript assente, timestamp illeggibile, brain non
  montato) produce **uscita 0 e silenzio**, come oggi: la guardia non deve
  mai rompere un turno.

### 2. La ripresa dopo `/clear` — `scripts/resume-desk.py`, hook `SessionStart`

Su `startup` e `clear`, lo script rileva il progetto dal `cwd` con la stessa
logica del server (importata dal pacchetto, non riscritta) e legge le scrivanie
aperte direttamente dai file del brain:

- **una scrivania aperta:** inietta titolo, obiettivo, "fatto quando", il
  prossimo passo (prima checkbox non spuntata), le ultime due voci del
  registro e la sezione "Aperto". Tetto ~1,2k token;
- **più scrivanie aperte:** per ognuna slug e prossimo passo, senza sceglierne
  una;
- **nessuna scrivania:** silenzio.

Così `/clear` diventa "riparti dal punto giusto": per continuare non serve
`get_context`, né un `desk_read` a mano.

### 3. Il conto alla rovescia — `statusline.sh`

`cache 42m` accanto al peso, e `cache fredda` quando è scaduta. È passivo e
costa zero token: Elia sa quando gli conviene un `/clear` prima di alzarsi.

### 4. Conti onesti — i messaggi di `session-weight.py`

Le soglie di peso restano (50/75/90), ma i messaggi dicono il costo vero: il
turno caldo (contesto × 0,1), il turno freddo (× 2), la compattazione
automatica vicina. I rapporti stanno in costanti con nome e con la fonte
accanto, e la durata della cache è sovrascrivibile da variabile d'ambiente:
in caso di sforamento del piano la durata scende a 5 minuti.

## Il presupposto: la scrivania sempre aggiornata

La guardia funziona solo se `/clear` è sicuro, e `/clear` è sicuro solo se la
scrivania è aggiornata **prima** della pausa. Chiedere al modello un
`desk_log` dopo la pausa costerebbe proprio il turno freddo che si vuole
evitare. La regola esiste già (`desk_log` dopo ogni passo): questo piano la
rende quella che fa risparmiare.

## Test — prima del codice

In `tests/`, con fixture nella **forma reale**: record del transcript copiati
dalla struttura di un transcript vero (`type`, `timestamp`, `message.usage`),
e file di scrivania nel formato che il server scrive davvero. Vale la memoria
*un fixture che mente*: un finto semplificato renderebbe la suite verde e
cieca.

- pausa > TTL e contesto grande → blocco; secondo invio → passa;
- pausa > TTL e contesto piccolo → silenzio; pausa < TTL → silenzio;
- scrivania ferma da prima dell'ultimo turno → il messaggio lo dice;
- `WADACHI_CACHE_GUARD=off` → silenzio;
- transcript senza timestamp / malformato / brain assente → uscita 0, muto;
- ripresa: una scrivania, più scrivanie, nessuna; testo sotto il tetto;
- statusline: minuti residui e `cache fredda`.

## Fatto quando

- Un messaggio inviato dopo più di un'ora, su una sessione oltre 40k, viene
  bloccato **una volta**, con costo stimato e stato della scrivania; il
  secondo invio passa.
- Dopo `/clear` la sessione nuova parte con la scrivania del progetto nel
  contesto, senza tool call.
- La statusline mostra i minuti di cache residui.
- I messaggi di peso dicono il costo con la cache, non senza.
- Suite verde; nessun hook può far fallire un turno.
- Hook registrati in `~/.claude/settings.json`, con conferma di Elia prima di
  toccarlo. Prova dal vivo: pausa > 1 h, blocco visto, `/clear`, ripresa vista.

## Cosa NON si fa

- Nessun `/compact` a tempo. Mentre si lavora la cache si rinnova da sola, e un
  compact periodico costerebbe token e dettaglio senza motivo.
- Non si chiude né si compatta niente da soli: il blocco ferma e spiega, la
  scelta resta di Elia.
- Nessun tool MCP nuovo, nessun modello chiamato per decidere.
