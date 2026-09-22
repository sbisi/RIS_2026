from dash import html, dcc


def canton_dropdown(id_, cantons_df, placeholder='Alle Kantone', width='320px'):
    options = [{'label': f"{r.canton_code} – {r.canton_name}", 'value': r.canton_id} for r in cantons_df.itertuples()]
    return html.Div([
        html.Div('Kanton', className='filter-label'),
        dcc.Dropdown(id=id_, options=options, placeholder=placeholder, style={'width': width}),
    ])


def dropdown_filter(id_, label, options, placeholder='Alle', width='260px', value=None):
    """Generischer Label+Dropdown-Filter (z.B. Gebäudefunktion, Baumassnahmenart) -
    `options` bereits als [{'label':..., 'value':...}, ...]. `value` erlaubt eine initiale
    Vorauswahl (z.B. Deep-Link von einer anderen Seite mit ?bfs=...)."""
    return html.Div([
        html.Div(label, className='filter-label'),
        dcc.Dropdown(id=id_, options=options, placeholder=placeholder, value=value, style={'width': width}),
    ])


def range_filter(label, min_id, max_id, min_placeholder='von', max_placeholder='bis', width='90px'):
    return html.Div([
        html.Div(label, className='filter-label'),
        html.Div([
            dcc.Input(id=min_id, type='number', placeholder=min_placeholder, min=0,
                      style={'width': width, 'height': '38px', 'padding': '0 10px', 'border': '1px solid var(--border)', 'borderRadius': '6px'}),
            dcc.Input(id=max_id, type='number', placeholder=max_placeholder, min=0,
                      style={'width': width, 'height': '38px', 'padding': '0 10px', 'border': '1px solid var(--border)', 'borderRadius': '6px'}),
        ], style={'display': 'flex', 'gap': '6px'}),
    ])


def date_range_filter(label, id_):
    return html.Div([
        html.Div(label, className='filter-label'),
        dcc.DatePickerRange(id=id_, display_format='DD.MM.YYYY', clearable=True,
                             start_date_placeholder_text='von', end_date_placeholder_text='bis'),
    ])


def reset_button(id_, label='Filter zurücksetzen'):
    return html.Button(label, id=id_, n_clicks=0, className='btn-secondary', style={'alignSelf': 'flex-end'})


def filter_bar(*controls):
    return html.Div(list(controls), className='filter-bar')
