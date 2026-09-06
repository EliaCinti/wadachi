# La scrivania — stato di lavoro che sopravvive alla finestra di contesto

- **Data:** 2026-09-06
- **Stato:** proposto, in attesa di approvazione
- **Progetto:** Wadachi (P1 del piano harness/loop — vedi memoria #223, decisione D39)

## Il problema

Wadachi ricorda **quello che hai imparato**. Non ricorda **quello che stai facendo**.

La prova sta nel brain stesso: la memoria #222 si apre con «Elia cambia chat perché il
contesto è cresciuto troppo» ed è millecinquecento parole di consegna scritte a mano.
**Quella memoria esiste perché la scrivania non esiste.** Ogni volta che una sessione si
allunga, lo stato del lavoro in corso — il piano, cosa è già stato provato, dove si era
rimasti — o viene perso dalla compattazione o viene ricopiato a mano.

## Cos'è

Un **progress record**: un file markdown per filo di lavoro, che il modello scrive mentre
lavora e rilegge quando riprende. Vive accanto alle memorie e **non dentro** di esse.

Serve due letture della stessa cosa:

- **(a) continuità** — una sessione nuova legge *dove siamo, perché, cosa resta aperto*;
- **(b) esecuzione a passi** — chi lavora legge *il piano, il prossimo passo, cosa ha già
  fallito*, con contesto fresco a ogni passo.

Entrambe funzionano **senza Overmind**: il cliente è qualunque sessione MCP.

### Il confine, che è quello già pubblicato

> **Wadachi tiene lo stato dei passi, non li esegue.** Dice «sei al passo 3 di 7, il 4 l'hai
> provato ed è fallito così»; non decide di lanciare il 4.

Nella scrivania non entra **nessun** concetto di Overmind: niente azienda, agente,
`ExecutionKind`. Solo un filo di lavoro, un piano, un cursore, e cosa è stato provato.

## Da dove viene il progetto

- **Simone Rizzo** (il video da cui nasce la richiesta): un harness «re-inizializza l'agente
  passo dopo passo **per completare un compito a step**, facendolo ripartire esattamente dal
  punto in cui si era fermato». Nella sua dimostrazione il 320× non nasce da un'idea
  brillante ma da tre cose: un obiettivo che una macchina misura, un tetto di dieci
  tentativi, e l'istruzione di **documentare ogni modifica**.
- **Lilian Weng**: «a harness should not carry the entire workflow and all logs in context;
  instead, it should keep durable state **in files**», con gli artefatti che crescono **per
  rollout**.
- **Il pattern Anthropic** citato da Wikipedia: un agente che «sceglie ripetutamente il
  prossimo compito non finito, committa, e **aggiorna un progress record** prima di fermarsi».

Le tre fonti convergono sulla stessa unità: **il compito**, non la sessione né il progetto.

## 1 · La forma del file

`~/.wadachi/desks/<progetto>/<slug>.md`

```markdown
---
type: desk
slug: m34-slice4-signin
title: M34 fetta 4 — sign_in
project: overmind
status: open          # open | done | abandoned
created: 2026-09-06T18:40:00+00:00
updated: 2026-09-06T21:12:00+00:00
---

## Obiettivo
Spostare `sign_in` dentro il tratto Provider, senza copiarlo.
**Fatto quando:** la suite passa e `scrub_secrets` non si ancora più a `sk-ant`.

## Piano
- [x] Leggere `claude_auth.rs` e mappare la macchina a stati
- [ ] Estrarre `sign_in` nel tratto          ← prossimo
- [ ] Generalizzare `scrub_secrets`

## Registro
- **21:04** — provato a tenere `token_path` fisso: **fallito**, il provider B sovrascrive
  il token di A. Serve un percorso per provider.

## Aperto
- `backup.rs` ha la stessa forma di `token_path`: insieme o dopo?
```

**Quattro scelte, con la loro ragione:**

1. **`Fatto quando` è obbligatorio.** È la condizione d'arresto verificabile. Senza, non è
   una scrivania: è un diario. Se non si sa scrivere, il compito non è ancora definito — ed
   è un'informazione utile, non un ostacolo.
2. **Il piano è una lista di spunta markdown.** «Il prossimo compito non finito» diventa «il
   primo `- [ ]`»: una riga di parsing, e resta modificabile a mano in Obsidian.
3. **Il registro è cronologico inverso.** Rileggendolo con un budget di token si taglia la
   coda vecchia invece della testa fresca.
4. **Il registro tiene i fallimenti.** «Provato X, fallito perché Y» è ciò che evita di
   riprovare; i successi sono già visibili come spunte.

Fuori di proposito: priorità, stime, assegnatari, sotto-passi annidati.

## 2 · Gli strumenti — tre, non cinque

Ricerca del 6 Sep 2026: **la scelta dello strumento giusto degrada oltre i 20-25 strumenti**,
e Wadachi ne ha già 33 (di cui **19 mai chiamati** in 741 trascrizioni — memoria #226).
Anthropic: «più strumenti non portano sempre a risultati migliori», meglio **consolidare**.
Cinque strumenti nuovi porterebbero a 38: peggiorerebbero un problema mentre ne risolvono
un altro. Quindi tre.

| Strumento | Cosa fa |
|---|---|
| **`desk(action, …)`** | `open` (rifiuta senza `done_when`) · `close` (`done`/`abandoned`, con `distil` opzionale) · `list` |
| **`desk_read(slug?)`** | il file, più il prossimo passo già estratto. Alta frequenza. |
| **`desk_log(slug?, done?, note?, add_steps?)`** | spunta un passo **e/o** annota **e/o** aggiunge passi, in una chiamata. Restituisce il prossimo passo. |

**`slug` è quasi sempre opzionale**: il progetto viene dal `cwd` (reso affidabile dal
marcatore `.wadachi` e dalla corrispondenza più specifica), e da lì la scrivania aperta. Se
ce n'è più d'una, gli strumenti **chiedono invece di scegliere**.

**Non esiste `desk_write`.** Nessuno strumento riscrive il file intero: è ciò che rende
sicura la concorrenza (§4).

**Le descrizioni dicono *quando*, non solo *cosa*** — con il manuale come risorsa MCP
separata (progressive disclosure). I 19 strumenti mai chiamati sono la prova sperimentale
che una buona funzione con una descrizione tiepida non viene scelta mai.

## 3 · Come una sessione nuova la trova

`get_context` — lo strumento che apre ogni sessione — la mostra **in cima**, prima delle
memorie: «dove eravamo» viene prima di «cosa sappiamo».

```
## 🖿 scrivania aperta — m34-slice4-signin
**M34 fetta 4 — sign_in** · aggiornata 2h fa
Obiettivo: …  ·  Fatto quando: …
Prossimo passo: **estrarre `sign_in` nel tratto**  (2 di 5 fatti)
Ultimo dal registro: provato a tenere `token_path` fisso → fallito, B sovrascrive A.
→ desk_read() per il resto
```

Quattro regole: un **riassunto** (~100 token), non il file; **più di una → le elenca e non
sceglie**; **nessuna → non dice niente** (chi non usa le scrivanie non ne paga il costo);
una ferma da N giorni compare come «ancora aperta?» — **propone, non chiude**.

## 4 · Concorrenza

Una memoria si scrive una volta; una scrivania è un file che **più sessioni modificano in
append**. Con la sola scrittura atomica, l'ultimo che scrive vince e l'altro contributo
sparisce in silenzio.

Tutte le operazioni sono **aggiunte a una sezione**: rileggi da disco → applica il
cambiamento minimo → riscrivi con `_atomic_write_text`, dentro `_write()` (`BEGIN
IMMEDIATE`), che serializza già i processi. Il file è la verità, il lock del database è il
turno.

**Il caso che conta è la collisione di lavoro, non di file:** se due spuntano lo stesso
passo, `desk_log` risponde «era già fatto (4 min fa) — il prossimo è il 4». Non un errore:
un'informazione, come i `collisions` già esistenti per le memorie.

## 5 · La chiusura — l'unico punto in cui i due strati si toccano

Alla chiusura una scrivania produce **al massimo una memoria**, scritta da chi ha fatto il
lavoro:

- **`distil` dato** → nasce una memoria vera, con un `[[slug]]` alla scrivania archiviata;
- **`distil` omesso** → non nasce niente.

**Il file non si cancella mai**: va in `desks/<progetto>/archived/`, leggibile, fuori dal
richiamo. È la regola «memories are sacred» applicata anche a ciò che memoria non è.

**Nessun riassunto automatico**: sarebbe un testo generato che *sembra* conoscenza e che
nessuno ha verificato. La chiusura può **proporre** (obiettivo, spunte, registro come
traccia); il testo lo scrive chi c'era. Ed è giusto che non ogni scrivania diventi una
memoria: il valore sta nella sorpresa, e un `abandoned` — «provato X, non funziona perché
Y» — vale spesso più di un `done` liscio.

**Cosa non succede mai:** la scrivania non entra in `recall` né in `recall_associative`
(aperta o archiviata), non ha embedding, non ha credenze né versioning. Tenere i due strati
separati protegge il richiamo: `procedural.py` documenta già un caso in cui l'ordinamento
per recenza **ha nascosto la regola giusta e ha fatto ripetere lo stesso errore due volte**.

## 6 · Le promesse, e il test che tiene ciascuna

**Ciclo di vita** — una scrivania si apre e si ritrova · senza `done_when` non si apre
(nessun file creato) · il prossimo passo è il primo non spuntato, anche a spunte sparse ·
piano finito → lo dice e invita a chiudere.

**Ripresa** — *(il test che conta)* apri, registra, poi **uno store nuovo di zecca**:
`desk_read()` senza slug ritrova scrivania e passo giusto · `get_context` la mette in cima ·
due scrivanie → le elenca e non sceglie · nessuna → non nomina la parola.

**Concorrenza** — due note alternate a due letture → **entrambe** nel registro · passo già
spuntato → «era già fatto» e il prossimo, senza errore · file mai troncato.

**Il confine** — una scrivania **non compare in `recall`** (testo molto specifico, zero
risultati) · chiudere senza `distil` non crea memorie · con `distil` ne crea **una**, che
contiene `[[slug]]` · chiudere non cancella nulla.

**Due test di progetto, non di codice** — il ciclo intero (apri → tre log → chiudi con
distillato → una sessione nuova ricorda la lezione ma **non** il rumore del registro), e
**il caso di Rizzo**: dieci tentativi registrati, tetto raggiunto, e il decimo `desk_log`
risponde «dieci tentativi e il `Fatto quando` non è soddisfatto» invece di un undicesimo
passo. È la condizione d'arresto, ed è ciò che separa un loop da una fuga.

## Migrazione

`0003_desks.py`: una tabella **indice** (slug, titolo, progetto, stato, date, percorso), mai
contenuto — che vive nel file, come per le memorie. Nessuna migrazione di dati esistenti:
non c'è nulla da migrare.

## Cosa resta fuori, di proposito

Riapertura di una scrivania chiusa (il registro è già distillato: riaprire mescola due
storie) · scrivanie condivise fra progetti · gerarchie di sotto-compiti · qualunque
esecuzione. Se servissero, arriveranno con un caso reale che le chiede.
