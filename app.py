from dash import Dash, html, page_container
from config.settings import HOST, PORT, DEBUG
import plotly_theme  # noqa: F401 - registers the corporate default template before any figure is built

app = Dash(__name__, use_pages=True, suppress_callback_exceptions=True, title='RIS Analytics Platform')

app.index_string = '''<!DOCTYPE html>
<html>
<head>
{%metas%}
<title>{%title%}</title>
{%favicon%}
{%css%}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
</head>
<body>{%app_entry%}<footer>{%config%}{%scripts%}{%renderer%}</footer></body>
</html>'''

app.layout = html.Div(page_container)
server = app.server
if __name__ == '__main__':
    # use_reloader=False: der Werkzeug-Autoreloader (debug=True) beobachtet Datei-Timestamps und
    # startet bei Aenderung neu - in diesem OneDrive-synchronisierten Ordner loest der Sync-Prozess
    # das staendig aus (Endlos-Neustart-Schleife). Manuelles Neustarten nach Codeaenderungen noetig.
    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True, use_reloader=False)
