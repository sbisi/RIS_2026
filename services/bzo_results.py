"""Gemeinsamer Zugriff auf das Ergebnis-CSV des BZO-Crawlers (scripts/bzo_crawler.py) -
liest data/audit/bzo_ergebnisse.csv. Eigene, schlanke Funktion hier statt Import aus
pages/reglement_update.py oder pages/reglement_search.py: pages/*.py-Module dürfen sich laut
Projektkonvention nicht gegenseitig importieren (Dash fuehrt jede Datei in pages/ eigenstaendig
aus - ein Cross-Import wuerde Callbacks doppelt registrieren)."""
from pathlib import Path

import pandas as pd

CSV_PATH = Path(__file__).resolve().parent.parent / 'data' / 'audit' / 'bzo_ergebnisse.csv'


def bzo_documents_for_bfs(bfs):
    """Liefert die vom BZO-Crawler gefundenen Dokumente (status='ok') fuer eine Gemeinde
    (BFS-Nr.) als Liste von {'title':, 'url':} - unverifizierte Suchmaschinen-Treffer, siehe
    Datenqualitaets-Hinweis auf den Crawler-Seiten (Update Reglemente/Scrawling Reglemente)."""
    if not bfs or not CSV_PATH.exists():
        return []
    df = pd.read_csv(CSV_PATH, dtype=str)
    if 'bfs_nr' not in df.columns or 'status' not in df.columns:
        return []
    match = df[(df['bfs_nr'] == str(int(bfs))) & (df['status'] == 'ok')]
    if match.empty:
        return []
    docs = []
    for rec in match.to_dict('records'):
        url = rec.get('pdf_url') or ''
        if not url:
            continue
        title = (rec.get('document_title') or '').strip() or 'Dokument'
        docs.append({'title': title, 'url': url})
    return docs
