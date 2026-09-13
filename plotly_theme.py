"""Corporate Plotly-Template für die RIS Analytics Platform.
Import genügt (import plotly_theme) — der Default-Template wird global gesetzt,
damit jede px.*-Figur in den Seiten automatisch Corporate-Farben, linksbündige
Titel und einen weissen statt grauen Plot-Hintergrund erhält."""
import plotly.graph_objects as go
import plotly.io as pio
from config.settings import COLORS, PLOTLY_COLORWAY

FONT_FAMILY = 'Inter, "Segoe UI", Arial, sans-serif'

_template = go.layout.Template()
_template.layout = go.Layout(
    font=dict(family=FONT_FAMILY, size=13, color=COLORS['text']),
    title=dict(x=0, xanchor='left', font=dict(size=16, color=COLORS['navy'], family=FONT_FAMILY)),
    paper_bgcolor=COLORS['surface'],
    plot_bgcolor=COLORS['surface'],
    colorway=PLOTLY_COLORWAY,
    margin=dict(l=48, r=24, t=48, b=40),
    legend=dict(bgcolor='rgba(0,0,0,0)', font=dict(size=12)),
    xaxis=dict(gridcolor='#E5E9F0', zerolinecolor='#E5E9F0', linecolor='#D1D5DB', title=dict(font=dict(size=12, color=COLORS['gray']))),
    yaxis=dict(gridcolor='#E5E9F0', zerolinecolor='#E5E9F0', linecolor='#D1D5DB', title=dict(font=dict(size=12, color=COLORS['gray']))),
    hoverlabel=dict(bgcolor=COLORS['navy'], font=dict(color='#FFFFFF', family=FONT_FAMILY)),
)

pio.templates['ris_corporate'] = _template
pio.templates.default = 'ris_corporate'


def no_toolbar():
    return {'displayModeBar': False}
