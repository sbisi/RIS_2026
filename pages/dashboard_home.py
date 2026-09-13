import dash
from dash import html, dcc
from services.data import metrics, data_quality_summary, map_data, top_bottom_municipalities, regulation_vs_duration, market_vs_duration
from components.page_header import page_shell
from components.cards import kpi, section_card, empty_state
from components.charts import swiss_map, bar, scatter, CHART_CONFIG

dash.register_page(__name__, path='/', name='Dashboard')


def layout():
    try:
        m = metrics()
        q = data_quality_summary()
        quality_pct = (q['valid_documents'] / q['total_documents']) if q['total_documents'] else None

        kpis = html.Div([
            kpi('Gemeinden', f"{int(m['municipalities']):,}", accent='navy'),
            kpi('Projekte', f"{int(m['projects']):,}", accent='blue'),
            kpi('Median Dauer Baubewilligung', f"{m['median']:.0f} Tage" if m['median'] == m['median'] else '–', accent='teal'),
            kpi('Baubewilligung > 180 Tage', f"{m['over180']:.1%}" if m['over180'] == m['over180'] else '–', accent='orange'),
            kpi('Baubewilligung > 365 Tage', f"{m['over365']:.1%}" if m['over365'] == m['over365'] else '–', accent='red'),
            kpi('Reglementsqualität', f"{quality_pct:.0%}" if quality_pct == quality_pct else '–', f"{int(q['total_documents']):,} geprüft", accent='green'),
        ], className='grid-6')

        md = map_data().dropna(subset=['overall_score', 'median_duration'])
        fig_map = swiss_map(md, color='overall_score', size='median_duration', hover_name='municipality_name',
                             color_continuous_scale=['#C00000', '#ED7D31', '#70AD47']) if len(md) else {}

        top, bottom = top_bottom_municipalities(10)
        fig_top = bar(top, x='overall_score', y='municipality_name', color_map=None,
                      labels={'overall_score': 'Gesamt-Score', 'municipality_name': ''})
        fig_top.update_traces(marker_color='#70AD47')
        fig_bottom = bar(bottom, x='overall_score', y='municipality_name',
                         labels={'overall_score': 'Gesamt-Score', 'municipality_name': ''})
        fig_bottom.update_traces(marker_color='#C00000')

        # Kein color='Kanton': 26 Kategorien lassen sich mit keiner Palette paarweise
        # unterscheidbar einfärben (dataviz-Validator: all-pairs-Scatter deckelt bei 3
        # Slots). Kanton bleibt über den Hover-Tooltip abrufbar, Farbe entfällt als
        # Identitätsträger zugunsten eines einheitlichen Markentons.
        reg = regulation_vs_duration().dropna(subset=['regulation_score', 'median_duration', 'n_projects'])
        fig_reg = scatter(reg, x='regulation_score', y='median_duration', size='n_projects',
                           hover_data=['municipality_name', 'Kanton'],
                           labels={'regulation_score': 'Regulierungs-Score', 'median_duration': 'Median Dauer (Tage)'})
        mkt = market_vs_duration().dropna(subset=['market_score', 'median_duration', 'n_projects'])
        fig_mkt = scatter(mkt, x='market_score', y='median_duration', size='n_projects',
                           hover_data=['municipality_name', 'Kanton'],
                           labels={'market_score': 'Markt-Score', 'median_duration': 'Median Dauer (Tage)'})

        return page_shell('/', 'Dashboard', 'Executive Reporting über Baugesuche, Gemeinderanking und Regulierungsqualität.', [
            kpis,
            html.Div([
                section_card('Schweizer Karte – Gesamt-Score', dcc.Graph(figure=fig_map, config=CHART_CONFIG)),
                html.Div([
                    section_card('Top 10 Gemeinden', dcc.Graph(figure=fig_top, config=CHART_CONFIG)),
                    section_card('Bottom 10 Gemeinden', dcc.Graph(figure=fig_bottom, config=CHART_CONFIG)),
                ], style={'display': 'flex', 'flexDirection': 'column', 'gap': '28px'}),
            ], className='grid-2-1'),
            html.Div([
                section_card('Regulierung vs. Bewilligungsdauer', dcc.Graph(figure=fig_reg, config=CHART_CONFIG)),
                section_card('Markt vs. Bewilligungsdauer', dcc.Graph(figure=fig_mkt, config=CHART_CONFIG)),
            ], className='grid-2'),
        ])
    except Exception as e:
        return page_shell('/', 'Dashboard', '', empty_state(str(e)))
