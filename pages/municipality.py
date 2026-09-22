import dash
import pandas as pd
import plotly.express as px
from dash import html, dcc, Input, Output, callback
from services.data import (
    projects_for_bfs, municipality_options, municipality_summary, municipality_regulation_detail,
    municipality_yearly_volume, municipality_documents, municipality_benchmark,
    municipality_overview_radar,
    municipality_process_radar, municipality_reglement_radar, municipality_markt_radar,
    municipality_peer_benchmark, regulation_subcounts, REGULATION_DEFINITIONS,
    municipality_score_breakdown,
)
from components.page_header import page_shell
from components.cards import kpi, section_card, empty_state, meta_pill, status_badge
from components.tables import styled_table
from components.charts import bar, line, radar, CHART_CONFIG, with_definition_hover

dash.register_page(__name__, path='/gemeinde', name='Analyse Gemeinden')


def layout(bfs=None, **kwargs):
    # bfs kommt als URL-Query-Param (?bfs=...) für Deep-Links von anderen Seiten (z.B. Parzellen).
    try:
        opts = municipality_options()
        options = [{'label': r.municipality_name, 'value': int(r.BFS)} for r in opts.itertuples()]
        default = int(bfs) if bfs else (options[0]['value'] if options else None)
        return page_shell('/gemeinde', 'Analyse Gemeinden', 'Detailanalyse einer einzelnen Gemeinde: Ranking, Regulierung, Prozess und Benchmark.', [
            section_card('Gemeinde wählen', html.Div([
                dcc.Dropdown(id='bfs-select', options=options, value=default, placeholder='Gemeinde wählen', style={'maxWidth': '420px', 'flex': 1}),
                html.Div(id='bfs-number-box', style={'minWidth': '160px'}),
            ], style={'display': 'flex', 'gap': '16px', 'alignItems': 'center'})),
            html.Div(id='municipality-content'),
        ])
    except Exception as e:
        return page_shell('/gemeinde', 'Analyse Gemeinden', '', empty_state(str(e)))


@callback(Output('bfs-number-box', 'children'), Input('bfs-select', 'value'))
def update_bfs_number(bfs):
    if not bfs:
        return None
    # Bewusst kein kpi()-Kasten (zu gross/fett) - schlichte Box in derselben Schriftgrösse/Font
    # wie das Gemeinde-Dropdown daneben, nur mit Rahmen zur optischen Abgrenzung.
    return html.Div([
        html.Span('BFS-Nummer: ', style={'color': 'var(--text-muted)'}),
        html.Span(str(int(bfs))),
    ], style={
        'height': '38px', 'display': 'flex', 'alignItems': 'center', 'padding': '0 14px',
        'border': '1px solid var(--border)', 'borderRadius': '6px', 'background': 'var(--surface)',
    })


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
    overview_radar_df = municipality_overview_radar(bfs)
    process_radar_df = municipality_process_radar(bfs)
    reglement_radar_df = municipality_reglement_radar(bfs)
    markt_radar_df = municipality_markt_radar(bfs)
    peer_bench, peer_group = municipality_peer_benchmark(bfs)
    score_breakdown = municipality_score_breakdown(bfs)

    header = section_card(None, html.Div([
        meta_pill('Gemeinde', s.municipality_name),
        meta_pill('Kanton', s.Kanton or '–'),
        meta_pill('Peergruppe', s.peer_group or '–'),
        meta_pill('Ranking', f"{s.peer_rank:.0f} / {s.peer_group_size:.0f}" if s.peer_rank == s.peer_rank and s.peer_group_size == s.peer_group_size else '–'),
    ], className='meta-pill-row'))

    score_values = [s.overall_score, s.process_score, s.regulation_score, s.market_score]
    has_scores = any(v == v for v in score_values)  # v==v ist False fuer NaN

    def score_fmt(v):
        return f'{v:.1f}' if v == v else '–'

    scores = section_card('Scores', html.Div([
        kpi('Gesamt-Score', score_fmt(s.overall_score), accent='navy'),
        kpi('Prozess-Score', score_fmt(s.process_score), accent='blue'),
        kpi('Reglement-Score', score_fmt(s.regulation_score), accent='teal'),
        kpi('Markt-Score', score_fmt(s.market_score), accent='orange'),
    ], className='grid-4') if has_scores else html.P('Zu wenig Projektdaten für ein Scoring (nicht gerankt).', className='kpi-subtitle'))

    score_panel = _score_panel(score_breakdown, overview_radar_df, process_radar_df, reglement_radar_df, markt_radar_df)
    reglement_panel = _reglement_panel(reg, bfs)
    prozess_panel = _prozess_panel(df)
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
        score_panel,
        html.Div([reglement_panel, prozess_panel], className='grid-2'),
        html.Div([historie, dokumente, benchmark], className='grid-3'),
        peer_benchmark_panel,
    ], className='page-body', style={'marginTop': '28px'})


def _radar_or_empty(df, title):
    if df.empty:
        return html.P(f'{title}: keine Peer-Gruppe zugeordnet.', className='kpi-subtitle')
    # NaN-Werte (z.B. Gemeinde nicht gerankt) rausfiltern statt die Achse zu unterbrechen - der
    # Chart zeigt dann weiterhin die vorhandene(n) Serie(n) (i.d.R. Peer-Durchschnitt). Ohne
    # Flaechenfuellung (siehe radar()) sieht eine Peer-only-Linie nicht wie ein eigenes Scoring
    # der Gemeinde aus.
    plot_df = df.dropna(subset=['Wert'])
    if plot_df.empty:
        return html.P(f'{title}: keine Peer-Vergleichsdaten verfügbar.', className='kpi-subtitle')
    # responsive=False + feste style-Höhe (identisch zur figure.layout.height=315 aus radar()):
    # ohne das versucht dcc.Graph, sich an seinen Container anzupassen - in den verschachtelten
    # CSS-Grids hier (aeusseres grid-2/grid-3, kein Elternelement mit fixer Hoehe) fuehrt das zu
    # einem Rueckkopplungs-Loop, bei dem sich Chart und Container gegenseitig aufschaukeln
    # ("rutscht herum") - siehe dieselbe Ursache/Fix bei den Verdichtung/Wohnen-Mini-Charts.
    return dcc.Graph(figure=radar(plot_df, r='Wert', theta='Achse', color='Serie'), config=CHART_CONFIG,
                      responsive=False, style={'height': '315px', 'width': '100%'})


def _score_panel(breakdown, overview_df, process_df, reglement_df, markt_df):
    if not breakdown:
        return None

    def fmt(v):
        return f'{v:.2f}' if v is not None and v == v else '–'

    compare_rows = [
        {'Score': 'Gesamt-Score', 'Original': fmt(breakdown['gesamt']['original']), 'Berechnet': fmt(breakdown['gesamt']['berechnet'])},
        {'Score': 'Prozess-Score', 'Original': fmt(breakdown['prozess']['original']), 'Berechnet': fmt(breakdown['prozess']['berechnet'])},
        {'Score': 'Reglement-Score', 'Original': fmt(breakdown['reglement']['original']), 'Berechnet': fmt(breakdown['reglement']['berechnet'])},
        {'Score': 'Markt-Score', 'Original': fmt(breakdown['markt']['original']), 'Berechnet': fmt(breakdown['markt']['berechnet'])},
    ]
    compare_cols = [{'name': c, 'id': c} for c in ['Score', 'Original', 'Berechnet']]

    def detail_table(detail):
        rows = [{
            'Komponente': d['Komponente'], 'Gewicht': f"{d['Gewicht']:.1%}",
            'Wert': fmt(d['Wert']), 'Beitrag': fmt(d['Beitrag']),
        } for d in detail]
        cols = [{'name': c, 'id': c} for c in ['Komponente', 'Gewicht', 'Wert', 'Beitrag']]
        return styled_table(rows, cols, page_size=10, sort=False, filter_=False)

    def component_column(title, detail, radar_df):
        # feste Mindesthöhe für den Tabellenbereich: Prozess hat 6 Komponenten-Zeilen, Reglement
        # 4, Markt 3 - ohne das würden die Radars je nach Zeilenzahl auf unterschiedlicher Höhe
        # beginnen statt in den 3 Spalten horizontal auf gleicher Höhe zu stehen.
        # minWidth: 0 verhindert, dass die Spalte über die 1fr-Breite aus .grid-3 hinauswächst -
        # ohne das können Kindelemente (Tabelle/Chart) eine CSS-Grid-Spalte an ihre eigene
        # Minimalbreite drücken statt auf den zugeteilten Platz zu schrumpfen.
        return html.Div([
            html.H4(title, style={'fontSize': '0.9rem', 'marginBottom': '8px', 'color': 'var(--navy)'}),
            html.Div(detail_table(detail), style={'minHeight': '270px'}),
            _radar_or_empty(radar_df, title),
        ], style={'minWidth': 0})

    return section_card('Score-Berechnung & Vergleich', html.Div([
        html.P(
            'Vergleich des im Ranking-Sheet hinterlegten Werts (Original) mit der Nachrechnung aus den '
            'gewichteten Einzelkomponenten (0-100-Skala je Komponente) - "Wert" ist der Komponentenscore, '
            '"Beitrag" = Wert × Gewicht. Die Radar-Charts zeigen dieselben Komponenten im Peer-Vergleich.',
            className='kpi-subtitle', style={'marginBottom': '18px'},
        ),
        # Gesamt-Score: Vergleichstabelle direkt neben dem zugehörigen Radar.
        html.Div([
            html.Div([
                html.H4('Gesamt-Score: Original vs. Berechnet', style={'fontSize': '0.9rem', 'marginBottom': '8px', 'color': 'var(--navy)'}),
                styled_table(compare_rows, compare_cols, page_size=4, sort=False, filter_=False),
            ]),
            html.Div([
                html.H4('Gesamt-Score im Vergleich (Peer)', style={'fontSize': '0.9rem', 'marginBottom': '8px', 'color': 'var(--navy)'}),
                _radar_or_empty(overview_df, 'Gesamt-Score'),
            ]),
        ], className='grid-2', style={'marginBottom': '24px'}),
        # Prozess/Reglement/Markt: je Komponenten-Tabelle direkt über dem zugehörigen Radar.
        html.Div([
            component_column('Prozess-Score', breakdown['prozess']['detail'], process_df),
            component_column('Reglement-Score', breakdown['reglement']['detail'], reglement_df),
            component_column('Markt-Score', breakdown['markt']['detail'], markt_df),
        ], className='grid-3'),
    ]))


def _reglement_panel(reg, bfs):
    if reg.empty or reg.iloc[0].complexity_index_raw != reg.iloc[0].complexity_index_raw:
        body = html.P('Kein Reglement erfasst.')
    else:
        r = reg.iloc[0]
        chart_df = _counts_df(r)

        detail_block = None
        if (r.densification_count or 0) > 0 or (r.housing_count or 0) > 0:
            sub = regulation_subcounts(bfs)
            verdichtung = sub[sub['Oberbereich'] == 'Verdichtung']
            wohnen = sub[sub['Oberbereich'] == 'Wohnen']
            detail_block = html.Div([
                html.Div([
                    html.H4('Verdichtung im Detail', style={'fontSize': '0.85rem', 'marginBottom': '6px', 'color': 'var(--navy)'}),
                    dcc.Graph(figure=with_definition_hover(bar(verdichtung, x='n', y='Sub-Kategorie', labels={'n': '', 'Sub-Kategorie': ''}, hover_data=['Definition'], height=190)),
                              config=CHART_CONFIG, responsive=False, style={'height': '190px'}),
                ]),
                html.Div([
                    html.H4('Wohnen im Detail', style={'fontSize': '0.85rem', 'marginBottom': '6px', 'color': 'var(--navy)'}),
                    dcc.Graph(figure=with_definition_hover(bar(wohnen, x='n', y='Sub-Kategorie', labels={'n': '', 'Sub-Kategorie': ''}, hover_data=['Definition'], height=190)),
                              config=CHART_CONFIG, responsive=False, style={'height': '190px'}),
                ]),
            ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '18px', 'marginTop': '20px'})

        body = html.Div([
            html.Div([
                kpi('Komplexitätsindex', f"{r.complexity_index_raw:.2f}" if r.complexity_index_raw == r.complexity_index_raw else '–', accent='teal'),
                kpi('Reglementsalter', f"{r.document_age:.0f} Jahre" if r.document_age == r.document_age else '–', accent='blue'),
                status_badge(r.validation_status) if isinstance(r.validation_status, str) else html.Span('–'),
            ], style={'display': 'flex', 'gap': '16px', 'alignItems': 'center', 'marginBottom': '16px', 'flexWrap': 'wrap'}),
            dcc.Graph(figure=with_definition_hover(bar(chart_df, x='n', y='Kategorie', hover_data=['Definition'])), config=CHART_CONFIG),
            detail_block,
            dcc.Link('Analyse Reglemente ansehen →', href=f'/regulierung?bfs={int(bfs)}',
                     className='btn-secondary', style={'display': 'inline-block', 'marginTop': '18px'}),
        ])
    return section_card('Reglement', body)


def _counts_df(r):
    return pd.DataFrame([
        {'Kategorie': 'Intervention', 'n': r.intervention_count or 0, 'Definition': REGULATION_DEFINITIONS['Intervention']},
        {'Kategorie': 'Architektur', 'n': r.architecture_count or 0, 'Definition': REGULATION_DEFINITIONS['Architektur']},
        {'Kategorie': 'Wohnen', 'n': r.housing_count or 0, 'Definition': REGULATION_DEFINITIONS['Wohnen']},
        {'Kategorie': 'Verdichtung', 'n': r.densification_count or 0, 'Definition': REGULATION_DEFINITIONS['Verdichtung']},
    ])


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
