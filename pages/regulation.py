import dash
from dash import html, dcc, Input, Output, callback
from config.settings import STATUS_COLORS
from services.data import (
    regulation_table, regulation_count, regulation_municipality_options,
    document_validation_status_counts, canton_options,
)
from components.page_header import page_shell
from components.cards import section_card, empty_state, kpi
from components.filters import canton_dropdown, dropdown_filter, range_filter, reset_button, filter_bar
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
        gemeinden = regulation_municipality_options()
        statuses = document_validation_status_counts()

        gemeinde_options = [{'label': f'{r.municipality_name} ({r.Kanton})', 'value': r.BFS} for r in gemeinden.itertuples()]
        status_options = [{'label': f'{r.validation_status} ({r.n})', 'value': r.validation_status} for r in statuses.itertuples()]

        table_filters = filter_bar(
            canton_dropdown('reg-table-canton', cantons),
            dropdown_filter('reg-table-gemeinde', 'Gemeinde', gemeinde_options, placeholder='Alle Gemeinden', width='240px'),
            range_filter('Komplexitätsindex', 'reg-table-complexity-min', 'reg-table-complexity-max'),
            range_filter('Reglementsalter (Jahre)', 'reg-table-age-min', 'reg-table-age-max'),
            dropdown_filter('reg-table-status', 'Dok.-Status', status_options, placeholder='Alle Status', width='220px'),
            reset_button('reg-table-reset'),
        )

        return page_shell('/regulierung', 'Reglementanalyse', 'Reglementskomplexität, Interventionsgrad und Dokumentenalter je Gemeinde.', [
            section_card('Filter', filter_bar(canton_dropdown('regulation-canton', cantons))),
            html.Div(id='regulation-kpis'),
            section_card('Reglementsalter vs. Komplexität', dcc.Graph(id='regulation-scatter', config=CHART_CONFIG)),
            section_card('Gemeinde-Reglemente', [
                table_filters,
                html.Div(id='reg-table-result-count', className='kpi-subtitle', style={'margin': '18px 0 10px 0'}),
                html.Div(id='regulation-table-wrap'),
            ]),
        ])
    except Exception as e:
        return page_shell('/regulierung', 'Reglementanalyse', '', empty_state(str(e)))


@callback(
    Output('regulation-kpis', 'children'), Output('regulation-scatter', 'figure'),
    Input('regulation-canton', 'value'),
)
def update_overview(canton_id):
    df = regulation_table(canton_id)
    if df.empty:
        return None, {}

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
    return kpis, fig


@callback(
    Output('reg-table-canton', 'value'), Output('reg-table-gemeinde', 'value'),
    Output('reg-table-complexity-min', 'value'), Output('reg-table-complexity-max', 'value'),
    Output('reg-table-age-min', 'value'), Output('reg-table-age-max', 'value'),
    Output('reg-table-status', 'value'),
    Input('reg-table-reset', 'n_clicks'),
    prevent_initial_call=True,
)
def reset_table_filters(n_clicks):
    return None, None, None, None, None, None, None


@callback(
    Output('regulation-table-wrap', 'children'), Output('reg-table-result-count', 'children'),
    Input('reg-table-canton', 'value'), Input('reg-table-gemeinde', 'value'),
    Input('reg-table-complexity-min', 'value'), Input('reg-table-complexity-max', 'value'),
    Input('reg-table-age-min', 'value'), Input('reg-table-age-max', 'value'),
    Input('reg-table-status', 'value'),
)
def update_table(canton_id, bfs, complexity_min, complexity_max, age_min, age_max, status):
    kwargs = dict(canton_id=canton_id, bfs=bfs, min_complexity=complexity_min, max_complexity=complexity_max,
                  min_age=age_min, max_age=age_max, validation_status=status)
    total = regulation_count(**kwargs)
    if not total:
        return empty_state('Keine Gemeinde-Reglemente für diese Filterkombination gefunden.'), ''

    df = regulation_table(**kwargs)
    count_text = f"{total:,} Gemeinde-Reglemente gefunden"
    return styled_table(df.to_dict('records'), COLS, page_size=20, sort=True, filter_=False), count_text
