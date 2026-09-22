import dash
from dash import html, dcc, Input, Output, callback
from services.data import (
    metrics, data_quality_summary, map_data, top_bottom_municipalities,
    regulation_vs_duration, market_vs_duration, zone_parameter_coverage, municipality_parameter_ranking,
    ranking_table, canton_options,
)
from components.page_header import page_shell
from components.cards import kpi, section_card, empty_state
from components.charts import swiss_map, bar, scatter, CHART_CONFIG
from components.filters import canton_dropdown, filter_bar
from components.tables import styled_table
from config.settings import COLORS

# Gemeinderanking ist vollständig ins Dashboard integriert (eigene Seite /ranking entfernt) -
# Spalten/Filter/Scatter unverändert aus der ehemaligen pages/ranking.py übernommen.
RANKING_COLS = [
    {'name': 'Gemeinde', 'id': 'municipality_name'},
    {'name': 'BFS', 'id': 'BFS', 'type': 'numeric'},
    {'name': 'Kanton', 'id': 'Kanton'},
    {'name': 'Peer-Rang', 'id': 'peer_rank', 'type': 'numeric', 'format': {'specifier': '.0f'}},
    {'name': 'Prozess-Score', 'id': 'process_score', 'type': 'numeric', 'format': {'specifier': '.1f'}},
    {'name': 'Regulierungs-Score', 'id': 'regulation_score', 'type': 'numeric', 'format': {'specifier': '.1f'}},
    {'name': 'Markt-Score', 'id': 'market_score', 'type': 'numeric', 'format': {'specifier': '.1f'}},
    {'name': 'Gesamt-Score', 'id': 'overall_score', 'type': 'numeric', 'format': {'specifier': '.1f'}},
]

dash.register_page(__name__, path='/dashboard', name='Dashboard')


def layout():
    try:
        m = metrics()
        q = data_quality_summary()
        quality_pct = (q['valid_documents'] / q['total_documents']) if q['total_documents'] else None
        cantons = canton_options()

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

        cov, cov_total, cov_total_gem = zone_parameter_coverage()
        fig_cov = bar(cov, x='coverage_pct', y='Parameter', labels={'coverage_pct': 'Anteil Zonen mit Wert', 'Parameter': ''})
        fig_cov.update_xaxes(tickformat='.0%')
        fig_cov.update_traces(hovertemplate='%{y}: %{x:.0%}<extra></extra>')

        # Gleiche Kategorienreihenfolge wie fig_cov (dort 'total ascending', zeigt den grössten
        # Wert oben) - cov ist nach coverage_pct absteigend sortiert, für die y-Achse (rendert
        # von unten nach oben) daher umgekehrt übergeben, damit dieselbe Parameter-Zeile in
        # beiden Charts auf derselben Höhe liegt und sich Anteil/absolute Zahl direkt vergleichen lassen.
        fig_cov_gem = bar(cov, x='n_municipalities', y='Parameter', labels={'n_municipalities': 'Anzahl Gemeinden', 'Parameter': ''})
        fig_cov_gem.update_traces(marker_color=COLORS['blue'], hovertemplate='%{y}: %{x} Gemeinden<extra></extra>')
        fig_cov_gem.update_layout(yaxis={'categoryorder': 'array', 'categoryarray': cov['Parameter'].tolist()[::-1]})

        rank = municipality_parameter_ranking(15)
        fig_rank = bar(rank, x='n_parameters', y='municipality_name', hover_data=['Kanton'],
                       labels={'n_parameters': 'Anzahl Parameter-Typen (von 28)', 'municipality_name': ''})
        fig_rank.update_traces(marker_color='#2F75B5', hovertemplate='%{y} (%{customdata[0]}): %{x} Parameter<extra></extra>')

        return page_shell('/dashboard', 'Dashboard', 'Executive Reporting über Baugesuche, Gemeinderanking und Regulierungsqualität.', [
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
            section_card('Gemeinderanking', [
                filter_bar(canton_dropdown('ranking-canton', cantons)),
                dcc.Graph(id='ranking-scatter', config=CHART_CONFIG, style={'marginTop': '18px'}),
                html.Div(id='ranking-table-wrap', style={'marginTop': '18px'}),
            ]),
            section_card('Zonenparameter-Abdeckung (Schweiz)', [
                html.P(
                    f"Anteil der {cov_total:,} in den Baugesuchsdaten vorkommenden Gemeinde/Zone-Kombinationen, "
                    "für die im Reglement mindestens ein Wert (Standard, Bonus oder Arealüberbauung) je Parameter-Typ erfasst ist.",
                    className='kpi-subtitle', style={'marginBottom': '14px'},
                ),
                dcc.Graph(figure=fig_cov, config=CHART_CONFIG),
                html.P(
                    f"Anzahl der {cov_total_gem:,} in den Baugesuchsdaten vorkommenden Gemeinden, in denen mindestens eine Zone "
                    "einen Wert für den jeweiligen Parameter-Typ hat (eine Gemeinde hat meist mehrere Zonen, daher nicht 1:1 proportional zum Anteil oben).",
                    className='kpi-subtitle', style={'margin': '20px 0 14px 0'},
                ),
                dcc.Graph(figure=fig_cov_gem, config=CHART_CONFIG),
            ]),
            section_card('Rangliste Gemeinden – meiste erfasste Zonenparameter', [
                html.P(
                    'Top 15 Gemeinden nach Anzahl unterschiedlicher Parameter-Typen (von 28), für die mindestens eine ihrer '
                    'Zonen einen Wert hat – ein Parameter zählt pro Gemeinde nur einmal, auch wenn er in mehreren Zonen vorkommt.',
                    className='kpi-subtitle', style={'marginBottom': '14px'},
                ),
                dcc.Graph(figure=fig_rank, config=CHART_CONFIG),
            ]),
        ])
    except Exception as e:
        return page_shell('/dashboard', 'Dashboard', '', empty_state(str(e)))


@callback(Output('ranking-scatter', 'figure'), Output('ranking-table-wrap', 'children'), Input('ranking-canton', 'value'))
def update_ranking(canton_id):
    df = ranking_table(canton_id)
    if df.empty:
        return {}, empty_state()
    plot_df = df.dropna(subset=['regulation_score', 'process_score', 'overall_score'])
    fig = scatter(
        plot_df, x='regulation_score', y='process_score', size='overall_score', color='overall_score',
        hover_data=['municipality_name', 'BFS', 'Kanton'],
        labels={'regulation_score': 'Regulierungs-Score', 'process_score': 'Prozess-Score'},
        color_continuous_scale=['#C00000', '#ED7D31', '#70AD47'],
    )
    return fig, styled_table(df.to_dict('records'), RANKING_COLS)
