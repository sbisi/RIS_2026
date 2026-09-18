from dash import html
from config.settings import COLORS, STATUS_COLORS


def kpi(title, value, subtitle='', accent='blue'):
    return html.Div([
        html.Div(title, className='kpi-title'),
        html.Div(value, className='kpi-value'),
        html.Div(subtitle, className='kpi-subtitle') if subtitle else None,
    ], className=f'kpi-card kpi-accent-{accent}')


def section_card(title, children, actions=None):
    if title is None and actions is None:
        return html.Div(html.Div(children), className='section-card')
    header_children = [html.H3(title, className='section-title')] if title else []
    if actions is not None:
        header_children.append(html.Div(actions, className='section-actions'))
    return html.Div([
        html.Div(header_children, className='section-header'),
        html.Div(children),
    ], className='section-card')


def status_badge(status, color=None):
    color = color or STATUS_COLORS.get(status, COLORS['gray'])
    return html.Span(status, className='status-badge', style={
        'backgroundColor': color + '1A', 'color': color, 'border': f'1px solid {color}',
    })


TRAFFIC_COLORS = {'green': COLORS['green'], 'yellow': COLORS['orange'], 'red': COLORS['red']}


def traffic_light(level, label=None):
    color = TRAFFIC_COLORS.get(level, COLORS['gray'])
    return html.Div([
        html.Span(className='traffic-dot', style={'backgroundColor': color}),
        html.Span(label, className='traffic-label') if label else None,
    ], className='traffic-light')


def score_bar(label, value, accent='blue', max_value=100):
    value = 0 if value is None or value != value else value
    pct = max(0, min(100, (value / max_value) * 100))
    return html.Div([
        html.Div([
            html.Span(label, className='score-label'),
            html.Span(f'{value:.1f}', className='score-value'),
        ], className='score-row-header'),
        html.Div(html.Div(className=f'score-fill score-accent-{accent}', style={'width': f'{pct}%'}), className='score-track'),
    ], className='score-row')


def meta_pill(label, value):
    return html.Div([
        html.Div(label, className='meta-pill-label'),
        html.Div(value, className='meta-pill-value'),
    ], className='meta-pill')


def empty_state(text='Bitte zuerst ETL ausführen: python -m etl.build_clean_model'):
    return html.Div(text, className='empty-state')
