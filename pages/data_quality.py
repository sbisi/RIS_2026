import dash
from dash import html, dcc
from config.settings import STATUS_COLORS
from services.data import document_validation_status_counts, document_validation_issues, data_quality_summary, duplicate_projects_detail, quality_traffic
from components.page_header import page_shell
from components.cards import section_card, empty_state, kpi, status_badge, traffic_light
from components.tables import styled_table
from components.charts import bar, CHART_CONFIG

dash.register_page(__name__, path='/datenqualitaet', name='Datenqualität')

ISSUE_COLS = [
    {'name': 'Gemeinde', 'id': 'municipality_name'},
    {'name': 'BFS', 'id': 'BFS', 'type': 'numeric'},
    {'name': 'Ortsteil', 'id': 'municipality_part_name'},
    {'name': 'Status', 'id': 'validation_status'},
    {'name': 'Link vorhanden', 'id': 'linkdoc_present'},
    {'name': 'Link gültig', 'id': 'link_valid'},
    {'name': 'PDF gültig', 'id': 'downloaded_pdf_valid'},
    {'name': 'Metadaten gleich', 'id': 'metadata_equal'},
    {'name': 'Hash gleich', 'id': 'hash_equal'},
]


def layout():
    try:
        q = data_quality_summary()
        sc = document_validation_status_counts()
        issues = document_validation_issues(200)
        dup = duplicate_projects_detail(100)
        traffic = quality_traffic()

        kpis = html.Div([
            kpi('Reglemente geprüft', f"{int(q['total_documents']):,}", accent='navy'),
            kpi('Ohne Befund', f"{int(q['valid_documents']):,}", f"{q['valid_documents']/q['total_documents']:.0%}" if q['total_documents'] else '', accent='green'),
            kpi('Mit Fehlerstatus', f"{int(q['error_documents']):,}", 'Link/PDF/Gemeinde-Fehler', accent='red'),
            kpi('Von mehreren Gemeinden geteilt', f"{int(q['shared_documents']):,}", 'identisches Reglement', accent='teal'),
            kpi('Doppelte Projekt-IDs', f"{int(q['duplicate_projects']):,}", 'in fact_project', accent='orange'),
        ], className='grid-6')

        ampel = html.Div([
            html.Div([
                traffic_light(t['level'], t['label']),
                html.Div(f"{t['share']:.1%}" if t['share'] == t['share'] else '–', className='kpi-subtitle'),
                html.Div(t.get('note', ''), className='kpi-subtitle', style={'fontStyle': 'italic'}) if t.get('note') else None,
            ], style={'padding': '10px 0'})
            for t in traffic
        ], className='grid-6')

        fig = bar(sc, x='validation_status', y='n', orientation='v', color='validation_status', color_map=STATUS_COLORS,
                  labels={'validation_status': '', 'n': 'Anzahl Reglemente'})
        fig.update_layout(showlegend=False)

        legend = html.Div([status_badge(s) for s in sc['validation_status']], style={'display': 'flex', 'gap': '8px', 'marginBottom': '12px'})

        return page_shell('/datenqualitaet', 'Datenqualität', 'Validierungsstatus aller erfassten Gemeindereglemente (results_law_Manager) und strukturelle Datenqualität der Projektdaten.', [
            kpis,
            section_card('Ampelsystem – Reglementsprüfung', ampel),
            section_card('Validierungsstatus aller Reglemente', [legend, dcc.Graph(figure=fig, config=CHART_CONFIG)]),
            section_card(f'Auffällige Reglemente ({len(issues):,} von {int(q["total_documents"]):,})', styled_table(
                issues.to_dict('records'), ISSUE_COLS, page_size=20,
            ) if len(issues) else html.P('Keine auffälligen Reglemente.')),
            section_card('Projekte mit mehreren Zeilen (PROJID-Duplikate)', styled_table(
                dup.to_dict('records'), [{'name': c, 'id': c} for c in dup.columns], page_size=10,
            ) if len(dup) else html.P('Keine Duplikate gefunden.')),
        ])
    except Exception as e:
        return page_shell('/datenqualitaet', 'Datenqualität', '', empty_state(str(e)))
