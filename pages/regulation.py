import dash
from dash import html, dcc, Input, Output, callback
from config.settings import STATUS_COLORS
from services.data import regulation_table, canton_options
from components.page_header import page_shell
from components.cards import section_card, empty_state, kpi
from components.filters import canton_dropdown, filter_bar
from components.tables import styled_table
from components.charts import scatter, CHART_CONFIG

dash.register_page(__name__, path='/regulierung', name='Reglementanalyse')

COLS = [
    {'name': 'Gemeinde', 'id': 'municipality_name'},
    {'name': 'BFS', 'id': 'BFS', 'type': 'numeric'},
    {'name': 'Kanton', 'id': 'Kanton'},
    {'name': 'Komplexitätsindex', 'id': 'complexity_index_raw', 'type': 'numeric', 'format': {'specifier': '.2f'}},
    {'name': 'Intervention', 'id': 'intervention_count', 'type': 'numeric'},
    {'name': 'Architektur', 'id': 'architecture_count', 'type': 'numeric'},
    {'name': 'Wohnen', 'id': 'housing_count', 'type': 'numeric'},
    {'name': 'Verdichtung', 'id': 'densification_count', 'type': 'numeric'},
    {'name': 'Reglementsalter', 'id': 'document_age', 'type': 'numeric', 'format': {'specifier': '.0f'}},
    {'name': 'Dok.-Status', 'id': 'validation_status'},
]


def layout():
    try:
        cantons = canton_options()
        return page_shell('/regulierung', 'Reglementanalyse', 'Reglementskomplexität, Interventionsgrad und Dokumentenalter je Gemeinde.', [
            section_card('Filter', filter_bar(canton_dropdown('regulation-canton', cantons))),
            html.Div(id='regulation-kpis'),
            section_card('Reglementsalter vs. Komplexität', dcc.Graph(id='regulation-scatter', config=CHART_CONFIG)),
            section_card('Gemeinde-Reglemente', html.Div(id='regulation-table-wrap')),
        ])
    except Exception as e:
        return page_shell('/regulierung', 'Reglementanalyse', '', empty_state(str(e)))


@callback(
    Output('regulation-kpis', 'children'), Output('regulation-scatter', 'figure'),
    Output('regulation-table-wrap', 'children'), Input('regulation-canton', 'value'),
)
def update(canton_id):
    df = regulation_table(canton_id)
    if df.empty:
        return None, {}, empty_state()

    kpis = html.Div([
        kpi('Gemeinden mit Reglement', f"{df['complexity_index_raw'].notna().sum():,}", accent='navy'),
        kpi('Ø Komplexitätsindex', f"{df['complexity_index_raw'].mean():.2f}", accent='blue'),
        kpi('Ø Reglementsalter', f"{df['document_age'].mean():.0f} Jahre" if df['document_age'].notna().any() else '–', accent='teal'),
        kpi('Ø Interventionen', f"{df['intervention_count'].mean():.1f}", accent='orange'),
    ], className='grid-4')

    fig = scatter(
        df.dropna(subset=['document_age', 'complexity_index_raw']), x='document_age', y='complexity_index_raw',
        color='validation_status', color_map=STATUS_COLORS, hover_data=['municipality_name', 'BFS', 'Kanton'],
        labels={'document_age': 'Reglementsalter (Jahre)', 'complexity_index_raw': 'Komplexitätsindex'},
    )

    return kpis, fig, styled_table(df.to_dict('records'), COLS)
