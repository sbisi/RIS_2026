import dash
from dash import html, dcc, Input, Output, callback
from services.data import (
    metrics, project_types, devtype_breakdown, projects_table, projects_count,
    project_filter_options, canton_options, municipality_options,
)
from components.page_header import page_shell
from components.cards import section_card, empty_state, kpi
from components.filters import canton_dropdown, dropdown_filter, range_filter, date_range_filter, reset_button, filter_bar
from components.tables import styled_table
from components.charts import bar, CHART_CONFIG
from config.settings import COLORS

dash.register_page(__name__, path='/Baugesuche', name='Analyse Baugesuche')

TABLE_COLS = [
    {'name': 'PROJID', 'id': 'PROJID', 'type': 'numeric'},
    {'name': 'Gemeinde', 'id': 'municipality_name'},
    {'name': 'Kanton', 'id': 'Kanton'},
    {'name': 'Eingereicht', 'id': 'applied_date', 'type': 'datetime'},
    {'name': 'Genehmigt', 'id': 'approved_date', 'type': 'datetime'},
    {'name': 'Bearbeitungsdauer (Tage)', 'id': 'processing_days', 'type': 'numeric', 'format': {'specifier': '.0f'}},
]

RESULT_LIMIT = 500


def layout():
    try:
        m = metrics()
        cantons = canton_options()
        gemeinden = municipality_options()
        fsa_opts, devtype_opts = project_filter_options()
        fsa_options = [{'label': r.fsa_description, 'value': r.fsa_code} for r in fsa_opts.itertuples()]
        devtype_options = [{'label': r.devtype_description, 'value': r.devtype_code} for r in devtype_opts.itertuples()]
        gemeinde_options = [{'label': f'{r.municipality_name} ({r.Kanton})', 'value': r.BFS} for r in gemeinden.itertuples()]

        kpis = html.Div([
            kpi('Projekte total', f"{int(m['projects']):,}", accent='navy'),
            kpi('Median Bearbeitungsdauer', f"{m['median']:.0f} Tage" if m['median'] == m['median'] else '–', accent='blue'),
            kpi('Anteil > 365 Tage', f"{m['over365']:.1%}" if m['over365'] == m['over365'] else '–', accent='orange'),
        ], className='grid-3')

        pt = project_types()
        dt = devtype_breakdown()
        fig_fsa = bar(pt.head(12), x='n', y='fsa_text', labels={'fsa_text': '', 'n': 'Projekte'})
        fig_dt = bar(dt, x='n', y='devtype_text', labels={'devtype_text': '', 'n': 'Projekte'})

        filters = filter_bar(
            canton_dropdown('bp-canton', cantons),
            dropdown_filter('bp-gemeinde', 'Gemeinde', gemeinde_options, placeholder='Alle Gemeinden', width='240px'),
            dropdown_filter('bp-fsa', 'Gebäudefunktion', fsa_options, width='280px'),
            dropdown_filter('bp-devtype', 'Baumassnahmenart', devtype_options, width='220px'),
            range_filter('Bearbeitungsdauer (Tage)', 'bp-days-min', 'bp-days-max'),
            date_range_filter('Eingereicht (Zeitraum)', 'bp-date-range'),
            reset_button('bp-reset'),
        )

        return page_shell('/Baugesuche', 'Analyse Baugesuche', 'Explorative Analyse der Baugesuchsdaten nach Gebäudefunktion und Baumassnahmenart.', [
            kpis,
            html.Div([
                section_card('Gebäudefunktionen (FSA)', dcc.Graph(figure=fig_fsa, config=CHART_CONFIG)),
                section_card('Baumassnahmenart', dcc.Graph(figure=fig_dt, config=CHART_CONFIG)),
            ], className='grid-2'),
            section_card('Projekte', [
                filters,
                html.Div(id='bp-result-count', className='kpi-subtitle', style={'margin': '18px 0 10px 0'}),
                html.Div(id='bp-table-wrap'),
            ]),
        ])
    except Exception as e:
        return page_shell('/Baugesuche', 'Analyse Baugesuche', '', empty_state(str(e)))


@callback(
    Output('bp-canton', 'value'), Output('bp-gemeinde', 'value'), Output('bp-fsa', 'value'), Output('bp-devtype', 'value'),
    Output('bp-days-min', 'value'), Output('bp-days-max', 'value'),
    Output('bp-date-range', 'start_date'), Output('bp-date-range', 'end_date'),
    Input('bp-reset', 'n_clicks'),
    prevent_initial_call=True,
)
def reset_filters(n_clicks):
    return None, None, None, None, None, None, None, None


@callback(
    Output('bp-table-wrap', 'children'), Output('bp-result-count', 'children'),
    Input('bp-canton', 'value'), Input('bp-gemeinde', 'value'), Input('bp-fsa', 'value'), Input('bp-devtype', 'value'),
    Input('bp-days-min', 'value'), Input('bp-days-max', 'value'),
    Input('bp-date-range', 'start_date'), Input('bp-date-range', 'end_date'),
)
def update(canton_id, bfs, fsa_code, devtype_code, days_min, days_max, date_from, date_to):
    kwargs = dict(canton_id=canton_id, bfs=bfs, fsa_code=fsa_code, devtype_code=devtype_code,
                  min_days=days_min, max_days=days_max, date_from=date_from, date_to=date_to)
    total = projects_count(**kwargs)
    if not total:
        return empty_state('Keine Projekte für diese Filterkombination gefunden.'), ''

    df = projects_table(**kwargs, limit=RESULT_LIMIT)
    count_text = f"{total:,} Projekte gefunden" + (f" – zeigt die neuesten {RESULT_LIMIT}" if total > RESULT_LIMIT else '')
    table = styled_table(
        df.to_dict('records'), TABLE_COLS, page_size=20, sort=True, filter_=False,
        style_data_conditional=[
            {'if': {'row_index': 'odd'}, 'backgroundColor': '#F7F9FB'},
            {'if': {'filter_query': '{processing_days} > 365', 'column_id': 'processing_days'},
             'color': COLORS['red'], 'fontWeight': '700'},
            {'if': {'filter_query': '{processing_days} > 180 && {processing_days} <= 365', 'column_id': 'processing_days'},
             'color': COLORS['orange'], 'fontWeight': '600'},
        ],
    )
    return table, count_text
