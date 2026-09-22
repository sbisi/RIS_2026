from dash import html, dcc
from components.sidebar import sidebar, pom_logo


def page_header(title, subtitle=None, actions=None, back_link=None):
    children = []
    if back_link:
        # Rueckweg fuer Deep-Links zwischen Seiten (z.B. Analyse Gemeinden -> Analyse Reglemente
        # mit vorgefiltertem bfs) - sonst kommt man nur ueber den Browser-Zurueck-Button zurueck.
        children.append(dcc.Link(f"← {back_link['label']}", href=back_link['href'], className='page-back-link'))
    children.append(html.H1(title, className='page-title'))
    if subtitle:
        children.append(html.P(subtitle, className='page-subtitle'))
    header = html.Div(children, className='page-header-text')
    if actions is not None:
        return html.Div([header, html.Div(actions, className='page-header-actions')], className='page-header')
    return html.Div([header], className='page-header')


def page_shell(active_path, title, subtitle, children, actions=None, back_link=None):
    # title=None (statt eines Strings) lässt die Titelzeile ganz weg - für Seiten wie die
    # Suche, die bewusst ohne Standard-Header auskommen (z.B. ein zentriertes, Google-artiges
    # Layout). Alle anderen Seiten übergeben weiterhin immer einen Titel, Verhalten dort
    # unverändert.
    header = page_header(title, subtitle, actions, back_link) if title else None
    return html.Div([
        sidebar(active_path),
        pom_logo(),
        html.Div([
            header,
            html.Div(children, className='page-body'),
        ], className='main-content'),
    ], className='app-shell')
