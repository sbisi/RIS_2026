from dash import html
from components.sidebar import sidebar, pom_logo


def page_header(title, subtitle=None, actions=None):
    children = [html.H1(title, className='page-title')]
    if subtitle:
        children.append(html.P(subtitle, className='page-subtitle'))
    header = html.Div(children, className='page-header-text')
    if actions is not None:
        return html.Div([header, html.Div(actions, className='page-header-actions')], className='page-header')
    return html.Div([header], className='page-header')


def page_shell(active_path, title, subtitle, children, actions=None):
    return html.Div([
        sidebar(active_path),
        pom_logo(),
        html.Div([
            page_header(title, subtitle, actions),
            html.Div(children, className='page-body'),
        ], className='main-content'),
    ], className='app-shell')
