# Quando cambiare sessione

*Piano — 22 Set 2026. In attesa di approvazione.*

## Il problema

Una chat lunga **si ripaga a ogni turno**: il contesto intero viene rifatturato
a ogni messaggio, quindi il costo di una sessione cresce con il quadrato della
sua durata, non linearmente.

Già misurato, memoria #243 (16 Set 2026, €20 spariti in un giorno):

```
Task 7, stesso agente ripreso:  274k → 311k → 456k → 589k token in 4 giri
Task 8, agente fresco:          218k token per lo stesso lavoro
```

Un agente fresco che legge il brief da file parte da ~60k e fa lo stesso lavoro
a **un terzo** del costo. La regola era già stata scritta allora — *«chiudere e
ripartire da una memoria è più economico che continuare»* — ma **non è mai stata
applicata**, perché nessuno dice quando si è passato il punto di pareggio. Si
scopre a fine mese, dalla fattura.

## Cosa manca, esattamente

Non manca la macchina per salvare: la scrivania fa già esattamente quello.
Manca **il segnale**. Serve qualcosa che misuri il peso della sessione e lo dica
al momento giusto, a chi può agire.

## Cosa è possibile — verificato, non dedotto

Letto dal binario di Claude Code 2.1.278 (`strings`, non indovinato):

| Meccanismo | Cosa riceve | Chi lo vede |
|---|---|---|
| **statusline** | `context_window_size`, `current_usage`, `used_percentage`, `remaining_percentage`, `exceeds_200k_tokens` | Elia, di continuo |
| **hook** | `transcript_path`, `cwd`, `session_id` | lo script |
| `hookSpecificOutput.additionalContext` | — | **il modello**: il testo viene iniettato nel contesto |

Il terzo è il pezzo che rende la cosa possibile: un hook **può parlare a
Claude**, non solo all'utente.

⚠️ Vincolo noto (memoria #207): con `ANTHROPIC_API_KEY` esportata in `~/.zshrc`
le quote del piano non esistono (`rate_limits_available: false`). Il segnale
deve quindi basarsi sul **peso del contesto**, non sulla quota residua.

## Il piano

### 1. `scripts/session-weight.py` — la misura

Legge `transcript_path`, prende l'ultimo record con `usage`, somma
`input_tokens + cache_read_input_tokens + cache_creation_input_tokens`, lo
rapporta a `context_window_size`. Nessuna stima: sono i numeri che la CLI ha
già scritto.

### 2. L'hook `UserPromptSubmit` — il segnale

Gira prima di ogni messaggio. Sotto soglia non dice niente (silenzio = costo
zero). Sopra soglia inietta `additionalContext`:

| Peso | Cosa dice |
|---|---|
| < 50% | niente |
| 50–75% | una riga: peso attuale, e che da qui in poi ogni turno costa quel tanto |
| > 75% | invita a chiudere: distilla nella scrivania, apri una sessione nuova |
| > 90% | lo dice come raccomandazione ferma, prima che scatti la compattazione |

La soglia sta in una variabile d'ambiente, non nel codice.

### 3. La statusline — per Elia

`used_percentage` sempre visibile. È passiva e costa zero token: Elia vede il
peso salire senza che nessuno glielo dica.

### 4. Nessun tool nuovo in wadachi

La scrivania è già il posto giusto: `desk_log` tiene il registro,
`desk(action="close", distil=…)` produce il riassunto, `desk_read` riprende in
una sessione nuova. **Aggiungere un tool sarebbe duplicare una cosa che c'è.**

## Il punto di pareggio, esplicitato

Ripartire non è gratis: costa la distillazione più il `get_context` +
`desk_read` della sessione nuova — circa **15–20k token**. Conviene quando

```
peso_attuale × turni_rimasti  >  20k + (peso_fresco × turni_rimasti)
```

che con un contesto da 100k e un ripartenza da 20k si semplifica in: **conviene
quasi sempre, se restano più di due o tre turni di lavoro.** Sotto i due turni,
no: si finisce e basta. Per questo la soglia bassa avvisa e non insiste.

## Fatto quando

- Una sessione oltre il 75% riceve l'invito **una volta sola**, non a ogni turno.
- Sotto soglia l'hook non produce output e non appare da nessuna parte.
- Con `ANTHROPIC_API_KEY` impostata funziona comunque (misura il contesto, non la quota).
- Un transcript assente o illeggibile **non rompe il turno**: l'hook esce 0 e muto.
- La statusline mostra la percentuale senza rallentare il prompt.

## Cosa NON si fa

- Non si compatta e non si chiude niente da soli: la decisione resta di Elia.
- Non si chiama un modello per decidere: è aritmetica su un file, costo zero.
- Non si aggiunge un tool MCP, non si tocca lo schema del brain.
