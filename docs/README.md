# docs/

Ogni `.md` di questo repo sta qui, e **il nome dice che tipo di documento è**.

| Forma | Cos'è |
|---|---|
| `NOME.md` — maiuscolo, senza data | documento **vivo**, tenuto vero |
| `adr/NNNN-slug.md` | una **decisione**: cosa, perché, cosa è stato scartato |
| `plans/AAAA-MM-GG-slug.md` | un **piano**, scritto prima del codice e approvato |
| `analysis/AAAA-MM-GG-slug.md` | un'**analisi**, un audit, un'indagine |

Una regola sola: **se resta vero è maiuscolo e senza data; se è la fotografia di
un momento, la data viene prima.**

Da lì discende il resto:

- Un documento vivo **si aggiorna**, non si archivia. Uno diventato falso è un
  bug, non storia.
- Un'ADR **non si riscrive mai**: una decisione rivelatasi sbagliata viene
  superata da una nuova ADR, e la vecchia resta a dire cosa si credeva allora.
- Un piano o un'analisi **non si aggiornano**: è a questo che serve la data. Se
  producono una verità duratura, quella migra in un documento vivo o in un'ADR,
  e il file datato resta come traccia di come ci si è arrivati.

Slug in minuscolo con trattini.
