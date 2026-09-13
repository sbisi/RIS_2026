from dash import html, dcc, clientside_callback, Output, Input
from config.settings import NAV_ITEMS

# Official pom+ plus-mark (traced vector from pom.ch favicon), recolored to their brand green,
# embedded as a data-URI (Dash's html.Img has no dangerouslySetInnerHTML equivalent).
POM_LOGO_SVG_B64 = (
    'PHN2ZyB3aWR0aD0iMjIiIGhlaWdodD0iMjIiIHZpZXdCb3g9IjAgMCA4OTYgODk2IiB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciPgo8ZyB0cmFuc2Zvcm09InRyYW5zbGF0ZSgwLDg5Nikgc2NhbGUoMC4xLC0wLjEpIiBmaWxsPSIjMUVEOTZCIiBzdHJva2U9Im5vbmUiPgo8cGF0aCBkPSJNMzQyOSA4NzcwIGMtMSAtMTQgLTIgLTc0NyAtMiAtMTYzMCBsLTIgLTE2MDUgLTE2MzMgLTMgLTE2MzIgLTIgMAotMTA1NSAwIC0xMDU1IDEwMyAtMSBjNTYgLTEgMTA2IC0xIDExMCAwIDEzIDIgNDEzIDQgNTIwIDIgMjUgMCAxNzMgMCAxOTIgMAoyMiAwIDk0MCAxIDk2NSAwIDEyIDAgMjQ0IDAgMjg4IDAgMzIgMCA0NjQgMCA0NzUgMCAyMyAwIDE3MiAwIDE4NyAwIDggMCAxMDcKLTEgMjIwIC0zIGwyMDUgLTMgMiAtMTYxNSBjMCAtODg4IDEgLTE2MjIgMiAtMTYzMCAxIC0xMyAxMjQgLTE1IDEwNDUgLTE1CjU3NSAwIDEwNDggNCAxMDUzIDggNCA1IDggNzM4IDggMTYzMCBsMCAxNjIyIDIyMCAyIGMxMjEgMSAyMzEgMyAyNDUgMyAxNCAxCjYxIDEgMTA1IDEgNDQgMCA4OSAwIDEwMCAwIDIyIDAgOTQwIDEgOTY1IDAgMTIgMCAyNDQgMCAyODggMCAzMiAwIDQ2NCAwIDQ3NQowIDIzIDAgMTcyIDAgMTkyIDAgMTEgMCAxNjMgMCAzMzggLTEgMTc1IDAgMzIyIDIgMzI2IDQgNCAzIDggNDc4IDkgMTA1NiBsMgoxMDUwIC0xNjMyIDIgLTE2MzIgMyAwIDE2MzAgLTEgMTYzMCAtMTA1MiAwIC0xMDUzIDAgLTEgLTI1eiIvPgo8L2c+Cjwvc3ZnPg=='
)

# RIS-Logo (offizielles Asset v2, bereitgestellt vom Nutzer als ris-logo-stacked-black-v2.svg).
# C2PA-Provenienz-Metadaten des Originals sind hier bewusst entfernt (irrelevant für ein
# eingebettetes UI-Icon, würde die data-URI unnötig aufblähen) - Bildinhalt unverändert.
# Der viewBox ist gegenüber dem Original (0 0 680 290) eng auf den sichtbaren Inhalt
# zugeschnitten (190 50 300 190) - Icon, Schriftzug und Tagline sitzen unverändert an
# denselben Koordinaten, nur der breite schwarze Leerraum links/rechts/oben/unten wurde
# aus dem sichtbaren Ausschnitt entfernt, damit das Logo den verfügbaren Platz in der
# Sidebar füllt statt zusätzlich verkleinert zu werden.
RIS_LOGO_FULL_SVG_B64 = (
    'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIzMDAiIGhlaWdodD0iMTkwIiB2aWV3Qm94PSIxOTAgNTAgMzAwIDE5MCIgcm9sZT0iaW1nIiBhcmlhLWxhYmVsPSJSSVMg4oCTIFJlZ3VsYXRvcnkgSW50ZWxsaWdlbmNlIFN3aXR6ZXJsYW5kIj4KPHRpdGxlPlJJUyDigJMgUmVndWxhdG9yeSBJbnRlbGxpZ2VuY2UgU3dpdHplcmxhbmQ8L3RpdGxlPgo8cmVjdCB4PSIwIiB5PSIwIiB3aWR0aD0iNjgwIiBoZWlnaHQ9IjI5MCIgZmlsbD0iIzAwMDAwMCIvPgo8ZyB0cmFuc2Zvcm09InRyYW5zbGF0ZSgzMDMsNjgpIHNjYWxlKDAuNjgpIj4KPGcgc3Ryb2tlPSIjMDBBNkE2IiBzdHJva2Utd2lkdGg9IjMuMiIgc3Ryb2tlLWxpbmVjYXA9InJvdW5kIiBmaWxsPSJub25lIj4KPGxpbmUgeDE9IjIzIiB5MT0iMjMiIHgyPSIzNiIgeTI9IjM2Ii8+CjxsaW5lIHgxPSI4NyIgeTE9IjIzIiB4Mj0iNzQiIHkyPSIzNiIvPgo8bGluZSB4MT0iMjMiIHkxPSI4NyIgeDI9IjM2IiB5Mj0iNzQiLz4KPGxpbmUgeDE9Ijg3IiB5MT0iODciIHgyPSI3NCIgeTI9Ijc0Ii8+CjwvZz4KPHJlY3QgeD0iMzgiIHk9IjAiIHdpZHRoPSIzNCIgaGVpZ2h0PSIzNCIgcng9IjUiIGZpbGw9IiNGRkZGRkYiLz4KPHJlY3QgeD0iMCIgeT0iMzgiIHdpZHRoPSIzNCIgaGVpZ2h0PSIzNCIgcng9IjUiIGZpbGw9IiNGRkZGRkYiLz4KPHJlY3QgeD0iMzgiIHk9IjM4IiB3aWR0aD0iMzQiIGhlaWdodD0iMzQiIHJ4PSI1IiBmaWxsPSIjMDBBNkE2Ii8+CjxyZWN0IHg9Ijc2IiB5PSIzOCIgd2lkdGg9IjM0IiBoZWlnaHQ9IjM0IiByeD0iNSIgZmlsbD0iI0ZGRkZGRiIvPgo8cmVjdCB4PSIzOCIgeT0iNzYiIHdpZHRoPSIzNCIgaGVpZ2h0PSIzNCIgcng9IjUiIGZpbGw9IiNGRkZGRkYiLz4KPGNpcmNsZSBjeD0iMTciIGN5PSIxNyIgcj0iNSIgZmlsbD0iIzAwQTZBNiIvPgo8Y2lyY2xlIGN4PSI5MyIgY3k9IjE3IiByPSI1IiBmaWxsPSIjMDBBNkE2Ii8+CjxjaXJjbGUgY3g9IjE3IiBjeT0iOTMiIHI9IjUiIGZpbGw9IiMwMEE2QTYiLz4KPGNpcmNsZSBjeD0iOTMiIGN5PSI5MyIgcj0iNSIgZmlsbD0iIzAwQTZBNiIvPgo8L2c+Cjx0ZXh0IHg9IjM0MCIgeT0iMTgzIiB0ZXh0LWFuY2hvcj0ibWlkZGxlIiBmaWxsPSIjRkZGRkZGIiBmb250LWZhbWlseT0iSGVsdmV0aWNhIE5ldWUsIEhlbHZldGljYSwgQXJpYWwsIHNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iMzUiIGZvbnQtd2VpZ2h0PSI2MDAiIGxldHRlci1zcGFjaW5nPSIyIj5SSVM8L3RleHQ+CjxsaW5lIHgxPSIzMTAiIHkxPSIxOTciIHgyPSIzNzAiIHkyPSIxOTciIHN0cm9rZT0iIzAwQTZBNiIgc3Ryb2tlLXdpZHRoPSIyLjUiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIvPgo8dGV4dCB4PSIzNDAiIHk9IjIxOSIgdGV4dC1hbmNob3I9Im1pZGRsZSIgZmlsbD0iI0ZGRkZGRiIgZm9udC1mYW1pbHk9IkhlbHZldGljYSBOZXVlLCBIZWx2ZXRpY2EsIEFyaWFsLCBzYW5zLXNlcmlmIiBmb250LXNpemU9IjEyLjUiIGZvbnQtd2VpZ2h0PSI1MDAiIGxldHRlci1zcGFjaW5nPSIxLjQiPlJlZ3VsYXRvcnkgSW50ZWxsaWdlbmNlIFN3aXR6ZXJsYW5kPC90ZXh0Pgo8L3N2Zz4K'
)

# Gleiche Icon-Geometrie wie oben, isoliert (ohne schwarzen Hintergrund/Text) für die
# eingeklappte Sidebar - exakt dieselben Koordinaten aus dem Original-Asset.
RIS_LOGO_ICON_SVG_B64 = (
    'PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSI0NCIgaGVpZ2h0PSI0NCIgdmlld0JveD0iMCAwIDExMCAxMTAiIHJvbGU9ImltZyIgYXJpYS1sYWJlbD0iUklTIEljb24iPgo8ZyBzdHJva2U9IiMwMEE2QTYiIHN0cm9rZS13aWR0aD0iMi42IiBzdHJva2UtbGluZWNhcD0icm91bmQiIGZpbGw9Im5vbmUiPgo8bGluZSB4MT0iMjMiIHkxPSIyMyIgeDI9IjM2IiB5Mj0iMzYiLz4KPGxpbmUgeDE9Ijg3IiB5MT0iMjMiIHgyPSI3NCIgeTI9IjM2Ii8+CjxsaW5lIHgxPSIyMyIgeTE9Ijg3IiB4Mj0iMzYiIHkyPSI3NCIvPgo8bGluZSB4MT0iODciIHkxPSI4NyIgeDI9Ijc0IiB5Mj0iNzQiLz4KPC9nPgo8cmVjdCB4PSIzOCIgeT0iMCIgd2lkdGg9IjM0IiBoZWlnaHQ9IjM0IiByeD0iNSIgZmlsbD0iI0ZGRkZGRiIvPgo8cmVjdCB4PSIwIiB5PSIzOCIgd2lkdGg9IjM0IiBoZWlnaHQ9IjM0IiByeD0iNSIgZmlsbD0iI0ZGRkZGRiIvPgo8cmVjdCB4PSIzOCIgeT0iMzgiIHdpZHRoPSIzNCIgaGVpZ2h0PSIzNCIgcng9IjUiIGZpbGw9IiMwMEE2QTYiLz4KPHJlY3QgeD0iNzYiIHk9IjM4IiB3aWR0aD0iMzQiIGhlaWdodD0iMzQiIHJ4PSI1IiBmaWxsPSIjRkZGRkZGIi8+CjxyZWN0IHg9IjM4IiB5PSI3NiIgd2lkdGg9IjM0IiBoZWlnaHQ9IjM0IiByeD0iNSIgZmlsbD0iI0ZGRkZGRiIvPgo8Y2lyY2xlIGN4PSIxNyIgY3k9IjE3IiByPSI1IiBmaWxsPSIjMDBBNkE2Ii8+CjxjaXJjbGUgY3g9IjkzIiBjeT0iMTciIHI9IjUiIGZpbGw9IiMwMEE2QTYiLz4KPGNpcmNsZSBjeD0iMTciIGN5PSI5MyIgcj0iNSIgZmlsbD0iIzAwQTZBNiIvPgo8Y2lyY2xlIGN4PSI5MyIgY3k9IjkzIiByPSI1IiBmaWxsPSIjMDBBNkE2Ii8+Cjwvc3ZnPg=='
)


def pom_logo():
    return html.Div([
        html.Span('pom', className='pom-logo-text'),
        html.Img(src=f'data:image/svg+xml;base64,{POM_LOGO_SVG_B64}', className='pom-logo-mark'),
    ], className='pom-logo')


def sidebar(active_path):
    links = []
    for item in NAV_ITEMS:
        is_active = item['href'] == active_path
        links.append(dcc.Link(
            html.Div([
                html.Span(item['icon'], className='nav-icon'),
                html.Span(item['label'], className='nav-label'),
            ], className='nav-link-inner' + (' active' if is_active else '')),
            href=item['href'], className='nav-link-wrap',
        ))
    return html.Div([
        html.Div([
            html.Img(src=f'data:image/svg+xml;base64,{RIS_LOGO_FULL_SVG_B64}', className='brand-logo-full'),
            html.Img(src=f'data:image/svg+xml;base64,{RIS_LOGO_ICON_SVG_B64}', className='brand-logo-icon'),
            html.Button('‹', id='sidebar-toggle', className='sidebar-toggle', title='Menü ein-/ausklappen'),
        ], className='brand-block'),
        html.Div(links, className='nav-links'),
        html.Div([
            html.Div('pom+ Consulting AG', className='sidebar-footer-title'),
            html.Div('HSLU Forschungskooperation', className='sidebar-footer-sub'),
        ], className='sidebar-footer'),
        html.Div(id='sidebar-toggle-sink', style={'display': 'none'}),
    ], className='sidebar')


clientside_callback(
    """
    function(n_clicks) {
        if (n_clicks) { document.body.classList.toggle('sidebar-collapsed'); }
        return '';
    }
    """,
    Output('sidebar-toggle-sink', 'title'),
    Input('sidebar-toggle', 'n_clicks'),
    prevent_initial_call=True,
)
