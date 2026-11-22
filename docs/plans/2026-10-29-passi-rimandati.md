# Dove va un passo nuovo: `add` con la posizione

*Piano — 29 Ott 2026. In attesa di approvazione. Nasce dalla scrivania
`la-cache-ha-un-orologio` (registro del 29 Ott, 13:19 e 13:46). Va dentro la PR
`feat/risposte-leggere` (piano `2026-10-28-risposte-che-costano-meno.md`), per
scelta di Elia del 29 Ott. Una prima versione proponeva una sezione `## Dopo`:
Elia ha chiesto di dare un ordine ai passi, e i dati qui sotto gli danno
ragione.*

## Il problema

`desk_log(add=[…])` mette i passi nuovi **in fondo** al `## Piano`
(`desk.add_steps`), mentre il cursore (`desk.next_step`) restituisce **il primo**
passo non spuntato. Chi aggiunge un passo sa dove va, ma il server non glielo
chiede.

Sui passi aperti di tutte le 13 scrivanie del brain, il 29 Ott:

| Scrivania | Cosa è successo |
|---|---|
| `feynotes/figure-per-ogni-corso…` | `F5b`, `F5c` (sotto-passi di F5) e «Prompt di corso…» stanno **dopo** `F11. [REVIEW] /code-review e chiusura`: il cursore proporrà la review e la chiusura prima delle correzioni |
| `feynotes/…` (preambolo TikZ) | `9. Preambolo TikZ` sta dopo `9. [REVIEW]` |
| `wadachi/la-cache-ha-un-orologio` | i passi «Ripresa fuori progetto» sono finiti dietro «Dopo la PR: accenti», e il cursore indicava quello (riordinato a mano il 29 Ott) |

L'ordine si sta già scrivendo a mano nelle etichette: `F5b`, `0b`, `6a`/`6b`,
`1:`, `2:`. È l'intenzione di chi aggiunge, e oggi il server la butta via.

Il cursore è ciò su cui contano `/loop` e `resume-desk.py`. Se indica il passo
sbagliato, il lavoro automatico parte dal passo sbagliato. In feynotes,
partirebbe dalla chiusura.

## L'approccio

**La posizione la decide chi aggiunge; il server la esegue e non la indovina
mai.** Capire che «Rilascio» viene dopo «Test» richiede di capire il testo, e il
server è deterministico. Mettere un modello dentro `desk_log` costerebbe token
e latenza a ogni passo, per una risposta che non sarebbe sempre la stessa.

- **`add=[…], before="<etichetta>"`** inserisce i passi nuovi subito prima di
  quel passo aperto. Vale l'etichetta intera o un suo **prefisso univoco**
  (`before="F6"`), così non si ricopia un'etichetta di 110 caratteri. Si usa
  `before` e non `after` perché due aggiunte davanti allo stesso passo restano
  in ordine (A, B, F6); con `after` si invertirebbero.
- **Niente accodamento silenzioso.** Se il Piano ha passi aperti e la chiamata
  ha `add` senza posizione, è **rifiutata per intero** (`done`, `note` e il
  resto compresi: niente scritture a metà). La risposta elenca i passi aperti
  in ordine e dice come rifarla. Per accodare in fondo lo si dice:
  `at_end=True`. Con il Piano finito o vuoto si accoda come oggi, perché non
  c'è niente da scavalcare.
- **Etichetta sconosciuta, ambigua o già spuntata** in `before`: errore con i
  passi aperti, nessuna scrittura. È la stessa forma di `done=…` sbagliato.
- **Dopo un'aggiunta riuscita**, la risposta contiene `open_steps`, cioè i
  passi aperti nell'ordine finale: chi ha aggiunto vede subito dove sono
  finiti.
- **Manuale della scrivania**, insieme alla regola del passo-ombrello già nel
  piano della PR: quello che non è un passo (un debito, un piano a parte, una
  cosa che si ripete «dopo ogni merge») va in `open_question`, non nel Piano.

## Passi

Si aggiungono alla scrivania `risposte-che-costano-meno`, **prima** di
«CHANGELOG, /code-review», così la review copre anche questo lavoro. Test prima
del codice.

1. **Test che falliscono**, in `tests/test_desk_format.py`,
   `test_desk_store.py` e `test_desk_tools.py`:
   - `before=` con etichetta intera e con prefisso univoco;
   - due aggiunte davanti allo stesso passo restano in ordine;
   - prefisso ambiguo, etichetta sconosciuta, passo già spuntato: errore e
     file identico;
   - `add` senza posizione con passi aperti: rifiutato, file identico anche se
     la chiamata aveva `done` e `note`, e la risposta elenca i passi aperti;
   - `at_end=True` accoda; Piano finito o vuoto: `add` senza posizione accoda;
   - `open_steps` nella risposta dopo un'aggiunta;
   - i tre casi veri della tabella, rifatti come fixture: il cursore indica il
     passo giusto.
2. **`desk.py`**: `add_steps(text, labels, before=None)` e la risoluzione
   dell'etichetta (intera o prefisso univoco, solo fra i passi aperti, fence
   esclusi come in `parse_plan`).
3. **`store.log_desk(before=…, at_end=…)`**: la verifica della posizione si fa
   **prima** di qualunque scrittura; `open_steps` nel risultato.
4. **Strumento `desk_log`**: parametri `before` e `at_end`, docstring.
   CHANGELOG: è un cambio di contratto (`add` senza posizione ora può essere
   rifiutato). Nessun chiamante automatico lo usa: cercato in Overmind il
   29 Ott.
5. **Manuale**: le due regole (ombrello, non-passi in `open_question`).
6. **Le scrivanie vere**, a mano e con la conferma di Elia: `F5b`/`F5c`/«Prompt
   di corso» prima di `F6`, `9. Preambolo TikZ` prima della review. «Dopo la
   PR: accenti» in `la-cache-ha-un-orologio` si spunta, perché lo chiude il
   piano della PR.

## Cosa non si fa

- **Sezione `## Dopo`**: risolveva uno solo dei tre casi.
- **Numeri gestiti dal server**: l'ordine è già la posizione nella lista e
  l'identità di un passo è la sua etichetta (`done=…`). I numeri andrebbero
  rinumerati a ogni inserimento, senza informazione in più.
- **Sotto-passi annidati**: coprirebbero `F5b`, ma richiedono parsing a livelli
  e regole per spuntare il padre; `before=` dà lo stesso ordine con una lista
  piatta.
- **Spostare un passo esistente**: per ora si fa a mano nel file, che è la
  verità.
- **Prefisso univoco anche in `done=…`**: utile, ma è un altro cambio. Si valuta
  dopo.

## Fatto quando

- Nei tre casi veri, rifatti come test, il cursore indica il passo giusto.
- Un `add` senza posizione su un Piano con passi aperti non scrive mai in fondo
  in silenzio.
- Manuale con le due regole. Suite verde, CHANGELOG `[Unreleased]` della PR.
- Le tre scrivanie vere riordinate (con la conferma di Elia).
