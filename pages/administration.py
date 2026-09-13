import dash
from dash import html
from services.data import etl_status, model_table_counts
from components.page_header import page_shell
from components.cards import section_card, empty_state, kpi
from components.tables import styled_table

dash.register_page(__name__, path='/administration', name='Administration')

AUDIT_FILES = [
    'audit/duplicate_register.csv', 'audit/law_document_issues.csv',
    'audit/municipality_mapping_issues.csv', 'audit/document_version_conflicts.csv',
    'audit/data_quality_report.xlsx',
]


def layout():
    try:
        status = etl_status()
        counts = model_table_counts()

        kpis = html.Div([
            kpi('Letzter ETL-Lauf', status['run_at'].strftime('%d.%m.%Y %H:%M') if status else '–', accent='navy'),
            kpi('Rohdatenverzeichnis', status['raw_dir'] if status else '–', accent='blue'),
            kpi('Tabellen im Datenmodell', f"{len(counts):,}", accent='teal'),
        ], className='grid-3')

        cols = [{'name': c, 'id': c} for c in counts.columns]

        return page_shell('/administration', 'Administration', 'Pipeline-Status, Datenmodell-Übersicht und Audit-Berichte.', [
            kpis,
            section_card('Tabellenübersicht (data/duckdb/hslu_ris.duckdb)', styled_table(counts.to_dict('records'), cols, page_size=20, sort=True, filter_=False)),
            section_card('Audit-Berichte', html.Ul([html.Li(f) for f in AUDIT_FILES], style={'fontFamily': 'monospace', 'fontSize': '0.85rem'})),
            section_card('Reproduzierbarkeit', html.P(
                'Alle Tabellen werden reproduzierbar aus data/raw erzeugt: python -m etl.build_clean_model. '
                'Rohdaten werden dabei nie verändert, überschrieben oder gelöscht.',
                style={'fontSize': '0.9rem', 'color': 'var(--text-muted)'},
            )),
        ])
    except Exception as e:
        return page_shell('/administration', 'Administration', '', empty_state(str(e)))
