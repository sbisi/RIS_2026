import dash
from dash import html, dcc, Input, Output, callback
from services.data import ranking_table, canton_options
from components.page_header import page_shell
from components.cards import section_card, empty_state
from components.filters import canton_dropdown, filter_bar
from components.tables import styled_table
from components.charts import scatter, CHART_CONFIG

dash.register_page(__name__, path='/ranking', name='Gemeinderanking')

COLS = [
    {'name': 'Gemeinde', 'id': 'municipality_name'},
    {'name': 'BFS', 'id': 'BFS', 'type': 'numeric'},
    {'name': 'Kanton', 'id': 'Kanton'},
    {'name': 'Peer-Rang', 'id': 'peer_rank', 'type': 'numeric', 'format': {'specifier': '.0f'}},
    {'name': 'Prozess-Score', 'id': 'process_score', 'type': 'numeric', 'format': {'specifier': '.1f'}},
    {'name': 'Regulierungs-Score', 'id': 'regulation_score', 'type': 'numeric', 'format': {'specifier': '.1f'}},
    {'name': 'Markt-Score', 'id': 'market_score', 'type': 'numeric', 'format': {'specifier': '.1f'}},
    {'name': 'Gesamt-Score', 'id': 'overall_score', 'type': 'numeric', 'format': {'specifier': '.1f'}},
]


def layout():
    try:
        cantons = canton_options()
        return page_shell('/ranking', 'Gemeinderanking', 'Peer-Vergleich von Prozess-, Regulierungs- und Marktqualität je Gemeinde.', [
            section_card('Filter', filter_bar(canton_dropdown('ranking-canton', cantons))),
            section_card('Prozess- vs. Regulierungs-Score', dcc.Graph(id='ranking-scatter', config=CHART_CONFIG)),
            section_card('Rangliste', html.Div(id='ranking-table-wrap')),
        ])
    except Exception as e:
        return page_shell('/ranking', 'Gemeinderanking', '', empty_state(str(e)))


@callback(Output('ranking-scatter', 'figure'), Output('ranking-table-wrap', 'children'), Input('ranking-canton', 'value'))
def update(canton_id):
    df = ranking_table(canton_id)
    if df.empty:
        return {}, empty_state()
    plot_df = df.dropna(subset=['regulation_score', 'process_score', 'overall_score'])
    fig = scatter(
        plot_df, x='regulation_score', y='process_score', size='overall_score', color='overall_score',
        hover_data=['municipality_name', 'BFS', 'Kanton'],
        labels={'regulation_score': 'Regulierungs-Score', 'process_score': 'Prozess-Score'},
        color_continuous_scale=['#C00000', '#ED7D31', '#70AD47'],
    )
    return fig, styled_table(df.to_dict('records'), COLS)
