"""Analyse aller Gebäude einer Gemeinde (Bulk-GWR) - Karte, Kennzahlen, Verteilungen und
Volltabelle. Ergänzt den 'Gebäude'-Tab auf Analyse Parzellen (services/geo.py:
get_building_data, ein Gebäude pro Koordinate) um die Gemeinde-weite Sicht.

Datenquelle: der öffentliche MADD-Bulk-Export des BFS (siehe services/geo_buildings.py) -
deckt praktisch jede Schweizer Gemeinde vollständig ab."""
import math

import dash
import pandas as pd
import plotly.express as px
from dash import dcc, html, Input, Output, callback

from components.cards import kpi, section_card, empty_state
from components.charts import bar, CHART_CONFIG
from components.page_header import page_shell
from components.tables import styled_table
from services.geo_buildings import supported_municipalities, get_bulk_buildings

dash.register_page(__name__, path='/analyse-gebaeude', name='Analyse Gebäude')

MAP_SAMPLE_LIMIT = 3000
TABLE_COLUMNS = [
    {'name': 'EGID', 'id': 'egid'}, {'name': 'Bezeichnung', 'id': 'bezeichnung'},
    {'name': 'Status', 'id': 'status'}, {'name': 'Kategorie', 'id': 'kategorie'},
    {'name': 'Klasse', 'id': 'klasse'}, {'name': 'Baujahr', 'id': 'baujahr'},
    {'name': 'Geschosse', 'id': 'geschosse'}, {'name': 'Gebäudefläche (m²)', 'id': 'gebaeudeflaeche_m2'},
    {'name': 'Energiebezugsfläche (m²)', 'id': 'energiebezugsflaeche_m2'},
    {'name': 'Anzahl Wohnungen', 'id': 'anzahl_wohnungen'},
]


def layout(bfs=None, **kwargs):
    opts = supported_municipalities()
    options = [{'label': f"{r.name} ({r.canton})", 'value': int(r.bfs)} for r in opts.itertuples()]
    default = int(bfs) if bfs and int(bfs) in [o['value'] for o in options] else (options[0]['value'] if options else None)
    return page_shell('/analyse-gebaeude', 'Analyse Gebäude',
                       'Gebäudebestand einer Gemeinde: Karte, Kennzahlen und Volltabelle aus offenen GWR-Bulk-Daten.', [
        section_card('Gemeinde wählen', html.Div([
            dcc.Dropdown(id='geb-bfs-select', options=options, value=default, placeholder='Gemeinde wählen',
                         style={'maxWidth': '420px', 'flex': 1}),
        ], style={'display': 'flex', 'gap': '16px', 'alignItems': 'center'})),
        html.P('Datenquelle: öffentlicher Bulk-Export des eidg. Gebäude- und Wohnungsregisters (GWR, BFS/MADD) - '
               'https://www.housing-stat.ch, täglich aktualisiert. Falls für eine Gemeinde keine Daten '
               'erscheinen, siehe stattdessen den "Gebäude"-Tab auf Analyse Parzellen für ein einzelnes Gebäude.',
               className='kpi-subtitle', style={'margin': '10px 0 20px'}),
        html.Div(id='geb-content'),
    ])


def _period_order(labels):
    # Bauperiode-Labels wie "vor 1919" / "Periode von 1981 bis 1985" chronologisch sortieren,
    # statt alphabetisch (sonst landet "vor 1919" mitten in der Liste).
    def key(label):
        if not label:
            return (1, 0)
        if 'vor' in label:
            return (0, 0)
        digits = [int(s) for s in label.split() if s.isdigit()]
        return (0, digits[0]) if digits else (2, 0)
    return sorted(labels, key=key)


@callback(Output('geb-content', 'children'), Input('geb-bfs-select', 'value'))
def update_content(bfs):
    if bfs is None:
        return empty_state('Bitte Gemeinde wählen.')
    df = get_bulk_buildings(bfs)
    if df is None or df.empty:
        return empty_state('Keine Gebäudedaten für diese Gemeinde verfügbar oder Abfrage fehlgeschlagen.')

    n = len(df)
    avg_baujahr = df['baujahr'].mean()
    avg_geschosse = df['geschosse'].mean()
    sum_flaeche = df['gebaeudeflaeche_m2'].sum()
    sum_ebf = df['energiebezugsflaeche_m2'].sum()

    kpis = html.Div([
        kpi('Anzahl Gebäude', f'{n:,}', accent='navy'),
        kpi('Ø Baujahr', f'{avg_baujahr:.0f}' if avg_baujahr == avg_baujahr else '–', accent='blue'),
        kpi('Ø Geschosse', f'{avg_geschosse:.1f}' if avg_geschosse == avg_geschosse else '–', accent='teal'),
        kpi('Gebäudefläche gesamt', f'{sum_flaeche:,.0f} m²' if sum_flaeche == sum_flaeche else '–', accent='orange'),
        kpi('Energiebezugsfläche gesamt', f'{sum_ebf:,.0f} m²' if sum_ebf == sum_ebf else '–',
            'nicht bei allen Gebäuden erfasst' if sum_ebf == sum_ebf else '', accent='green'),
    ], className='grid-4', style={'marginBottom': '20px'})

    period_counts = df['bauperiode'].value_counts(dropna=True).reset_index()
    period_counts.columns = ['Bauperiode', 'Anzahl']
    period_order = _period_order(period_counts['Bauperiode'].tolist())
    period_counts['Bauperiode'] = pd.Categorical(period_counts['Bauperiode'], categories=period_order, ordered=True)
    period_counts = period_counts.sort_values('Bauperiode')

    kategorie_counts = df['kategorie'].value_counts(dropna=True).reset_index()
    kategorie_counts.columns = ['Kategorie', 'Anzahl']

    charts = html.Div([
        section_card('Bauperioden-Verteilung', dcc.Graph(
            figure=bar(period_counts, x='Anzahl', y='Bauperiode', labels={'Anzahl': '', 'Bauperiode': ''})
                   .update_layout(yaxis={'categoryorder': 'array', 'categoryarray': period_order, 'automargin': True}),
            config=CHART_CONFIG)),
        section_card('Gebäudekategorie-Verteilung', dcc.Graph(
            figure=bar(kategorie_counts, x='Anzahl', y='Kategorie', labels={'Anzahl': '', 'Kategorie': ''}),
            config=CHART_CONFIG)),
    ], className='grid-2', style={'marginBottom': '20px'})

    map_df = df.dropna(subset=['lat', 'lon'])
    map_note = None
    if len(map_df) > MAP_SAMPLE_LIMIT:
        map_df = map_df.sample(MAP_SAMPLE_LIMIT, random_state=0)
        map_note = html.P(f'Kartendarstellung aus Performance-Gründen auf eine Zufallsstichprobe von '
                           f'{MAP_SAMPLE_LIMIT:,} der insgesamt {n:,} Gebäude begrenzt - Kennzahlen und Tabelle '
                           f'unten zeigen alle Gebäude.', className='kpi-subtitle', style={'marginTop': '6px'})

    lat_span = max(map_df['lat'].max() - map_df['lat'].min(), 0.002)
    lon_span = max(map_df['lon'].max() - map_df['lon'].min(), 0.002)
    zoom = max(9, min(15, 8 - math.log2(max(lat_span, lon_span))))
    map_fig = px.scatter_map(
        map_df, lat='lat', lon='lon', color='baujahr', hover_name='bezeichnung',
        hover_data={'egid': True, 'kategorie': True, 'lat': False, 'lon': False},
        color_continuous_scale='Blues', zoom=zoom,
        center={'lat': map_df['lat'].mean(), 'lon': map_df['lon'].mean()},
        map_style='carto-positron', height=520,
    )
    map_fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    map_card = section_card('Karte', html.Div([dcc.Graph(figure=map_fig, config=CHART_CONFIG), map_note]))

    table_data = df[[c['id'] for c in TABLE_COLUMNS]].to_dict('records')
    table_card = section_card('Alle Gebäude', styled_table(table_data, TABLE_COLUMNS, page_size=25))

    return html.Div([kpis, charts, map_card, html.Div(style={'marginTop': '20px'}), table_card])
