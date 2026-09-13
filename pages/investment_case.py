"""Acquisition Decision Sheet: statistikbasierte Einschätzung von Bewilligungsdauer und
-risiko für eine per Suche eingegebene Adresse, berechnet aus echten RIS-Baugesuchs- und
Gemeinde-Rankingdaten. Investitionsvolumen und der Carry-Satz sind die einzigen nicht aus
der Datenbank stammenden Annahmen und werden dafür transparent ausgewiesen."""
import math
from urllib.parse import unquote

import dash
from dash import html, dcc, Input, Output, State, callback

from services.data import municipality_summary, permit_duration_benchmark, national_reference
from services.geo import get_coordinates, get_parcel_data, get_zone_data, clean_address, format_legal_status
from components.page_header import page_shell
from components.cards import section_card, empty_state

dash.register_page(__name__, path='/investment-case', name='Investment Case')

NA = '–'
# Einzige nicht aus der Datenbank stammende Annahme: angenommener Finanzierungs-/Carry-Satz
# p.a. auf das Investitionsvolumen, zur Umrechnung von Verzögerungsmonaten in CHF-Exposure.
CARRY_RATE_ANNUAL = 0.035


def _clean(v):
    if v is None:
        return None
    if hasattr(v, 'item'):
        v = v.item()
    return None if isinstance(v, float) and math.isnan(v) else v


def _months(days):
    return days / 30.44 if isinstance(days, (int, float)) else None


def _fmt_m(months, decimals=1, suffix=' m'):
    return f'{months:.{decimals}f}{suffix}' if months is not None else NA


def _fmt_pct(x):
    return f'{x:.0%}' if isinstance(x, (int, float)) else NA


def _fmt_chf(value):
    if value is None:
        return NA
    if abs(value) >= 1_000_000:
        return f'CHF {value / 1_000_000:.2f}m'
    return f'CHF {value / 1_000:.0f}k'


def _chf_cost(extra_months, investment_mio):
    if extra_months is None or not isinstance(investment_mio, (int, float)):
        return None
    return extra_months * (investment_mio * 1_000_000 * CARRY_RATE_ANNUAL / 12)


def _first_available(*values):
    for v in values:
        if v is not None:
            return v
    return None


def _verdict_col(value, caption):
    return html.Div([
        html.Div(value, className='decision-verdict-value'),
        html.Div(caption, className='decision-verdict-caption'),
    ], className='decision-verdict-col')


def _tile(label, value, caption):
    return html.Div([
        html.Div(label, className='decision-tile-label'),
        html.Div(value, className='decision-tile-value'),
        html.Div(caption, className='decision-tile-caption'),
    ], className='decision-tile')


def _evidence_table(bench):
    def m(level, key):
        return _fmt_m(_months(bench.get(level, {}).get(key)))

    def n(level):
        return str(bench.get(level, {}).get('n') or 0)

    rows = [
        ('Median', m('national', 'p50'), m('municipality', 'p50'), m('canton', 'p50')),
        ('P75', m('national', 'p75'), m('municipality', 'p75'), m('canton', 'p75')),
        ('P90', m('national', 'p90'), m('municipality', 'p90'), m('canton', 'p90')),
        ('Cases', n('national'), n('municipality'), n('canton')),
    ]
    return html.Table([
        html.Thead(html.Tr([
            html.Th(''), html.Th('Comparable permits'), html.Th('Municipality'), html.Th('Canton'),
        ])),
        html.Tbody([
            html.Tr([html.Td(label, className='decision-evidence-rowlabel'), html.Td(a), html.Td(b), html.Td(c)])
            for label, a, b, c in rows
        ]),
    ], className='decision-evidence-table')


def _risk_list(title, items, accent):
    return html.Div([
        html.Div(title, className=f'decision-risk-title decision-risk-title--{accent}'),
        html.Div([html.Div(item, className='decision-risk-item') for item in (items or ['– keine Auffälligkeiten erfasst'])]),
    ], className='decision-risk-col')


def layout(query=None, **kwargs):
    # Dash übergibt jeden URL-Query-Parameter direkt als Keyword-Argument an layout() -
    # zuverlässiger als der Umweg über eine client-seitige dcc.Location, deren 'search'-Prop
    # bei einer SPA-Navigation (dcc.Link von der Suche her) nicht immer rechtzeitig gesetzt
    # war und dadurch die Adresse nicht übernahm. Der initiale Wert des Adressfelds löst den
    # 'lookup_address'-Callback beim ersten Rendern der Seite ganz natürlich aus (Dash führt
    # jeden Callback einmal mit den initialen Prop-Werten aus).
    initial_address = clean_address(unquote(query)) if query else ''
    return page_shell(
        '/investment-case', 'Investment Case',
        'Statistikbasierte Einschätzung von Bewilligungsdauer und -risiko für einen Akquisitionsentscheid, '
        'berechnet aus den realen RIS-Baugesuchs- und Gemeinde-Rankingdaten für die gesuchte Adresse.',
        [
            section_card('Adresse', [
                html.Div([
                    dcc.Input(
                        id='ic-address-input', type='text', placeholder='Adresse eingeben (mind. Strasse, Ort)',
                        value=initial_address, autoComplete='off',
                        style={'flex': 1, 'height': '38px', 'padding': '0 12px', 'border': '1px solid var(--border)', 'borderRadius': '6px'},
                    ),
                    html.Button('Suchen', id='ic-search-button', n_clicks=0, className='btn-primary'),
                ], style={'display': 'flex', 'gap': '10px'}),

                # Investitionsvolumen/Bewilligungs-Annahme: nicht mehr sichtbar/editierbar in der
                # UI, aber als Komponenten erhalten (nur ausgeblendet) - render_sheet() braucht
                # sie weiterhin als Input, feste Annahmen: 10 Mio. CHF / 6 Monate.
                html.Div([
                    dcc.Input(id='ic-investment-input', type='number', value=10),
                    dcc.Input(id='ic-underwriting-input', type='number', value=6),
                ], style={'display': 'none'}),
            ]),
            dcc.Store(id='ic-data-store', data={}),
            html.Div(id='ic-sheet-container'),
        ],
    )


@callback(
    Output('ic-data-store', 'data'),
    Input('ic-search-button', 'n_clicks'), Input('ic-address-input', 'n_submit'),
    State('ic-address-input', 'value'),
)
def lookup_address(n_clicks, n_submit, address):
    if not address:
        return dash.no_update
    address = clean_address(address)
    coords = get_coordinates(address)
    if not coords:
        return {'error': f'Adresse „{address}“ konnte nicht geokodiert werden.'}
    lon, lat = coords
    parcel_id, parcel_name, e, n, area = get_parcel_data(lon, lat)
    if not parcel_id:
        return {'error': 'Keine Parzelle an dieser Adresse gefunden (amtliche Vermessung ohne Treffer).'}
    zone_info = get_zone_data(e, n)
    bfs = zone_info.get('bfs')
    if not bfs:
        return {'error': 'Keine Gemeinde (BFS-Nummer) für diese Parzelle ermittelbar.'}
    summary = municipality_summary(bfs)
    if summary.empty:
        return {'error': f'Keine RIS-Kennzahlen für diese Gemeinde (BFS {bfs}) im Datenmodell vorhanden.'}
    s = summary.iloc[0]
    canton = _clean(s.Kanton) or zone_info.get('canton')
    benchmark = permit_duration_benchmark(bfs=bfs, canton_code=canton)
    overlays = (zone_info.get('overlays') or [])[:3]

    return {
        'address': address, 'parcel_name': parcel_name, 'area': _clean(area),
        'zone_label': zone_info.get('zone_kommunal') or zone_info.get('zone_detail') or zone_info.get('zone_category'),
        'legal_status': zone_info.get('legal_status'), 'overlays': [ov.get('label') for ov in overlays],
        'bfs': int(bfs), 'municipality_name': _clean(s.municipality_name), 'canton': canton,
        'median_duration': _clean(s.median_duration), 'share_gt_180': _clean(s.share_gt_180),
        'share_gt_365': _clean(s.share_gt_365), 'peer_rank': _clean(s.peer_rank),
        'peer_group_size': _clean(s.peer_group_size), 'overall_score': _clean(s.overall_score),
        'regulation_score': _clean(s.regulation_score), 'benchmark': benchmark,
        'national_ref': national_reference(),
    }


@callback(
    Output('ic-sheet-container', 'children'),
    Input('ic-data-store', 'data'), Input('ic-investment-input', 'value'), Input('ic-underwriting-input', 'value'),
)
def render_sheet(data, investment_mio, underwriting_months):
    if not data:
        return empty_state('Adresse eingeben und suchen, um den Investment Case mit RIS-Daten zu berechnen.')
    if data.get('error'):
        return empty_state(data['error'])
    return build_decision_sheet(data, investment_mio, underwriting_months)


def build_decision_sheet(data, investment_mio, underwriting_months):
    bench = data.get('benchmark') or {}
    muni_b, canton_b, national_b = bench.get('municipality', {}), bench.get('canton', {}), bench.get('national', {})

    # Erwartete Dauer: Gemeinde-Median bevorzugt, sonst Kanton, sonst national - je nach
    # Datenlage. median_duration aus fact_municipality (Ranking-Sheet) deckt sich i.d.R. mit
    # muni_b['p50'] (fact_project), dient hier als robuster erster Fallback.
    median_days = _first_available(data.get('median_duration'), muni_b.get('p50'), canton_b.get('p50'), national_b.get('p50'))
    p90_days = _first_available(muni_b.get('p90'), canton_b.get('p90'), national_b.get('p90'))
    p95_days = _first_available(muni_b.get('p95'), canton_b.get('p95'), national_b.get('p95'))
    expected_months, p90_months, p95_months = _months(median_days), _months(p90_days), _months(p95_days)

    peer_rank, peer_group_size = data.get('peer_rank'), data.get('peer_group_size')
    if peer_rank is not None and peer_group_size and peer_group_size > 1:
        risk_score = round((peer_rank - 1) / (peer_group_size - 1) * 100)
    else:
        risk_score = None
    risk_label = NA if risk_score is None else ('tief' if risk_score < 34 else 'moderat' if risk_score < 67 else 'hoch')
    verdict = 'UNBEKANNT' if risk_score is None else ('REVIEW' if risk_score >= 67 else 'PROCEED')

    downside_delta = None if (p90_months is None or expected_months is None) else p90_months - expected_months
    delay_exposure = _chf_cost(downside_delta, investment_mio)

    verdict_caption = (
        f'Underwrite {expected_months:.0f} Monate; Regulierungspuffer von {_fmt_chf(delay_exposure)} einplanen.'
        if verdict == 'PROCEED' and expected_months is not None
        else 'Vertiefte Prüfung empfehlenswert; überdurchschnittliches Timing-Risiko in dieser Gemeinde.'
        if verdict == 'REVIEW'
        else 'Keine ausreichende Datenbasis für eine Beurteil des Investment Case.'
    )

    current_months = underwriting_months if isinstance(underwriting_months, (int, float)) else None
    delta_base = None if (current_months is None or expected_months is None) else expected_months - current_months
    delta_downside = None if (current_months is None or p90_months is None) else p90_months - current_months
    chf_base = _chf_cost(delta_base, investment_mio)
    chf_downside = _chf_cost(delta_downside, investment_mio)

    subline_parts = [data['address']]
    if data.get('parcel_name'):
        subline_parts.append(f"Parzelle {data['parcel_name']}")
    if data.get('zone_label'):
        subline_parts.append(f"Zone: {data['zone_label']}")
    subline_parts.append(f"Investitionsvolumen (Annahme): CHF {investment_mio or 0:g} Mio.")

    lower_risk, higher_risk = [], []
    if data.get('legal_status') == 'inKraft':
        lower_risk.append('– Nutzungsplanung rechtskräftig (kein Änderungsverfahren hängig)')
    elif data.get('legal_status'):
        higher_risk.append(f"+ Nutzungsplanung in Änderung ({format_legal_status(data['legal_status'])})")
    if not data.get('overlays'):
        lower_risk.append('– Keine überlagernden Nutzungsplaninhalte auf der Parzelle erfasst')
    else:
        for ov in data['overlays']:
            higher_risk.append(f'+ Überlagernder Nutzungsplaninhalt: {ov}')
    nat_ref = data.get('national_ref') or {}
    if isinstance(data.get('share_gt_365'), (int, float)) and isinstance(nat_ref.get('share_gt_365'), (int, float)):
        if data['share_gt_365'] < nat_ref['share_gt_365']:
            lower_risk.append('– Gemeinde: unterdurchschnittlicher Anteil Verfahren > 1 Jahr')
        else:
            higher_risk.append('+ Gemeinde: überdurchschnittlicher Anteil Verfahren > 1 Jahr')
    if isinstance(data.get('regulation_score'), (int, float)) and isinstance(nat_ref.get('regulation_score'), (int, float)):
        if data['regulation_score'] >= nat_ref['regulation_score']:
            lower_risk.append('– Reglement vergleichsweise unkomplex (Regulierungs-Score über nat. Median)')
        else:
            higher_risk.append('+ Reglement vergleichsweise komplex (Regulierungs-Score unter nat. Median)')

    return html.Div([
        # html.Div('RIS / Investment Case – Real Data', className='decision-header-overline'),
        # html.H2('Acquisition Decision Sheet', className='decision-header-title'),
        # html.Div(f"{data.get('municipality_name', NA)} ({data.get('canton', NA)})   |   " + '   |   '.join(subline_parts),
        #          className='decision-subline'),

        html.Div([
            html.Div('RIS Investment Case Beurteilung', className='decision-label'),
            html.Div([
                _verdict_col(verdict, verdict_caption),
                _verdict_col(_fmt_m(expected_months, 1, ' MONATE').upper(), 'Erwartete Bewilligungsdauer'),
                _verdict_col(f'{risk_score} / 100' if risk_score is not None else NA,
                             f'Bewilligungsrisiko – {risk_label.upper()}' +
                             (f' (Peer-Rang {peer_rank:.0f}/{peer_group_size:.0f})' if peer_rank is not None and peer_group_size else '')),
            ], className='decision-verdict-row'),
        ], className='decision-verdict-box'),

        html.Div([
            _tile('Parzellenfläche', f"{data['area']:.0f} m²" if data.get('area') else NA, 'amtliche Vermessung'),
            _tile('Downside', f'+{downside_delta:.1f} Monate' if downside_delta is not None else NA, 'P90 vs. Median'),
            _tile('Verfahren > 1 Jahr', _fmt_pct(data.get('share_gt_365')), 'Anteil, Gemeinde (real erfasst)'),
            _tile('Delay Exposure', _fmt_chf(delay_exposure), f'bei CHF {investment_mio or 0:g} Mio., {CARRY_RATE_ANNUAL:.1%} p.a. Annahme'),
        ], className='decision-tile-row'),

        html.Div([
            html.Div('Evidence (Bearbeitungsdauer in Monaten)', className='decision-label'),
            _evidence_table(bench),
        ], className='decision-block'),

        html.Div([
            _risk_list('Lower Risk', lower_risk, 'good'),
            _risk_list('Higher Risk', higher_risk, 'bad'),
        ], className='decision-risk-grid'),

        html.Div([
            html.Div('Investment Impact', className='decision-label'),
            html.Div([
                _tile('Current Underwriting', f'{current_months:.0f} m' if current_months is not None else NA, 'current assumption'),
                _tile('RIS Base Case', _fmt_m(expected_months),
                      f'+{delta_base:.1f} m / {_fmt_chf(chf_base)}' if delta_base is not None else NA),
                _tile('RIS Downside', _fmt_m(p90_months),
                      f'+{delta_downside:.1f} m / {_fmt_chf(chf_downside)}' if delta_downside is not None else NA),
                _tile('Severe / Appeal', _fmt_m(p95_months, 0, '+ m'), 'tail risk (P95 Kanton/national)'),
            ], className='decision-tile-row'),
        ], className='decision-block'),

        html.Div([
            html.Div('RIS Empfehlung', className='decision-recommendation-title'),
            html.P(verdict_caption, className='decision-recommendation-lead'),
            html.P(
                f"Die Bewilligungsdauer-Schätzung basiert auf {muni_b.get('n') or 0} Baugesuchen der Gemeinde "
                f"{data.get('municipality_name', NA)}" +
                (f", ergänzt durch {canton_b.get('n') or 0} Fälle im Kanton {data.get('canton', NA)}" if canton_b.get('n') else '') +
                f" und {national_b.get('n') or 0} Fällen national als breite Vergleichsbasis. "
                'Investitionsvolumen und Carry-Satz sind Annahmen des Nutzers, alle übrigen Werte stammen aus den RIS-Baugesuchs- und Rankingdaten.',
                className='decision-recommendation-body',
            ),
        ], className='decision-recommendation-box'),

        html.Div(
            'Berechnung auf Basis der RIS-Baugesuchs- und Gemeinde-Rankingdaten (siehe docs/data_model.md). '
            'Investitionsvolumen, aktuelle Bewilligungs-Annahme und Carry-Satz sind Annahmen und keine Rechts- '
            'oder Anlageberatung; keine Garantie für einen tatsächlichen Bewilligungsentscheid.',
            className='decision-disclaimer',
        ),
    ], className='decision-sheet')
