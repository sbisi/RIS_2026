import re
from urllib.parse import quote

import dash
import requests
from dash import html, dcc, callback, Input, Output, State, ALL, ctx

from services.data import search_municipalities
from components.page_header import page_shell
from components.cards import section_card, empty_state

dash.register_page(__name__, path='/suche', name='Suche')

ADDRESS_SEARCH_URL = 'https://lawmanager.app.levell.ch/api/geoadmin/addressSearch'
MIN_CHARS = 3


def clean_html(text):
    """Entfernt HTML-Tags (z.B. <b>PLZ Ort</b>) aus dem API-Label."""
    return re.sub(r'<.*?>', '', text or '')


def layout():
    return page_shell('/suche', 'Suche', 'Gemeinde, Adresse oder Parzellennummer suchen.', [
        section_card('Adress- und Gemeindesuche', [
            html.Div([
                dcc.Input(
                    id='search-input', type='text',
                    placeholder='Gemeinde, Adresse oder Parzellennummer eingeben (mind. 3 Zeichen)',
                    value='', autoComplete='off',
                    style={'flex': 1, 'height': '38px', 'padding': '0 12px', 'border': '1px solid var(--border)', 'borderRadius': '6px'},
                ),
                html.Button('Suchen', id='search-button', n_clicks=0, className='btn-primary'),
            ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'center', 'maxWidth': '700px'}),
            html.Div(id='search-suggestions', style={'maxWidth': '700px'}),
            dcc.Store(id='suggestions-data', data=[]),
            dcc.Location(id='search-redirect', refresh=True),
            html.Div(id='search-output', style={'marginTop': '16px'}),
        ]),
    ])


@callback(
    Output('search-suggestions', 'children'), Output('suggestions-data', 'data'),
    Input('search-input', 'value'),
)
def suggest_locations(search_value):
    if not search_value or len(search_value) < MIN_CHARS:
        return None, []

    muni_df = search_municipalities(search_value, limit=5)
    municipalities = [
        {'kind': 'municipality', 'label': f"🏛 {r.municipality_name} ({r.Kanton}) – Gemeindeprofil", 'bfs': int(r.BFS)}
        for r in muni_df.itertuples()
    ]

    try:
        resp = requests.get(f'{ADDRESS_SEARCH_URL}?search={quote(search_value)}', timeout=5)
        resp.raise_for_status()
        data = resp.json()
        addresses = [
            {'kind': 'address', 'label': clean_html(a.get('label')), 'lat': a.get('lat'), 'lon': a.get('lon')}
            for a in data.get('addresses', [])
        ]
    except requests.exceptions.RequestException:
        addresses = []

    suggestions = municipalities + addresses
    if not suggestions:
        return html.Div('Keine Treffer.', className='kpi-subtitle'), []

    items = [
        html.Div(s['label'], id={'type': 'suggestion-item', 'index': i},
                 n_clicks=0, className='suggestion-item' + (' suggestion-item-muni' if s['kind'] == 'municipality' else ''))
        for i, s in enumerate(suggestions)
    ]
    return html.Div(items, className='suggestion-list'), suggestions


@callback(
    Output('search-output', 'children'), Output('search-suggestions', 'children', allow_duplicate=True),
    Output('search-input', 'value'), Output('search-redirect', 'href'),
    Input({'type': 'suggestion-item', 'index': ALL}, 'n_clicks'), Input('search-button', 'n_clicks'),
    State('suggestions-data', 'data'), State('search-input', 'value'),
    prevent_initial_call=True,
)
def select_or_search(item_clicks, button_clicks, suggestions, current_value):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get('type') == 'suggestion-item':
        idx = triggered['index']
        if not any(item_clicks) or idx >= len(suggestions):
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update
        item = suggestions[idx]

        if item['kind'] == 'municipality':
            return dash.no_update, dash.no_update, dash.no_update, f"/gemeinde?bfs={item['bfs']}"

        result = html.Div([
            html.Div([
                html.Div(item['label'], className='search-result-label'),
                html.Div(f"Koordinaten: {item['lat']}, {item['lon']}", className='search-result-meta'),
            ]),
            html.Div([
                dcc.Link('Parzelle & Zone anzeigen →', href=f"/suche/parzellen?query={quote(item['label'])}",
                         className='btn-primary', style={'textDecoration': 'none'}),
                dcc.Link('Investment Case Report →', href=f"/investment-case?query={quote(item['label'])}",
                         className='btn-primary', style={'textDecoration': 'none'}),
            ], style={'display': 'flex', 'gap': '10px'}),
        ], className='search-result')
        return result, None, '', dash.no_update

    return empty_state('Bitte eine Adresse oder Gemeinde aus den Vorschlägen wählen.'), dash.no_update, dash.no_update, dash.no_update
