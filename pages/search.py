import re
from urllib.parse import quote

import dash
import requests
from dash import html, dcc, callback, Input, Output, State, ALL, ctx

from services.data import search_municipalities
from components.page_header import page_shell
from components.cards import empty_state

dash.register_page(__name__, path='/', name='Suche')

ADDRESS_SEARCH_URL = 'https://lawmanager.app.levell.ch/api/geoadmin/addressSearch'
MIN_CHARS = 3


def clean_html(text):
    """Entfernt HTML-Tags (z.B. <b>PLZ Ort</b>) aus dem API-Label."""
    return re.sub(r'<.*?>', '', text or '')


def layout():
    # title=None entfernt die Standard-Titelzeile - die Suche bekommt bewusst ein zentriertes,
    # Google-artiges Layout statt des sonst überall gleichen Seitenkopfs.
    return page_shell('/', None, None, [
        html.Div([
            html.Div([
                dcc.Input(
                    id='search-input', type='text',
                    placeholder='Gemeinde oder Adresse eingeben (mind. 3 Zeichen)',
                    value='', autoComplete='off',
                    style={
                        'flex': 1, 'height': '54px', 'padding': '0 22px', 'fontSize': '1.02rem',
                        'border': '1px solid var(--border)', 'borderRadius': '27px',
                        'boxShadow': '0 2px 10px rgba(23,54,93,0.08)', 'outline': 'none',
                    },
                ),
                html.Button('Suchen', id='search-button', n_clicks=0, className='btn-primary',
                            style={'height': '54px', 'padding': '0 30px', 'borderRadius': '27px', 'fontSize': '0.95rem'}),
            ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'center', 'width': '100%', 'maxWidth': '700px'}),

            html.Div(id='search-suggestions', style={'width': '100%', 'maxWidth': '700px', 'marginTop': '10px'}),
            html.Div(id='search-output', style={'width': '100%', 'maxWidth': '700px', 'marginTop': '16px'}),

            dcc.Store(id='suggestions-data', data=[]),
            # storage_type='session' merkt sich die zuletzt gewählte Adresse im Browser
            # (sessionStorage) über Seitenwechsel hinweg - damit auch ein direkter Klick auf den
            # Menüpunkt "Analyse Investitionspotenzial" (statt über den Link im Suchergebnis) die zuletzt
            # gesuchte Adresse übernimmt. Gleiche id in pages/investment_case.py definiert.
            dcc.Store(id='last-address-store', storage_type='session'),
            # storage_type='local': bleibt auch über Browser-Neustarts hinweg erhalten (anders
            # als last-address-store oben, das bewusst nur pro Session gilt) - die letzten 5
            # Suchen sollen wie ein normaler Suchverlauf dauerhaft verfügbar sein.
            dcc.Store(id='search-history-store', storage_type='local', data=[]),
            # Wird von assets/search_focus.js bei jedem Fokus-Ereignis auf #search-input über
            # window.dash_clientside.set_props aktualisiert (dcc.Input hat kein eigenes
            # Fokus-Ereignis) - Trigger dafür, dass "Letzte Suchen" nur bei echtem Klick ins
            # Feld erscheint, nicht schon beim Laden der Seite.
            dcc.Store(id='search-focus-store', data=0),
            dcc.Location(id='search-redirect', refresh=True),
        ], className='search-centered'),
    ])


def _suggestion_items(suggestions):
    return [
        html.Div(s['label'], id={'type': 'suggestion-item', 'index': i},
                 n_clicks=0, className='suggestion-item' + (' suggestion-item-muni' if s['kind'] == 'municipality' else ''))
        for i, s in enumerate(suggestions)
    ]


@callback(
    Output('search-suggestions', 'children'), Output('suggestions-data', 'data'),
    Input('search-input', 'value'), Input('search-focus-store', 'data'),
    State('search-history-store', 'data'),
)
def suggest_locations(search_value, focus_ts, history):
    # 'Letzte Suchen' nur zeigen, wenn dieser Aufruf tatsächlich durch das Fokus-Ereignis
    # ausgelöst wurde (assets/search_focus.js) - nicht beim initialen Laden der Seite und nicht,
    # wenn das Feld durch Tippen/Löschen leer wird (ctx.triggered_id ist beim allerersten
    # automatischen Aufruf None, taucht dort also nie als 'search-focus-store' auf).
    if ctx.triggered_id == 'search-focus-store':
        if not search_value and history:
            return html.Div([
                html.Div('Letzte Suchen', className='kpi-subtitle', style={'padding': '8px 14px 4px 14px'}),
                html.Div(_suggestion_items(history), className='suggestion-list'),
            ]), history
        return dash.no_update, dash.no_update

    if not search_value or len(search_value) < MIN_CHARS:
        return None, []

    muni_df = search_municipalities(search_value, limit=5)
    municipalities = [
        {'kind': 'municipality', 'label': f"🏛 {r.municipality_name} ({r.Kanton}) – Analyse Gemeinden", 'bfs': int(r.BFS)}
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

    return html.Div(_suggestion_items(suggestions), className='suggestion-list'), suggestions


def _push_history(history, item):
    """Neuestes zuoberst, Duplikate (gleiches Label) entfernt, auf 5 Einträge gedeckelt."""
    history = [h for h in (history or []) if h.get('label') != item.get('label')]
    history.insert(0, item)
    return history[:5]


@callback(
    Output('search-output', 'children'), Output('search-suggestions', 'children', allow_duplicate=True),
    Output('search-input', 'value'), Output('search-redirect', 'href'),
    Output('last-address-store', 'data'), Output('search-history-store', 'data'),
    Input({'type': 'suggestion-item', 'index': ALL}, 'n_clicks'), Input('search-button', 'n_clicks'),
    State('suggestions-data', 'data'), State('search-input', 'value'), State('search-history-store', 'data'),
    prevent_initial_call=True,
)
def select_or_search(item_clicks, button_clicks, suggestions, current_value, history):
    triggered = ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get('type') == 'suggestion-item':
        idx = triggered['index']
        if not any(item_clicks) or idx >= len(suggestions):
            return dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update
        item = suggestions[idx]
        new_history = _push_history(history, item)

        if item['kind'] == 'municipality':
            return dash.no_update, dash.no_update, dash.no_update, f"/gemeinde?bfs={item['bfs']}", dash.no_update, new_history

        result = html.Div([
            html.Div([
                html.Div(item['label'], className='search-result-label'),
                html.Div(f"Koordinaten: {item['lat']}, {item['lon']}", className='search-result-meta'),
            ]),
            html.Div([
                dcc.Link('Parzelle & Zone anzeigen →', href=f"/suche/parzellen?query={quote(item['label'])}",
                         className='btn-primary', style={'textDecoration': 'none'}),
                dcc.Link('Analyse Investitionspotenzial →', href=f"/investment-case?query={quote(item['label'])}",
                         className='btn-primary', style={'textDecoration': 'none'}),
            ], style={'display': 'flex', 'gap': '10px'}),
        ], className='search-result')
        # Adresse im sessionStorage merken, damit ein späterer Klick auf den Menüpunkt
        # "Analyse Investitionspotenzial" (ohne den Link hier zu nutzen) dieselbe Adresse übernimmt.
        return result, None, '', dash.no_update, item['label'], new_history

    return (empty_state('Bitte eine Adresse oder Gemeinde aus den Vorschlägen wählen.'),
            dash.no_update, dash.no_update, dash.no_update, dash.no_update, dash.no_update)
