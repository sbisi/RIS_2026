import math

import dash
import pandas as pd
import plotly.express as px
from dash import html, dcc, Input, Output, State, callback
from services.data import (
    projects_for_bfs, municipality_options, municipality_summary, municipality_regulation_detail,
    municipality_yearly_volume, municipality_documents, municipality_benchmark,
    municipality_overview_radar,
    municipality_process_radar, municipality_reglement_radar, municipality_markt_radar,
    municipality_peer_benchmark, regulation_subcounts, REGULATION_DEFINITIONS,
    municipality_score_breakdown, ausnuetzungsziffer_coverage_map, zone_parameters_for_municipality,
    municipality_coordinates, municipality_population, municipality_average_ausnuetzungsziffer,
)
from services.geo import get_zones_for_municipality, HAUPTNUTZUNG_GROUPS, HAUPTNUTZUNG_ORDER
from services.are_stats import get_bauzonenreserven
from services.parcel_ranking import get_parcel_potential_ranking, FETCH_CAP
from components.page_header import page_shell
from components.cards import kpi, section_card, empty_state, meta_pill, status_badge
from components.tables import styled_table
from components.charts import bar, line, radar, CHART_CONFIG, with_definition_hover
from config.settings import COLORS

dash.register_page(__name__, path='/gemeinde', name='Analyse Gemeinden')


def layout(bfs=None, **kwargs):
    # bfs kommt als URL-Query-Param (?bfs=...) für Deep-Links von anderen Seiten (z.B. Parzellen).
    try:
        opts = municipality_options()
        options = [{'label': r.municipality_name, 'value': int(r.BFS)} for r in opts.itertuples()]
        default = int(bfs) if bfs else (options[0]['value'] if options else None)

        cov = ausnuetzungsziffer_coverage_map()
        n_covered = int((cov['Abdeckung'] == 'Erfasst').sum())
        fig_cov_map = px.scatter_map(
            cov, lat='Latitude', lon='Longitude', color='Abdeckung', hover_name='municipality_name',
            hover_data={'Kanton': True, 'Latitude': False, 'Longitude': False},
            color_discrete_map={'Erfasst': COLORS['teal'], 'Nicht erfasst': COLORS['gray']},
            category_orders={'Abdeckung': ['Erfasst', 'Nicht erfasst']},
            zoom=6.4, center={'lat': 46.8, 'lon': 8.2}, map_style='carto-positron', height=480,
        )
        fig_cov_map.update_layout(margin=dict(l=0, r=0, t=0, b=0), legend=dict(orientation='h', y=-0.05))

        return page_shell('/gemeinde', 'Analyse Gemeinden', 'Detailanalyse einer einzelnen Gemeinde: Ranking, Regulierung, Prozess und Benchmark.', [
            section_card('Gemeinde wählen', html.Div([
                dcc.Dropdown(id='bfs-select', options=options, value=default, placeholder='Gemeinde wählen', style={'maxWidth': '420px', 'flex': 1}),
                html.Div(id='bfs-number-box', style={'minWidth': '160px'}),
            ], style={'display': 'flex', 'gap': '16px', 'alignItems': 'center'})),
            html.Div(id='municipality-content'),
            html.Div(section_card('Abdeckung Ausnützungsziffer (Standard)', html.Div([
                html.P(f'{n_covered:,} von {len(cov):,} Gemeinden ({n_covered / len(cov):.0%}) haben mindestens eine Zone mit '
                       'erfasster Ausnützungsziffer (Standard) in dim_zone_parameter - Voraussetzung dafür, dass sich '
                       '"Ausbaupotenzial" auf Analyse Parzellen für eine dortige Parzelle berechnen lässt.',
                       className='kpi-subtitle', style={'marginBottom': '10px'}),
                dcc.Graph(figure=fig_cov_map, config=CHART_CONFIG),
            ])), style={'marginTop': '20px'}),
            html.Div(_potenzial_ranking_shell(), style={'marginTop': '20px'}),
        ])
    except Exception as e:
        return page_shell('/gemeinde', 'Analyse Gemeinden', '', empty_state(str(e)))


RANKING_TOP_N = 20
METRIC_OPTIONS = [
    {'label': 'Absolut (ha)', 'value': 'absolut'},
    {'label': 'Pro 1\'000 Einwohner', 'value': 'pro_kopf'},
    {'label': 'Ausbaupotenzial (BGF, geschätzt)', 'value': 'ausbaupotenzial'},
]
RANKING_BASE_COLS = [
    {'name': 'Gemeinde', 'id': 'Gemeinde_Link', 'presentation': 'markdown'},
    {'name': 'Kanton', 'id': 'Kanton'},
    {'name': 'Unüberbaut (ha)', 'id': 'Unueberbaut_ha', 'type': 'numeric', 'format': {'specifier': ',.1f'}},
]
RANKING_PRO_KOPF_COL = {'name': 'ha pro 1\'000 Einwohner', 'id': 'Metric_display', 'type': 'numeric', 'format': {'specifier': ',.2f'}}
RANKING_AUSBAU_COLS = [
    {'name': 'Geschätztes Ausbaupotenzial (m² BGF)', 'id': 'Metric_display', 'type': 'numeric', 'format': {'specifier': ',.0f'}},
    {'name': 'Ø Ausnützungsziffer (Gemeinde)', 'id': 'Durchschnitt_AZ', 'type': 'numeric', 'format': {'specifier': ',.2f'}},
]


def _potenzial_ranking_shell():
    """Gemeinden-Ranking nach unüberbauter (noch nicht genutzter) Bauzonenfläche - Potenzial-
    Indikator auf Gemeinde-Ebene (services/are_stats.py). Eine echte Parzellen-Rangliste für
    die ganze Schweiz ist nicht berechenbar (siehe Moduldoc dort); für eine konkrete Parzelle
    innerhalb einer hier gerankten Gemeinde: "Gemeinde wählen" oben, dann bei erfasster
    Ausnützungsziffer auf Analyse Parzellen das "Ausbaupotenzial" für eine Adresse berechnen."""
    return section_card('Potenzial-Ranking: Unüberbaute Bauzonen', html.Div([
        html.P('Anteil der amtlichen Bauzone (Wohn-/Arbeits-/Misch-/Zentrumszonen), der laut ARE-Bauzonenstatistik 2022 '
               'noch unbebaut ist - die einzige national vollständige, amtliche Potenzial-Kennzahl auf Gemeinde-Ebene '
               '(eine Parzellen-Rangliste für die ganze Schweiz ist technisch nicht berechenbar). Absolute Fläche '
               'begünstigt grosse Gemeinden; pro 1\'000 Einwohner setzt sie ins Verhältnis zur Gemeindegrösse.',
               className='kpi-subtitle', style={'marginBottom': '10px'}),
        dcc.RadioItems(id='potenzial-metric', options=METRIC_OPTIONS, value='absolut', inline=True,
                       inputStyle={'marginRight': '6px'}, labelStyle={'marginRight': '20px'}),
        html.Div(id='potenzial-ranking-content', style={'marginTop': '12px'}),
    ]))


@callback(Output('potenzial-ranking-content', 'children'), Input('potenzial-metric', 'value'))
def update_potenzial_ranking(metric):
    reserven = get_bauzonenreserven()
    if reserven is None or reserven.empty:
        return html.P('ARE-Bauzonenstatistik aktuell nicht abrufbar.', className='kpi-subtitle')

    coords = municipality_coordinates()
    merged = reserven.merge(coords, on='BFS', how='inner')
    note = None

    if metric == 'pro_kopf':
        pop = municipality_population()
        merged = merged.merge(pop, on='BFS', how='inner')
        merged = merged[merged['Bevoelkerung'] > 0]
        merged['Metric'] = merged['Unueberbaut_ha'] / (merged['Bevoelkerung'] / 1000)
        color_label = 'ha pro 1\'000 Einwohner'
        color_format = ',.2f'
    elif metric == 'ausbaupotenzial':
        n_before = len(merged)
        az = municipality_average_ausnuetzungsziffer()
        merged = merged.merge(az, on='BFS', how='inner')
        # unüberbaute Fläche (ha) × 10'000 m²/ha × Ø Ausnützungsziffer dieser Gemeinde - dieselbe
        # Logik wie "Ausbaupotenzial" auf Analyse Parzellen (Fläche × AZ), hier aber gemeindeweit
        # und mit der Ø AZ statt der tatsächlichen Zone, da diese für die ARE-Reserveflächen
        # nicht bekannt ist. Grobe Schätzung, keine aktuelle Nutzungsfläche abgezogen (anders
        # als beim Parzellen-Ausbaupotenzial), da auf unüberbauter Fläche nichts steht.
        merged['Metric'] = merged['Unueberbaut_ha'] * 10000 * merged['Durchschnitt_AZ']
        color_label = 'Geschätztes Ausbaupotenzial (m² BGF)'
        color_format = ',.0f'
        note = html.P(f'Nur Gemeinden mit erfasster Ausnützungsziffer: {len(merged):,} von {n_before:,} - für die anderen '
                       'lässt sich kein Ausbaupotenzial schätzen (siehe "Abdeckung Ausnützungsziffer" oben). Schätzung = '
                       'unüberbaute Fläche × Ø Ausnützungsziffer aller erfassten Zonen der Gemeinde - nicht zonenscharf.',
                       className='kpi-subtitle', style={'marginBottom': '10px'})
    else:
        merged['Metric'] = merged['Unueberbaut_ha']
        color_label = 'Unüberbaut (ha)'
        color_format = ',.1f'

    fig_map = px.scatter_map(
        merged, lat='Latitude', lon='Longitude', color='Metric', hover_name='Name',
        hover_data={'Kanton': True, 'Gesamtbauzone_ha': ':.1f', 'Unueberbaut_ha': ':.1f', 'Latitude': False, 'Longitude': False},
        color_continuous_scale=['#F4F7FA', COLORS['teal']], labels={'Metric': color_label},
        zoom=6.4, center={'lat': 46.8, 'lon': 8.2}, map_style='carto-positron', height=480,
    )
    fig_map.update_layout(margin=dict(l=0, r=0, t=0, b=0), coloraxis_colorbar=dict(tickformat=color_format))

    top = merged.sort_values('Metric', ascending=False).head(RANKING_TOP_N).copy()
    top['Gemeinde_Link'] = top.apply(lambda r: f"[{r['Name']}](/gemeinde?bfs={int(r['BFS'])})", axis=1)
    top['Metric_display'] = top['Metric']
    # Bei "absolut" ist die Metrik bereits Unueberbaut_ha (schon in RANKING_BASE_COLS) - die
    # Pro-Kopf-/Ausbaupotenzial-Spalten nur zusätzlich anzeigen, wenn sie etwas Neues gegenüber
    # der Basisspalte sind.
    extra_cols = {'pro_kopf': [RANKING_PRO_KOPF_COL], 'ausbaupotenzial': RANKING_AUSBAU_COLS}.get(metric, [])
    cols = RANKING_BASE_COLS + extra_cols
    table = styled_table(top.to_dict('records'), cols, page_size=RANKING_TOP_N, sort=True, filter_=False)

    return html.Div([
        note,
        dcc.Graph(figure=fig_map, config=CHART_CONFIG),
        html.H4(f'Top {RANKING_TOP_N} Gemeinden ({color_label})', style={'fontSize': '0.9rem', 'margin': '16px 0 8px'}),
        table,
    ])


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
    zonen_panel = _zonen_panel(bfs)
    parcel_ranking_shell = _parcel_ranking_shell(bfs)

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
        zonen_panel,
        parcel_ranking_shell,
        peer_benchmark_panel,
    ], className='page-body', style={'marginTop': '28px'})


ZONE_TABLE_COLS = [{'name': c, 'id': c} for c in
                   ['Zone', 'Baugesuche (Basis)', 'Ausnützungsziffer', 'Grenzabstand', 'Gebäudehöhe', 'Geschosse']]

# HAUPTNUTZUNG_GROUPS/_ORDER kommen aus services/geo.py (dort auch von services/parcel_ranking.py
# für den Hauptnutzungs-Filter genutzt) - dataviz-Grundsatz: Kategorien NIE einfach durchzyklen,
# bei zu vielen in eine "Andere"-Sammelkategorie falten. PLOTLY_COLORWAY-Reihenfolge
# (blue/teal/orange/green, bereits per validate_palette.js geprüft) + neutrales Grau für
# "Andere" - exakt dieselbe 5er-Palette wie auf der Ausnützungsziffer-Abdeckungskarte.
HAUPTNUTZUNG_COLORS = {
    'Wohnzonen': COLORS['blue'], 'Zentrums- und Mischzonen': COLORS['teal'],
    'Arbeitszonen': COLORS['orange'], 'Landwirtschaftszonen': COLORS['green'], 'Andere': COLORS['gray'],
}


def _cap(text):
    return text[:1].upper() + text[1:] if text else text


def _zonen_panel(bfs):
    param_df = zone_parameters_for_municipality(bfs)
    if len(param_df):
        param_df = param_df.copy()
        param_df['Zone'] = param_df['Zone'].apply(_cap)
        table = styled_table(param_df.to_dict('records'), ZONE_TABLE_COLS, page_size=15, sort=True, filter_=False)
    else:
        table = html.P('Keine Zonenparameter für diese Gemeinde erfasst.', className='kpi-subtitle')

    zones = get_zones_for_municipality(bfs)
    if not zones:
        map_content = html.P('Zonenkarte aktuell nicht verfügbar (geodienste.ch/swissBOUNDARIES3D nicht erreichbar '
                              'oder keine Zonen für diese Gemeinde gefunden).', className='kpi-subtitle')
    else:
        geojson = {'type': 'FeatureCollection', 'features': [
            {'type': 'Feature', 'id': z['id'], 'geometry': z['geometry'], 'properties': {}} for z in zones
        ]}
        map_df = pd.DataFrame([{
            'id': z['id'],
            'Hauptnutzung': HAUPTNUTZUNG_GROUPS.get(z['hauptnutzung'], 'Andere'),
            'Zone': _cap(z['zone']),
        } for z in zones])

        lons = [pt[0] for z in zones for ring in _geometry_rings(z['geometry']) for pt in ring]
        lats = [pt[1] for z in zones for ring in _geometry_rings(z['geometry']) for pt in ring]
        lon_span = max(max(lons) - min(lons), 0.002)
        lat_span = max(max(lats) - min(lats), 0.002)
        zoom = max(9, min(15, 8 - math.log2(max(lat_span, lon_span))))

        fig = px.choropleth_map(
            map_df, geojson=geojson, locations='id', color='Hauptnutzung', hover_data={'Zone': True, 'id': False},
            color_discrete_map=HAUPTNUTZUNG_COLORS, category_orders={'Hauptnutzung': HAUPTNUTZUNG_ORDER},
            map_style='carto-positron', opacity=0.75, zoom=zoom,
            center={'lat': (min(lats) + max(lats)) / 2, 'lon': (min(lons) + max(lons)) / 2}, height=520,
        )
        fig.update_layout(margin=dict(l=0, r=0, t=10, b=30), legend=dict(orientation='h', y=-0.18, title=None))
        map_content = dcc.Graph(figure=fig, config=CHART_CONFIG)

    return section_card('Zonen', html.Div([
        html.Div(map_content, style={'marginBottom': '16px'}),
        table,
    ]))


def _geometry_rings(geometry):
    if geometry.get('type') == 'Polygon':
        return geometry['coordinates']
    if geometry.get('type') == 'MultiPolygon':
        return [ring for poly in geometry['coordinates'] for ring in poly]
    return []


PARCEL_TOPN_OPTIONS = [{'label': str(n), 'value': n} for n in [10, 25, 50, 100]]
PARCEL_HAUPTNUTZUNG_OPTIONS = [{'label': 'Alle', 'value': 'Alle'}] + [{'label': h, 'value': h} for h in HAUPTNUTZUNG_ORDER]
PARCEL_RANK_COLS = [
    {'name': 'Adresse', 'id': 'adresse'}, {'name': 'Hauptnutzung', 'id': 'hauptnutzung'}, {'name': 'Zone', 'id': 'zone'},
    {'name': 'AZ', 'id': 'az', 'type': 'numeric', 'format': {'specifier': ',.2f'}},
    {'name': 'Parzellenfläche (m²)', 'id': 'parzellenflaeche_m2', 'type': 'numeric', 'format': {'specifier': ',.0f'}},
    {'name': 'Aktuelle Nutzungsfläche (m²)', 'id': 'nutzungsflaeche_aktuell_m2', 'type': 'numeric', 'format': {'specifier': ',.0f'}},
    {'name': 'Ausbaupotenzial (m²)', 'id': 'ausbaupotenzial_m2', 'type': 'numeric', 'format': {'specifier': ',.0f'}},
]
PARCEL_RANK_ERROR_MESSAGES = {
    'keine_az': 'Für diese Gemeinde ist keine Ausnützungsziffer erfasst - Ausbaupotenzial kann nicht berechnet werden '
                '(siehe "Abdeckung Ausnützungsziffer" oben).',
    'keine_gebaeude': 'Keine Gebäudedaten (GWR) für diese Gemeinde verfügbar.',
    'keine_zonen': 'Zonenkarte für diese Gemeinde aktuell nicht verfügbar.',
    'keine_kandidaten': 'Keine bestehenden Gebäude in einer Zone mit erfasster Ausnützungsziffer gefunden.',
}


def _parcel_ranking_shell(bfs):
    """Rangliste der Parzellen mit grösstem Ausbaupotenzial INNERHALB der gewählten Gemeinde -
    auf Knopfdruck statt automatisch, da die Berechnung pro Gebäude einen Live-Request gegen
    api3.geo.admin.ch braucht (Parzellenfläche, keine Bulk-Quelle - siehe
    services/parcel_ranking.py) und je nach Gemeindegrösse bis zu einer Minute dauert."""
    return section_card('Rangliste: Parzellen mit grösstem Ausbaupotenzial', html.Div([
        html.P(f'Für die gewählte Gemeinde: Ausbaupotenzial je Gebäude/Parzelle, direkt aus Live-Gebäude- und '
               f'Parzellendaten berechnet (keine Bulk-Parzellendatenbank verfügbar - anders als das Potenzial-'
               f'Ranking oben, das auf Gemeinde-Ebene bleibt). Bei vielen Kandidaten wird nur eine Zufallsstichprobe '
               f'von bis zu {FETCH_CAP} Gebäuden abgefragt (ca. 3-4 Abfragen/Sekunde) - das Ergebnis ist dann eine '
               f'Annäherung, kein exaktes Ranking über alle Gebäude der Gemeinde. Berechnung kann bis zu 1-2 '
               f'Minuten dauern.', className='kpi-subtitle', style={'marginBottom': '10px'}),
        html.Div([
            html.Span('Anzahl Parzellen: ', style={'marginRight': '8px'}),
            dcc.Dropdown(id='parcel-rank-topn', options=PARCEL_TOPN_OPTIONS, value=25, clearable=False,
                         style={'width': '100px', 'display': 'inline-block', 'verticalAlign': 'middle'}),
            html.Span('Hauptnutzung: ', style={'marginLeft': '24px', 'marginRight': '8px'}),
            dcc.Dropdown(id='parcel-rank-hauptnutzung', options=PARCEL_HAUPTNUTZUNG_OPTIONS, value='Alle', clearable=False,
                         style={'width': '220px', 'display': 'inline-block', 'verticalAlign': 'middle'}),
            html.Button('Berechnen', id='parcel-rank-button', n_clicks=0, className='btn-primary', style={'marginLeft': '16px'}),
        ], style={'display': 'flex', 'alignItems': 'center', 'marginBottom': '12px'}),
        dcc.Loading(html.Div(id='parcel-rank-content'), type='circle'),
    ]))


@callback(
    Output('parcel-rank-content', 'children'),
    Input('parcel-rank-button', 'n_clicks'), Input('bfs-select', 'value'),
    State('parcel-rank-topn', 'value'), State('parcel-rank-hauptnutzung', 'value'),
    prevent_initial_call=True,
)
def update_parcel_ranking(_n_clicks, bfs, top_n, hauptnutzung):
    # Gemeinde gewechselt statt Button geklickt: alte Rangliste gehört nicht mehr zur neuen
    # Gemeinde - leeren statt stehen lassen, erst nach erneutem Klick neu berechnen.
    if dash.ctx.triggered_id == 'bfs-select':
        return None
    if not bfs:
        return empty_state('Bitte Gemeinde wählen.')

    hauptnutzung_filter = None if not hauptnutzung or hauptnutzung == 'Alle' else hauptnutzung
    top, meta = get_parcel_potential_ranking(bfs, top_n=top_n or 25, hauptnutzung_filter=hauptnutzung_filter)
    if top is None:
        return html.P(PARCEL_RANK_ERROR_MESSAGES.get(meta['reason'], 'Berechnung nicht möglich.'), className='kpi-subtitle')
    if top.empty:
        return html.P('Für die abgefragten Gebäude konnte keine Parzellenfläche ermittelt werden.', className='kpi-subtitle')

    sample_note = None
    if meta['n_candidates_total'] > meta['n_fetched']:
        sample_note = html.P(
            f"Stichprobe: {meta['n_fetched']} von {meta['n_candidates_total']} möglichen Gebäuden abgefragt "
            f"(Limit {meta['cap']}) - Ergebnis ist eine Annäherung, kein exaktes Ranking über alle Gebäude.",
            className='kpi-subtitle', style={'color': 'var(--orange)', 'marginBottom': '10px'})

    lat_span = max(top['lat'].max() - top['lat'].min(), 0.002)
    lon_span = max(top['lon'].max() - top['lon'].min(), 0.002)
    zoom = max(9, min(16, 8 - math.log2(max(lat_span, lon_span))))

    fig = px.scatter_map(
        top, lat='lat', lon='lon', color='ausbaupotenzial_m2', hover_name='adresse',
        hover_data={'hauptnutzung': True, 'zone': True, 'parzellenflaeche_m2': ':.0f', 'ausbaupotenzial_m2': ':.0f', 'lat': False, 'lon': False},
        color_continuous_scale=['#F4F7FA', COLORS['orange']], labels={'ausbaupotenzial_m2': 'Ausbaupotenzial (m²)'},
        zoom=zoom, center={'lat': (top['lat'].min() + top['lat'].max()) / 2, 'lon': (top['lon'].min() + top['lon'].max()) / 2},
        height=480,
    )
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))

    table = styled_table(top.to_dict('records'), PARCEL_RANK_COLS, page_size=len(top), sort=True, filter_=False)

    return html.Div([sample_note, dcc.Graph(figure=fig, config=CHART_CONFIG), table])


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
