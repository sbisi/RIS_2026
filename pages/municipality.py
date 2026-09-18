import dash
import pandas as pd
import plotly.express as px
from dash import html, dcc, Input, Output, callback
from services.data import (
    projects_for_bfs, municipality_options, municipality_summary, municipality_regulation_detail,
    municipality_yearly_volume, municipality_documents, municipality_benchmark,
    municipality_diagnosis, municipality_dimension_ranks, municipality_overview_radar,
    municipality_process_radar, municipality_peer_benchmark,
)
from components.page_header import page_shell
from components.cards import kpi, section_card, empty_state, meta_pill, score_bar, status_badge
from components.tables import styled_table
from components.charts import bar, line, radar, CHART_CONFIG
from config.settings import COLORS

RATING_COLORS = {
    'sehr gut': COLORS['green'], 'gut': COLORS['teal'], 'mittel': COLORS['orange'],
    'schlecht': COLORS['red'], 'sehr schlecht': COLORS['red'], 'Nicht gerankt': COLORS['gray'],
}
PRIORITY_COLORS = {
    'A - Sofort ansprechen': COLORS['red'], 'B - Priorisiert ansprechen': COLORS['orange'],
    'C - Marktrelevant': COLORS['teal'], 'D - Beobachten': COLORS['blue'],
    'Keine Priorität': COLORS['gray'], 'Nicht gerankt': COLORS['gray'],
}

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
    diag = municipality_diagnosis(bfs)
    dim_ranks = municipality_dimension_ranks(bfs)
    overview_radar_df = municipality_overview_radar(bfs)
    process_radar_df = municipality_process_radar(bfs)
    peer_bench, peer_group = municipality_peer_benchmark(bfs)

    header = section_card(None, html.Div([
        meta_pill('Gemeinde', s.municipality_name),
        meta_pill('Kanton', s.Kanton or '–'),
        meta_pill('Peergruppe', s.peer_group or '–'),
        meta_pill('Ranking', f"{s.peer_rank:.0f} / {s.peer_group_size:.0f}" if s.peer_rank == s.peer_rank and s.peer_group_size == s.peer_group_size else '–'),
    ], className='meta-pill-row'))

    score_values = [s.overall_score, s.process_score, s.regulation_score, s.market_score]
    has_scores = any(v == v for v in score_values)  # v==v ist False fuer NaN
    scores = section_card('Scores', html.Div([
        score_bar('Gesamt-Score', s.overall_score, accent='navy'),
        score_bar('Prozess', s.process_score, accent='blue'),
        score_bar('Regulierung', s.regulation_score, accent='teal'),
        score_bar('Markt', s.market_score, accent='orange'),
    ]) if has_scores else html.P('Zu wenig Projektdaten für ein Scoring (nicht gerankt).', className='kpi-subtitle'))

    reglement_panel = _reglement_panel(reg)
    prozess_panel = _prozess_panel(df)
    diagnosis_panel = _diagnosis_panel(diag, dim_ranks)
    score_radar_panel = _score_radar_panel(overview_radar_df, process_radar_df)
    peer_benchmark_panel = _peer_benchmark_panel(peer_bench, peer_group)

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
        html.Div([diagnosis_panel, score_radar_panel], className='grid-2'),
        html.Div([reglement_panel, prozess_panel], className='grid-2'),
        html.Div([historie, dokumente, benchmark], className='grid-3'),
        peer_benchmark_panel,
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


def _diagnosis_panel(diag, dim_ranks):
    if diag.empty:
        return section_card('Einordnung & Priorität', html.P('Keine Ranking-Daten verfügbar.'))
    d = diag.iloc[0]
    is_ranked = d.rating_eligibility == 'OK'
    body = [
        html.Div([
            html.Span('Bewilligungsprozess', className='meta-pill-label'),
            html.Div(status_badge(d.rating_prozess, RATING_COLORS.get(d.rating_prozess)), style={'marginTop': '4px'}),
        ], style={'marginBottom': '14px'}),
        html.Div([
            html.Span('Priorität', className='meta-pill-label'),
            html.Div(status_badge(d.prioritaet_partner, PRIORITY_COLORS.get(d.prioritaet_partner)), style={'marginTop': '4px'}),
        ], style={'marginBottom': '14px'}),
    ]
    if isinstance(d.diagnose, str):
        body.append(html.Div([
            html.Span('Mögliche Treiber', className='meta-pill-label'),
            html.Div(d.diagnose, style={'marginTop': '4px', 'fontWeight': 600, 'color': COLORS['navy']}),
        ], style={'marginBottom': '14px'}))
    if is_ranked and not dim_ranks.empty:
        rank_rows = [{
            'Dimension': r.Dimension,
            'Score': f'{r.Score:.1f}' if r.Score == r.Score else '–',
            'Peer_Rang': f'{r.Peer_Rang:.0f} / {r.Peer_Groesse:.0f}' if r.Peer_Rang == r.Peer_Rang else '–',
            'Nat_Perzentil': f'{r.Nat_Perzentil:.0f} %' if r.Nat_Perzentil == r.Nat_Perzentil else '–',
        } for r in dim_ranks.itertuples()]
        rank_cols = [
            {'name': 'Dimension', 'id': 'Dimension'}, {'name': 'Score (0-100)', 'id': 'Score'},
            {'name': 'Peer-Rang', 'id': 'Peer_Rang'}, {'name': 'Nat. Perzentil', 'id': 'Nat_Perzentil'},
        ]
        body.append(styled_table(rank_rows, rank_cols, page_size=4, sort=False, filter_=False))
    else:
        body.append(html.P('Zu wenig Projektdaten für ein Ranking (nicht gerankt).', className='kpi-subtitle'))
    return section_card('Einordnung & Priorität', html.Div(body))


def _score_radar_panel(overview_df, process_df):
    def graph_or_empty(df, title):
        if df.empty:
            return html.P(f'{title}: keine Peer-Gruppe zugeordnet.', className='kpi-subtitle')
        # NaN-Werte (z.B. Gemeinde nicht gerankt) rausfiltern statt die Achse zu unterbrechen -
        # der Chart zeigt dann weiterhin die vorhandene(n) Serie(n) (i.d.R. Peer-Durchschnitt).
        # Ohne Flaechenfuellung (siehe radar()) sieht eine Peer-only-Linie nicht wie ein eigenes
        # Scoring der Gemeinde aus.
        plot_df = df.dropna(subset=['Wert'])
        if plot_df.empty:
            return html.P(f'{title}: keine Peer-Vergleichsdaten verfügbar.', className='kpi-subtitle')
        return html.Div([
            html.H4(title, className='section-title', style={'fontSize': '0.9rem', 'marginBottom': '4px'}),
            dcc.Graph(figure=radar(plot_df, r='Wert', theta='Achse', color='Serie'), config=CHART_CONFIG),
        ])

    return section_card('Scores im Vergleich', html.Div([
        graph_or_empty(overview_df, 'Gesamtbewertung'),
        graph_or_empty(process_df, 'Prozessbewertung'),
    ]))


def _format_metric(value, unit):
    if value is None or value != value:
        return '–'
    if unit == '%':
        return f'{value * 100:.1f} %'
    if unit == 'Tage':
        return f'{value:.0f} Tage'
    return f'{value:.1f}' if value != round(value) else f'{value:.0f}'


def _peer_benchmark_panel(peer_bench, peer_group):
    if peer_bench is None or peer_bench.empty:
        return section_card('Peer-Vergleich', html.P('Keine Peer-Gruppe zugeordnet.'))
    rows = [{
        'Bereich': r.Bereich, 'Dimension': r.Dimension,
        'Gemeinde': _format_metric(r.Gemeinde, r.Einheit),
        'Peer_Oe': _format_metric(r.Peer_Oe, r.Einheit),
        'Nat_Oe': _format_metric(r.Nat_Oe, r.Einheit),
    } for r in peer_bench.itertuples()]
    cols = [
        {'name': 'Bereich', 'id': 'Bereich'}, {'name': 'Dimension', 'id': 'Dimension'},
        {'name': 'Gemeinde', 'id': 'Gemeinde'}, {'name': f'Peer-Ø ({peer_group})', 'id': 'Peer_Oe'},
        {'name': 'Nat.-Ø', 'id': 'Nat_Oe'},
    ]
    return section_card('Peer-Vergleich', styled_table(rows, cols, page_size=15, sort=False, filter_=False))


def _prozess_panel(df):
    durations = df['processing_days'].dropna()
    body = [html.P('Keine Bearbeitungsdauern verfügbar.', className='kpi-subtitle')]
    if len(durations):
        # Ein paar Ausreisser strecken sonst die Achse so weit, dass der eigentlich relevante
        # Bereich (die meisten Verfahren) auf einen schmalen Streifen zusammengequetscht wird -
        # Achse auf das 95. Perzentil deckeln statt Log-Skala (fuer Sachbearbeiter intuitiver
        # lesbar) und die ausgeblendeten Ausreisser transparent als Fussnote ausweisen.
        p95 = durations.quantile(0.95)
        n_outliers = int((durations > p95).sum())
        caption = (f'{n_outliers} Ausreisser über {p95:.0f} Tage ausgeblendet (Achse auf 95. Perzentil begrenzt).'
                   if n_outliers else None)

        fig1 = px.histogram(df, x='processing_days', labels={'processing_days': 'Bearbeitungsdauer (Tage)'})
        fig1.update_yaxes(title='Anzahl Projekte')
        if n_outliers:
            fig1.update_xaxes(range=[0, p95])

        medians = df.groupby('devtype_text')['processing_days'].median().sort_values()
        fig2 = px.box(
            df, x='devtype_text', y='processing_days', category_orders={'devtype_text': medians.index.tolist()},
            labels={'devtype_text': '', 'processing_days': 'Bearbeitungsdauer (Tage)'},
        )
        if n_outliers:
            fig2.update_yaxes(range=[0, p95])

        body = [
            dcc.Graph(figure=fig1, config=CHART_CONFIG),
            html.P(caption, className='kpi-subtitle') if caption else None,
            dcc.Graph(figure=fig2, config=CHART_CONFIG),
        ]
    return section_card('Prozessanalyse', html.Div(body))
