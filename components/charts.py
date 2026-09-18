import plotly.express as px
import plotly_theme  # noqa: F401 - registers the corporate default template

CHART_CONFIG = {'displayModeBar': False}

# Feste Pixelhöhe pro Kategorie für horizontale Balkendiagramme: ohne das würde Plotly die
# Balken einer fixen Gesamthöhe gleichmässig zuteilen, wodurch Charts mit wenigen Kategorien
# (z.B. 5 Baumassnahmenarten) viel dickere Balken bekommen als solche mit vielen (12 FSA-
# Kategorien) - obwohl sie nebeneinander in einem grid-2 stehen. Mit einer an die Kategorienzahl
# gekoppelten Höhe bleibt die Balkendicke konsistent; das kürzere Chart lässt dafür unten im
# (durch CSS-Grid gleich hoch gestreckten) Kartenrahmen etwas Leerraum.
BAR_ROW_PX = 32
BAR_MARGIN_PX = 90


def bar(df, x, y, orientation='h', color=None, color_map=None, labels=None, **kwargs):
    fig = px.bar(df, x=x, y=y, orientation=orientation, color=color,
                 color_discrete_map=color_map, labels=labels or {}, **kwargs)
    if orientation == 'h':
        # automargin lässt Plotly so viel Platz für die Kategorie-Labels reservieren wie
        # nötig, statt sie bei knappem Platz abzuschneiden - schrumpft dadurch auch die
        # Balkenfläche entsprechend. ticklabelstandoff schafft zusätzlich einen sichtbaren
        # Abstand zwischen den Labels und dem Balkenbeginn.
        fig.update_layout(
            yaxis={'categoryorder': 'total ascending', 'automargin': True, 'ticklabelstandoff': 10},
            height=max(220, len(df) * BAR_ROW_PX + BAR_MARGIN_PX),
        )
    return fig


def scatter(df, x, y, size=None, color=None, color_map=None, hover_data=None, labels=None, **kwargs):
    return px.scatter(df, x=x, y=y, size=size, color=color, color_discrete_map=color_map,
                       hover_data=hover_data, labels=labels or {}, **kwargs)


def donut(df, names, values, color=None, color_map=None, hole=0.55):
    fig = px.pie(df, names=names, values=values, color=color, color_discrete_map=color_map, hole=hole)
    fig.update_layout(legend=dict(orientation='h', y=-0.15))
    return fig


def line(df, x, y, color=None, labels=None, **kwargs):
    return px.line(df, x=x, y=y, color=color, labels=labels or {}, **kwargs)


def radar(df, r, theta, color, labels=None, range_r=(0, 100), height=315, **kwargs):
    """Radar/Spider-Chart (z.B. Gemeinde vs. Peer-Durchschnitt ueber mehrere Scores) als reine
    Umriss-Linien ohne Flaechenfuellung - eine gefuellte Flaeche fuer nur eine Serie (z.B. nur
    Peer-Durchschnitt, wenn die Gemeinde selbst nicht gerankt ist) sieht wie ein eigenes Scoring
    der Gemeinde aus, ist es aber nicht. Erwartet Long-Format: eine Zeile pro (Achse, Serie).
    height=315 (~30% kleiner als der Plotly-Default von 450)."""
    fig = px.line_polar(df, r=r, theta=theta, color=color, line_close=True, labels=labels or {},
                         height=height, **kwargs)
    fig.update_traces(fill='none')
    fig.update_layout(polar=dict(radialaxis=dict(range=list(range_r), gridcolor='#E5E9F0')))
    return fig


def swiss_map(df, lat='Latitude', lon='Longitude', color=None, size=None, hover_name=None,
              color_continuous_scale=None):
    fig = px.scatter_map(
        df, lat=lat, lon=lon, color=color, size=size, hover_name=hover_name,
        color_continuous_scale=color_continuous_scale, zoom=6.4, center={'lat': 46.8, 'lon': 8.2},
        map_style='carto-positron', height=520,
    )
    fig.update_layout(margin=dict(l=0, r=0, t=0, b=0))
    return fig
