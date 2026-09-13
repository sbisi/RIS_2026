from dash import dash_table

FONT_STACK = 'Inter, "Segoe UI", Arial, sans-serif'


def styled_table(data, columns, page_size=25, sort=True, filter_=True, **kwargs):
    return dash_table.DataTable(
        data=data, columns=columns,
        sort_action='native' if sort else 'none',
        filter_action='native' if filter_ else 'none',
        page_size=page_size,
        style_table={'overflowX': 'auto'},
        style_cell={'fontFamily': FONT_STACK, 'fontSize': '0.85rem', 'padding': '8px 12px'},
        style_header={'backgroundColor': '#17365D', 'color': '#FFFFFF', 'fontWeight': '600', 'border': 'none'},
        style_data={'border': 'none', 'borderBottom': '1px solid #E5E9F0'},
        **kwargs,
    )
