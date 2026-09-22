"""Update Reglemente: Status-Report des BZO-Crawlers (separates Offline-Skript unter
scripts/bzo_crawler.py), der pro Gemeinde prüft, ob ein aktuelles Bau-/Zonenreglement (BZO)
online gefunden werden kann. Diese Seite startet den Crawler NICHT selbst (Laufzeit über alle
~2000 Schweizer Gemeinden: mehrere Stunden, dazu abhängig von einer inoffiziellen Suchmaschinen-
API - ungeeignet für einen synchronen Dash-Callback). Sie liest nur das CSV-Ergebnisprotokoll
des letzten (manuell/per Cron ausgeführten) Laufs.

Zusammengeführt aus den vormals getrennten Seiten "Update Reglemente" (Status-Report, alle
Status inkl. nicht gefunden/fehlgeschlagen) und "Scrawling Reglemente" (Dokumenttyp-Erkennung,
Freitextsuche, Typ-Verteilung) - eine Seite statt zwei, da beide dieselbe CSV auswerten."""
import os
import re
from pathlib import Path

import dash
import pandas as pd
from dash import html, dcc, callback, Input, Output

from components.page_header import page_shell
from components.cards import section_card, empty_state, kpi
from components.filters import dropdown_filter, filter_bar, reset_button
from components.tables import styled_table
from components.charts import bar, CHART_CONFIG

dash.register_page(__name__, path='/update-reglement', name='Update Reglemente')

CSV_PATH = Path(__file__).resolve().parent.parent / 'data' / 'audit' / 'bzo_ergebnisse.csv'

STATUS_LABELS = {'ok': 'Gefunden', 'not_found': 'Nicht gefunden', 'download_failed': 'Download fehlgeschlagen'}

# local_comparison kommt aus dem Abgleich mit dem lokalen Reglemente-Archiv (data/Reglemente/) -
# vergleicht, wo vorhanden, das HTTP Last-Modified-Datum der Online-Quelle mit dem lokalen
# Dateidatum. 'unbekannt' ist der ehrliche Regelfall (viele Gemeinde-Websites liefern keinen
# Last-Modified-Header), keine geratene Aussage.
COMPARISON_LABELS = {
    'online_neuer': '🆕 Neuere Version vorhanden',
    'lokal_aktuell': 'Lokal aktuell',
    'unbekannt': 'Unbekannt (kein Last-Modified-Header)',
    'kein_online_treffer': 'Nur lokal vorhanden',
    'neu_online_gefunden': 'Neu online gefunden (lokal fehlt)',
}
# Marker-Text exakt wie in COMPARISON_LABELS['online_neuer'] - dient als filter_query-Wert für
# die Zeilenhervorhebung in der Tabelle (siehe update_table()).
NEWER_VERSION_LABEL = COMPARISON_LABELS['online_neuer']

# Reglement-Typen: V1-Erkennung aus dem Dokumenttitel (Stichwort-Abgleich). Später: eigene
# DuckDB-Taxonomie statt Text-Heuristik.
REGULATION_TYPES = {
    'BNO': ['bau- und nutzungsordnung', 'bau und nutzungsordnung', 'bno'],
    'BZO': ['bau- und zonenordnung', 'bau und zonenordnung', 'bzo'],
    'BZR': ['bau- und zonenreglement', 'bau und zonenreglement', 'bzr'],
    'Baureglement': ['baureglement', 'gemeindebaureglement'],
    'Bauordnung': ['bauordnung'],
    'Zonenreglement': ['zonenreglement'],
    'RCU': ["règlement communal d'urbanisme", "reglement communal d'urbanisme"],
    'RCCZ': ['règlement communal des constructions', 'rccz'],
    'NAPR': ['norme di attuazione', 'napr'],
}

COLS = [
    {'name': 'Gemeinde', 'id': 'name'},
    {'name': 'Kanton', 'id': 'canton'},
    {'name': 'BFS-Nr', 'id': 'bfs_nr'},
    {'name': 'Typ', 'id': 'regulation_type'},
    {'name': 'Dokument', 'id': 'document_title'},
    {'name': 'Status', 'id': 'status_label'},
    {'name': 'Lokal vorhanden', 'id': 'local_present'},
    {'name': 'Vergleich', 'id': 'comparison_label'},
    {'name': 'Link', 'id': 'pdf_link', 'presentation': 'markdown'},
]


def _detect_regulation_type(title):
    """Versucht aus dem Dokumenttitel den Reglementtyp zu erkennen."""
    if not title:
        return 'Sonstige'
    text = str(title).lower()
    for reg_type, aliases in REGULATION_TYPES.items():
        if any(alias in text for alias in aliases):
            return reg_type
    return 'Sonstige'


def _load_results():
    if not CSV_PATH.exists():
        return None
    df = pd.read_csv(CSV_PATH, dtype=str)
    df['status'] = df['status'].fillna('')
    # Ältere CSVs (vor dem lokalen Abgleich bzw. vor Mehrfach-Dokumenten je Gemeinde) haben diese
    # Spalten evtl. noch nicht - defensiv nachfüllen statt beim Lesen zu crashen.
    for col in ('local_reglement_path', 'local_comparison', 'document_title'):
        if col not in df.columns:
            df[col] = ''
    df['local_reglement_path'] = df['local_reglement_path'].fillna('')
    df['local_comparison'] = df['local_comparison'].fillna('')
    df['document_title'] = df['document_title'].fillna('')
    df['regulation_type'] = df['document_title'].apply(_detect_regulation_type)
    return df


def _filter_bar(df):
    cantons = sorted(c for c in df['canton'].dropna().unique() if c)
    canton_options = [{'label': c, 'value': c} for c in cantons]
    statuses = sorted(s for s in df['status'].unique() if s)
    status_options = [{'label': STATUS_LABELS.get(s, s), 'value': s} for s in statuses]
    comparisons = sorted(c for c in df['local_comparison'].unique() if c)
    comparison_options = [{'label': COMPARISON_LABELS.get(c, c), 'value': c} for c in comparisons]
    reg_types = sorted(t for t in df['regulation_type'].unique() if t)
    type_options = [{'label': t, 'value': t} for t in reg_types]
    return filter_bar(
        html.Div([
            html.Div('Suche', className='filter-label'),
            dcc.Input(id='crawl-search', type='text', placeholder='Gemeinde, BFS-Nr. oder Dokument…',
                      debounce=True, style={'width': '220px', 'height': '38px', 'padding': '0 12px',
                                             'border': '1px solid var(--border)', 'borderRadius': '6px'}),
        ]),
        dropdown_filter('crawl-canton', 'Kanton', canton_options, placeholder='Alle Kantone', width='140px'),
        dropdown_filter('crawl-type', 'Dokumenttyp', type_options, placeholder='Alle Typen', width='180px'),
        dropdown_filter('crawl-status', 'Status', status_options, placeholder='Alle Status', width='200px'),
        dropdown_filter('crawl-comparison', 'Vergleich', comparison_options, placeholder='Alle', width='240px'),
        reset_button('crawl-reset'),
    )


def _data_quality_notice():
    return html.Div([
        html.Div('Zur Datenqualität', className='data-quality-notice-title'),
        html.Ul([
            html.Li('Die Online-Suche ist Suchmaschinen-basiert und nicht verifiziert: das gefundene PDF kann zur '
                    'falschen Gemeinde gehören (z.B. Nachbargemeinde mit ähnlichem Namen), veraltet bzw. ein Entwurf '
                    'sein, oder nur ein Infoblatt statt des eigentlichen Reglements.'),
            html.Li('Der Datumsvergleich ("Online neuer" / "Lokal aktuell") beruht auf dem HTTP Last-Modified-Header '
                    'der Fundstelle - viele Gemeinde-Websites liefern diesen gar nicht oder leiten mehrfach um. '
                    '"Unbekannt" ist dabei der ehrliche Regelfall, keine seltene Ausnahme.'),
            html.Li('Alle Treffer sollten vor einer Übernahme ins Archiv manuell geprüft werden - diese Seite ist ein '
                    'Rechercheausgangspunkt, keine automatisch vertrauenswürdige Quelle.'),
        ]),
    ], className='data-quality-notice')


def _type_breakdown(df):
    """Zeigt, welche Dokumente die Erkennungsroutine (_detect_regulation_type) tatsächlich
    gefunden/erkannt hat - Gegenstück zum Dokumenttyp-Filter, der nur einzelne Typen isoliert."""
    found = df[df['status'] == 'ok']
    if found.empty:
        return None
    counts = (
        found['regulation_type'].value_counts()
        .rename_axis('Typ').reset_index(name='Anzahl').sort_values('Anzahl')
    )
    fig = bar(counts, x='Anzahl', y='Typ', labels={'Anzahl': '', 'Typ': ''})
    return section_card('Gefundene Dokumenttypen', dcc.Graph(figure=fig, config=CHART_CONFIG))


def layout():
    df = _load_results()
    subtitle = ('Status-Report und Recherche über die Funde des BZO-Crawlers (separates Offline-Skript, '
                'siehe scripts/bzo_crawler.py) - prüft pro Gemeinde, ob ein aktuelles Bau-/Zonenreglement '
                '(BZO) online gefunden werden kann.')
    if df is None or df.empty:
        rel_path = CSV_PATH.relative_to(Path(__file__).resolve().parent.parent)
        return page_shell('/update-reglement', 'Update Reglemente', subtitle, empty_state(
            f'Noch kein Crawler-Lauf vorhanden. scripts/bzo_crawler.py separat ausführen '
            f'(Ergebnis wird unter {rel_path} erwartet) und diese Seite danach neu laden.'
        ))

    # Pro Gemeinde kann es mehrere Zeilen geben (mehrere gefundene Dokumente) - "geprüft"/
    # "gefunden" daher auf eindeutige Gemeinden (bfs_nr) bezogen, alles andere (Downloads,
    # Vergleichs-Kategorien) bleibt auf Dokumentenebene, da das die tatsächlichen Einzelfunde sind.
    last_run = pd.Timestamp(os.path.getmtime(CSV_PATH), unit='s').strftime('%d.%m.%Y %H:%M')
    n_gemeinden = df['bfs_nr'].nunique()
    n_kantone = df['canton'].nunique()
    n_gemeinden_gefunden = df.loc[df['status'] == 'ok', 'bfs_nr'].nunique()
    n_docs_ok = int((df['status'] == 'ok').sum())
    n_not_found = int((df['status'] == 'not_found').sum())
    n_failed = int((df['status'] == 'download_failed').sum())
    n_newer = int((df['local_comparison'] == 'online_neuer').sum())
    n_new_found = int((df['local_comparison'] == 'neu_online_gefunden').sum())
    n_local_only = int((df['local_comparison'] == 'kein_online_treffer').sum())
    n_unknown = int((df['local_comparison'] == 'unbekannt').sum())
    avg_docs = n_docs_ok / n_gemeinden_gefunden if n_gemeinden_gefunden else 0

    kpis = html.Div([
        kpi('Zuletzt geprüft', last_run, accent='navy'),
        kpi('Gemeinden geprüft', f'{n_gemeinden:,}', accent='blue'),
        kpi('Kantone', f'{n_kantone}', accent='blue'),
        kpi('Gemeinden mit Treffer', f'{n_gemeinden_gefunden:,}',
            f'{n_gemeinden_gefunden / n_gemeinden:.0%}' if n_gemeinden else '', accent='green'),
        kpi('Dokumente gefunden', f'{n_docs_ok:,}', accent='teal'),
        kpi('Ø Dokumente/Gemeinde', f'{avg_docs:.1f}', 'bei Gemeinden mit Treffer', accent='teal'),
        kpi('Nicht gefunden', f'{n_not_found:,}', accent='orange'),
        kpi('Download fehlgeschlagen', f'{n_failed:,}', accent='red'),
        kpi('Online neuer als lokal', f'{n_newer:,}', 'zum Nachladen ins Archiv', accent='teal'),
        kpi('Neu online gefunden', f'{n_new_found:,}', 'lokal noch kein Reglement vorhanden', accent='navy'),
        kpi('Nur lokal vorhanden', f'{n_local_only:,}', 'online kein Treffer', accent='blue'),
        kpi('Aktualität unbekannt', f'{n_unknown:,}', 'kein Last-Modified-Header', accent='blue'),
    ], className='grid-6')

    return page_shell('/update-reglement', 'Update Reglemente', subtitle, [
        kpis,
        _type_breakdown(df),
        _data_quality_notice(),
        section_card('Ergebnisse je Gemeinde', [
            _filter_bar(df),
            html.Div(id='crawl-result-count', className='kpi-subtitle', style={'margin': '14px 0 10px 0'}),
            html.Div(id='crawl-table-wrap'),
        ]),
    ])


@callback(
    Output('crawl-table-wrap', 'children'), Output('crawl-result-count', 'children'),
    Input('crawl-search', 'value'), Input('crawl-canton', 'value'), Input('crawl-type', 'value'),
    Input('crawl-status', 'value'), Input('crawl-comparison', 'value'),
)
def update_table(search, canton, regulation_type, status, comparison):
    df = _load_results()
    if df is None or df.empty:
        return empty_state(), ''
    if search:
        term = re.escape(search.strip())
        mask = (
            df['name'].str.contains(term, case=False, na=False)
            | df['bfs_nr'].str.contains(term, case=False, na=False)
            | df['document_title'].str.contains(term, case=False, na=False)
        )
        df = df[mask]
    if canton:
        df = df[df['canton'] == canton]
    if regulation_type:
        df = df[df['regulation_type'] == regulation_type]
    if status:
        df = df[df['status'] == status]
    if comparison:
        df = df[df['local_comparison'] == comparison]
    if df.empty:
        return empty_state('Keine Gemeinden für diese Filterkombination.'), ''

    rows = []
    tooltip_data = []
    for rec in df.to_dict('records'):
        pdf_url = rec.get('pdf_url') or ''
        comparison_val = rec.get('local_comparison') or ''
        comparison_text = COMPARISON_LABELS.get(comparison_val, '–') if comparison_val else '–'
        rows.append({
            'name': rec.get('name'), 'canton': rec.get('canton'), 'bfs_nr': rec.get('bfs_nr'),
            'regulation_type': rec.get('regulation_type') or '–',
            'document_title': rec.get('document_title') or '–',
            'status_label': STATUS_LABELS.get(rec.get('status'), rec.get('status')),
            'local_present': 'Ja' if rec.get('local_reglement_path') else 'Nein',
            'comparison_label': comparison_text,
            'pdf_link': f'[Öffnen]({pdf_url})' if pdf_url else '–',
        })
        # Der Datumsvergleich kommt aus einem separaten HEAD-Request (Last-Modified-Header) -
        # unabhängig vom eigentlichen GET-Download. Bei fehlgeschlagenem Download wurde der
        # Inhalt also nie bestätigt, nur die Server-Kopfzeilen - das macht die Kombination
        # "Download fehlgeschlagen" + "Neuere Version vorhanden" auf den ersten Blick
        # widersprüchlich. Klärung per Mouseover-Tooltip statt Text in der Zelle selbst.
        if rec.get('status') == 'download_failed' and comparison_val in ('online_neuer', 'lokal_aktuell'):
            tooltip_data.append({'comparison_label': {
                'type': 'text',
                'value': 'Nur Header-Check (HTTP Last-Modified) - der Download ist fehlgeschlagen, '
                         'der Inhalt wurde nicht bestätigt.',
            }})
        else:
            tooltip_data.append({})
    # Zeilen mit neuerer Online-Version optisch hervorheben, statt nur als Text in der
    # Vergleich-Spalte - DataTable-Zellen können keine Badge-Komponenten rendern, daher
    # per style_data_conditional auf den (eindeutigen) Marker-Text gefiltert.
    style_data_conditional = [{
        'if': {'filter_query': f'{{comparison_label}} = "{NEWER_VERSION_LABEL}"'},
        'backgroundColor': 'rgba(237, 125, 49, 0.12)',
        'fontWeight': '600',
    }]
    count_text = f"{len(df):,} Dokumente ({df['bfs_nr'].nunique():,} Gemeinden)"
    return styled_table(rows, COLS, page_size=25, style_data_conditional=style_data_conditional,
                         tooltip_data=tooltip_data, tooltip_duration=None), count_text


@callback(
    Output('crawl-search', 'value'), Output('crawl-canton', 'value'), Output('crawl-type', 'value'),
    Output('crawl-status', 'value'), Output('crawl-comparison', 'value'),
    Input('crawl-reset', 'n_clicks'),
    prevent_initial_call=True,
)
def reset_filters(n_clicks):
    return None, None, None, None, None
