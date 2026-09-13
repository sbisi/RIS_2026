import dash
import pandas as pd
import plotly.express as px
from dash import html, dcc, Input, Output, callback
from services.data import (
    projects_for_bfs, municipality_options, municipality_summary, municipality_regulation_detail,
    municipality_yearly_volume, municipality_documents, municipality_benchmark,
)
from components.page_header import page_shell
from components.cards import kpi, section_card, empty_state, meta_pill, score_bar, status_badge
from components.tables import styled_table
from components.charts import bar, line, CHART_CONFIG

dash.register_page(__name__, path='/gemeinde', name='Gemeindeprofil')


def layout(bfs=None, **kwargs):
    # bfs kommt als URL-Query-Param (?bfs=...) für Deep-Links von anderen Seiten (z.B. Parzellen).
    try:
        opts = municipality_options()
        options = [{'label': f"{r.municipality_name} ({int(r.BFS)})", 'value': int(r.BFS)} for r in opts.itertuples()]
        default = int(bfs) if bfs else (options[0]['value'] if options else None)
        return page_shell('/gemeinde', 'Gemeindeprofil', 'Detailanalyse einer einzelnen Gemeinde: Ranking, Regulierung, Prozess und Benchmark.', [
            section_card('Gemeinde wählen', dcc.Dropdown(id='bfs-select', options=options, value=default, placeholder='Gemeinde wählen', style={'maxWidth': '420px'})),
            html.Div(id='municipality-content'),
        ])
    except Exception as e:
        return page_shell('/gemeinde', 'Gemeindeprofil', '', empty_state(str(e)))


@callback(Output('municipality-content', 'children'), Input('bfs-select', 'value'))
def update(bfs):
    if bfs is None:
        return empty_state('Bitte Gemeinde wählen.')
    summary = municipality_summary(bfs)
    if summary.empty:
        return empty_state()
    s = summary.iloc[0]
    df = projects_for_bfs(bfs)
    reg = municipality_regulation_detail(bfs)
    yearly = municipality_yearly_volume(bfs)
    docs = municipality_documents(bfs)
    bench = municipality_benchmark(bfs)

    header = section_card(None, html.Div([
        meta_pill('Gemeinde', s.municipality_name),
        meta_pill('Kanton', s.Kanton or '–'),
        meta_pill('Peergruppe', s.peer_group or '–'),
        meta_pill('Ranking', f"{s.peer_rank:.0f} / {s.peer_group_size:.0f}" if s.peer_rank == s.peer_rank and s.peer_group_size == s.peer_group_size else '–'),
    ], className='meta-pill-row'))

    scores = section_card('Scores', html.Div([
        score_bar('Gesamt-Score', s.overall_score, accent='navy'),
        score_bar('Prozess', s.process_score, accent='blue'),
        score_bar('Regulierung', s.regulation_score, accent='teal'),
        score_bar('Markt', s.market_score, accent='orange'),
    ]))

    reglement_panel = _reglement_panel(reg)
    prozess_panel = _prozess_panel(df)

    historie = section_card('Historie – Projekte pro Jahr', dcc.Graph(
        figure=line(yearly, x='Jahr', y='Projekte'), config=CHART_CONFIG,
    ) if len(yearly) else html.P('Keine Zeitreihe verfügbar.'))

    doc_cols = [
        {'name': 'Ortsteil', 'id': 'Ortsteil'}, {'name': 'URL', 'id': 'canonical_url'},
        {'name': 'Version', 'id': 'source_version'}, {'name': 'Status', 'id': 'validation_status'},
    ]
    dokumente = section_card('Dokumente', styled_table(docs.to_dict('records'), doc_cols, page_size=10) if len(docs) else html.P('Kein Reglement erfasst.'))

    bench_cols = [{'name': 'Ebene', 'id': 'Ebene'}, {'name': 'Gesamt-Score', 'id': 'Gesamt_Score', 'type': 'numeric', 'format': {'specifier': '.1f'}},
                  {'name': 'Median Dauer (Tage)', 'id': 'Median_Dauer', 'type': 'numeric', 'format': {'specifier': '.0f'}}]
    benchmark = section_card('Benchmark', styled_table(bench.to_dict('records'), bench_cols, page_size=5, sort=False, filter_=False))

    return html.Div([
        header,
        scores,
        html.Div([reglement_panel, prozess_panel], className='grid-2'),
        html.Div([historie, dokumente, benchmark], className='grid-3'),
    ], className='page-body', style={'marginTop': '28px'})


def _reglement_panel(reg):
    if reg.empty or reg.iloc[0].complexity_index_raw != reg.iloc[0].complexity_index_raw:
        body = html.P('Kein Reglement erfasst.')
    else:
        r = reg.iloc[0]
        chart_df = _counts_df(r)
        body = html.Div([
            html.Div([
                kpi('Komplexitätsindex', f"{r.complexity_index_raw:.2f}" if r.complexity_index_raw == r.complexity_index_raw else '–', accent='teal'),
                kpi('Reglementsalter', f"{r.document_age:.0f} Jahre" if r.document_age == r.document_age else '–', accent='blue'),
                status_badge(r.validation_status) if isinstance(r.validation_status, str) else html.Span('–'),
            ], style={'display': 'flex', 'gap': '16px', 'alignItems': 'center', 'marginBottom': '16px', 'flexWrap': 'wrap'}),
            dcc.Graph(figure=bar(chart_df, x='n', y='Kategorie'), config=CHART_CONFIG),
        ])
    return section_card('Reglementanalyse', body)


def _counts_df(r):
    return pd.DataFrame([
        {'Kategorie': 'Intervention', 'n': r.intervention_count or 0},
        {'Kategorie': 'Architektur', 'n': r.architecture_count or 0},
        {'Kategorie': 'Wohnen', 'n': r.housing_count or 0},
        {'Kategorie': 'Verdichtung', 'n': r.densification_count or 0},
    ])


def _prozess_panel(df):
    fig1 = px.histogram(df, x='processing_days', labels={'processing_days': 'Bearbeitungsdauer (Tage)'})
    fig2 = px.box(df, x='devtype_text', y='processing_days', labels={'devtype_text': '', 'processing_days': 'Bearbeitungsdauer (Tage)'})
    return section_card('Prozessanalyse', html.Div([
        dcc.Graph(figure=fig1, config=CHART_CONFIG),
        dcc.Graph(figure=fig2, config=CHART_CONFIG),
    ]))
