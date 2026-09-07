"""
La scrivania (P1): stato di lavoro che sopravvive alla finestra di contesto.

Indice soltanto — il contenuto vive nel file markdown, come per le memorie.
`filepath` è relativo alla brain dir, così un brain spostato resta valido.
"""

VERSION = 3
DESCRIPTION = "desks: indice delle scrivanie (il contenuto sta nei file)"


def up(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS desks (
            slug       TEXT NOT NULL,
            project    TEXT NOT NULL,
            title      TEXT NOT NULL,
            status     TEXT NOT NULL DEFAULT 'open',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            filepath   TEXT NOT NULL,
            PRIMARY KEY (project, slug)
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_desks_open "
        "ON desks(project, status, updated_at DESC)"
    )
