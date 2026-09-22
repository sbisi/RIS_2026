import dash
from dash import html, dcc, Input, Output, callback
from config.settings import STATUS_COLORS
from services.data import (
    regulation_table, regulation_count, regulation_municipality_options,
    document_validation_status_counts, canton_options, regulation_subcounts,
)
from components.page_header import page_shell
from components.cards import section_card, empty_state, kpi
from components.filters import canton_dropdown, dropdown_filter, range_filter, reset_button, filter_bar
from components.tables import styled_table
from components.charts import scatter, bar, CHART_CONFIG, with_definition_hover

dash.register_page(__name__, path='/regulierung', name='Analyse Reglemente')

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


def layout(bfs=None, **kwargs):
    # bfs kommt als URL-Query-Param (?bfs=...) für Deep-Links von anderen Seiten (z.B.
    # Analyse Gemeinden "Analyse Reglemente ansehen") - vorbefüllt den Gemeinde-Filter
    # der Tabelle direkt, der zugehörige update_table()-Callback feuert dank des initialen
    # Dropdown-Werts ganz natürlich beim ersten Rendern (kein zusätzlicher Trigger nötig).
    try:
        cantons = canton_options()
        gemeinden = regulation_municipality_options()
        statuses = document_validation_status_counts()

        gemeinde_options = [{'label': f'{r.municipality_name} ({r.Kanton})', 'value': r.BFS} for r in gemeinden.itertuples()]
        status_options = [{'label': f'{r.validation_status} ({r.n})', 'value': r.validation_status} for r in statuses.itertuples()]

        table_filters = filter_bar(
            canton_dropdown('reg-table-canton', cantons),
            dropdown_filter('reg-table-gemeinde', 'Gemeinde', gemeinde_options, placeholder='Alle Gemeinden', width='240px',
                             value=int(bfs) if bfs else None),
            range_filter('Komplexitätsindex', 'reg-table-complexity-min', 'reg-table-complexity-max'),
            range_filter('Reglementsalter (Jahre)', 'reg-table-age-min', 'reg-table-age-max'),
            dropdown_filter('reg-table-status', 'Dok.-Status', status_options, placeholder='Alle Status', width='220px'),
            reset_button('reg-table-reset'),
        )

        # Bei Deep-Link mit vorgefiltertem bfs (z.B. von der Analyse Gemeinden) macht der Titel
        # sichtbar, dass die Seite in einem gefilterten Zustand ist, statt kommentarlos die
        # generische Übersicht zu zeigen - plus ein Rückweg zur Ursprungsseite.
        gemeinde_match = next((g for g in gemeinde_options if g['value'] == int(bfs)), None) if bfs else None
        subtitle = 'Reglementskomplexität, Interventionsgrad und Dokumentenalter je Gemeinde.'
        back_link = None
        if gemeinde_match:
            subtitle = f"Gefiltert auf {gemeinde_match['label']}."
            back_link = {'label': 'Zurück zur Analyse Gemeinden', 'href': f'/gemeinde?bfs={int(bfs)}'}

        return page_shell('/regulierung', 'Analyse Reglemente', subtitle, [
            section_card('Filter', filter_bar(canton_dropdown('regulation-canton', cantons))),
            html.Div(id='regulation-kpis'),
            section_card('Reglementsalter vs. Komplexität', dcc.Graph(id='regulation-scatter', config=CHART_CONFIG)),
            section_card('Gemeinde-Reglemente', [
                table_filters,
                html.Div(id='reg-table-result-count', className='kpi-subtitle', style={'margin': '18px 0 10px 0'}),
                html.Div(id='regulation-table-wrap'),
                html.P('Zeile links anklicken (Checkbox) für die Verdichtung-/Wohnen-Detailaufschlüsselung dieser Gemeinde.',
                       className='kpi-subtitle', style={'margin': '14px 0 10px 0'}),
                html.Div(id='reg-detail-panel'),
            ]),
        ], back_link=back_link)
    except Exception as e:
        return page_shell('/regulierung', 'Analyse Reglemente', '', empty_state(str(e)))


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
    table = styled_table(df.to_dict('records'), COLS, page_size=20, sort=True, filter_=False,
                          id='reg-table', row_selectable='single', selected_rows=[])
    return table, count_text


@callback(
    Output('reg-detail-panel', 'children'),
    Input('reg-table', 'derived_virtual_selected_rows'), Input('reg-table', 'derived_virtual_data'),
)
def update_detail_panel(selected_rows, virtual_data):
    if not selected_rows or not virtual_data:
        return None
    row = virtual_data[selected_rows[0]]
    bfs, name = row.get('BFS'), row.get('municipality_name')
    if not bfs:
        return None

    sub = regulation_subcounts(bfs)
    if sub.empty or sub['n'].sum() == 0:
        return section_card(f'Detailaufschlüsselung: {name}',
                             html.P('Keine Verdichtung-/Wohnen-Stichwörter im Reglementstext erfasst.', className='kpi-subtitle'))

    verdichtung = sub[sub['Oberbereich'] == 'Verdichtung']
    wohnen = sub[sub['Oberbereich'] == 'Wohnen']
    return section_card(f'Detailaufschlüsselung: {name}', html.Div([
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
    ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '18px'}))
