import dash
from dash import html, dcc, callback, Input, Output, State

from components.page_header import page_shell
from components.cards import section_card
from services.chatbot import ask

dash.register_page(__name__, path='/chatbot', name='Insights')

EXAMPLE_QUESTIONS = [
    'Wie viel Prozent der Gemeinden haben eine Bauzonenordnung erfasst?',
    'Welche 5 Gemeinden haben die längste durchschnittliche Bearbeitungsdauer?',
    'Wie viele Baugesuche gab es 2023 pro Kanton?',
]


def _bubble(entry):
    role = entry['role']
    text = entry['content'] if role == 'user' else entry['answer']
    bubble_class = 'chat-bubble chat-bubble-user' if role == 'user' else 'chat-bubble chat-bubble-assistant'
    children = [html.Div(text, className='chat-bubble-text')]
    if role == 'assistant' and entry.get('sql'):
        children.append(html.Details([
            html.Summary('SQL anzeigen'),
            html.Pre(entry['sql'], className='chat-sql'),
        ], className='chat-sql-details'))
    return html.Div(children, className=bubble_class)


def _api_history(history):
    """Reduziert den gespeicherten Verlauf auf das API-Nachrichtenformat (role/content) -
    fuer 'assistant' die rohe SQL-Antwort (raw_sql_response), damit ask() Anschlussfragen
    korrekt auf der zuletzt geschriebenen Abfrage aufbauen kann."""
    return [
        {'role': h['role'], 'content': h['content'] if h['role'] == 'user' else (h['raw_sql_response'] or '-- (keine Antwort)')}
        for h in history
    ]


def layout():
    return page_shell('/chatbot', 'Insights', 'Stelle Fragen in natürlicher Sprache zu den RIS-Daten.', [
        section_card('Chat', [
            html.Div([
                html.Div([
                    html.Span('Beispiele: ', className='chat-examples-label'),
                    *[
                        html.Button(q, id={'type': 'chat-example', 'index': i}, n_clicks=0, className='chat-example-chip')
                        for i, q in enumerate(EXAMPLE_QUESTIONS)
                    ],
                ], className='chat-examples'),
                html.Button('Neue Unterhaltung', id='chat-reset', n_clicks=0, className='btn-secondary'),
            ], style={'display': 'flex', 'justifyContent': 'space-between', 'alignItems': 'center', 'flexWrap': 'wrap', 'gap': '12px'}),
            html.Div(id='chat-history', className='chat-history'),
            dcc.Store(id='chat-store', data=[]),
            html.Div([
                dcc.Input(
                    id='chat-input', type='text', placeholder='z.B. Wie viele Gemeinden haben ein Reglement erfasst?',
                    value='', autoComplete='off', debounce=False,
                    style={'flex': 1, 'height': '38px', 'padding': '0 12px', 'border': '1px solid var(--border)', 'borderRadius': '6px'},
                ),
                html.Button('Fragen', id='chat-send', n_clicks=0, className='btn-primary'),
            ], style={'display': 'flex', 'gap': '12px', 'alignItems': 'center', 'marginTop': '16px'}),
            dcc.Loading(html.Div(id='chat-status'), type='circle'),
        ]),
    ])


@callback(
    Output('chat-input', 'value'),
    Input({'type': 'chat-example', 'index': dash.ALL}, 'n_clicks'),
    prevent_initial_call=True,
)
def fill_example(_clicks):
    triggered = dash.ctx.triggered_id
    if isinstance(triggered, dict) and triggered.get('type') == 'chat-example':
        return EXAMPLE_QUESTIONS[triggered['index']]
    return dash.no_update


@callback(
    Output('chat-history', 'children'), Output('chat-store', 'data'),
    Output('chat-input', 'value', allow_duplicate=True), Output('chat-status', 'children'),
    Input('chat-send', 'n_clicks'), Input('chat-input', 'n_submit'),
    State('chat-input', 'value'), State('chat-store', 'data'),
    prevent_initial_call=True,
)
def send_message(_n_clicks, _n_submit, question, history):
    question = (question or '').strip()
    if not question:
        return dash.no_update, dash.no_update, dash.no_update, ''

    history = history or []
    try:
        result = ask(question, history=_api_history(history))
        answer = result['answer']
        sql = result.get('sql')
        error = result.get('error')
        raw_sql_response = result.get('raw_sql_response', '')
    except Exception as exc:
        answer, sql, error, raw_sql_response = f'Fehler bei der Anfrage: {exc}', None, str(exc), ''

    history.append({'role': 'user', 'content': question})
    history.append({'role': 'assistant', 'answer': answer, 'sql': sql, 'raw_sql_response': raw_sql_response})

    bubbles = [_bubble(m) for m in history]
    status = html.Div('Es gab ein Problem bei der Anfrage.', className='chat-error') if error else ''
    return bubbles, history, '', status


@callback(
    Output('chat-history', 'children', allow_duplicate=True), Output('chat-store', 'data', allow_duplicate=True),
    Output('chat-status', 'children', allow_duplicate=True),
    Input('chat-reset', 'n_clicks'),
    prevent_initial_call=True,
)
def reset_chat(_n_clicks):
    return [], [], ''
