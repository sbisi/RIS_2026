"""Parzellen- und Zonendetails zu einer Adresse: Geokodierung, amtliche Vermessung,
Nutzungsplanung (geodienste.ch) mit Fallback auf die eidg. Bauzonen, eingebettete
Katasterkarte (map.geo.admin.ch)."""
import re

import dash
from dash import dcc, html, Input, Output, State, callback
from urllib.parse import unquote

from database.db import query_df
from services.data import municipality_summary, municipality_documents, municipality_sustainability
from services.geo import get_coordinates, get_parcel_data, get_zone_data, clean_address, format_legal_status
from components.page_header import page_shell
from components.cards import section_card, kpi
from components.tables import styled_table
from config.settings import COLORS

dash.register_page(__name__, path='/suche/parzellen', name='Parzellen')


def info_row(label, value):
    return html.Div([
        html.Div(label, className='score-label'),
        html.Div(value, style={'color': 'var(--text-primary)', 'fontSize': '0.92rem', 'marginTop': '2px', 'wordBreak': 'break-word'}),
    ], style={'marginBottom': '14px'})


# Die 27 Zonenparameter-Typen aus data_hslu260312.csv, wie in
# etl/build_zone_parameters.py extrahiert (Anzeigename -> Spalten-Slug-Präfix).
ZONE_PARAM_TYPES = [
    ('Abstand Strasse', 'abstand_strasse'), ('Ausnützungsziffer', 'ausnuetzungsziffer'),
    ('Bachabstand', 'bachabstand'), ('Baumassenziffer', 'baumassenziffer'),
    ('Bonus Ausnützung', 'bonus_ausnuetzung'), ('Fassadenhöhe', 'fassadenhoehe'),
    ('Fassadenhöhe (giebelseitig)', 'fassadenhoehe_giebelseitig'),
    ('Fassadenhöhe (traufseitig)', 'fassadenhoehe_traufseitig'), ('Firsthöhe', 'firsthoehe'),
    ('Freiflächenziffer', 'freiflaechenziffer'), ('Fussgängerwege-Abstand', 'fussgaengerwege_abstand'),
    ('Gebäudeabstand', 'gebaeudeabstand'), ('Gebäudebreite', 'gebaeudebreite'),
    ('Gebäudehöhe', 'gebaeudehoehe'), ('Gebäudelänge', 'gebaeudelaenge'),
    ('Gesamtausnützung', 'gesamtausnuetzung'), ('Geschossflächenziffer', 'geschossflaechenziffer'),
    ('Geschosse', 'geschosse'), ('Gestaltungsplanbonus', 'gestaltungsplanbonus'),
    ('grosser Grenzabstand', 'grosser_grenzabstand'), ('kleiner Grenzabstand', 'kleiner_grenzabstand'),
    ('Grenzabstand', 'grenzabstand'), ('Mehrhöhenzuschlag', 'mehrhoehenzuschlag'),
    ('Mehrlängenzuschlag', 'mehrlaengenzuschlag'), ('Überbauungsziffer', 'ueberbauungsziffer'),
    ('Untergeschosse', 'untergeschosse'), ('Waldabstand', 'waldabstand'), ('Wohnanteil', 'wohnanteil'),
]
ZONE_PARAM_VARIANTS = [('standard', 'Standard'), ('bonus', 'Bonus'), ('arealueberbauung', 'Arealüberbauung')]


def get_zone_parameters(bfs, zone_candidates):
    """Sucht die Zonenparameter (Grenzabstand, Gebäudehöhe usw.) aus data_hslu260312.csv
    für die gegebene Gemeinde (BFS) und einen der Zonennamen-Kandidaten (zone_kommunal,
    zone_detail, zone_category - je nachdem, was die geodienste.ch/bauzonen-Abfrage
    geliefert hat). Erst exakter, dann fuzzy (substring) Abgleich auf zone_clean."""
    if not bfs:
        return None
    candidates = [c.strip().lower() for c in zone_candidates if c]
    if not candidates:
        return None
    df = query_df('SELECT * FROM dim_zone_parameter WHERE BFS=?', [int(bfs)])
    if df.empty:
        return None
    norm = df['zone_clean'].str.strip().str.lower()
    for cand in candidates:
        match = df[norm == cand]
        if len(match):
            return match.iloc[0].to_dict()
    for cand in candidates:
        match = df[norm.apply(lambda z: cand in z or z in cand)]
        if len(match):
            return match.iloc[0].to_dict()
    return None


def format_zone_parameters_table(row):
    """Baut die Anzeige-Tabelle (Parameter x Standard/Bonus/Arealüberbauung) aus einer
    dim_zone_parameter-Zeile - alle 27 Parameter-Typen werden gezeigt, auch wenn für diese
    konkrete Zone kein Wert erfasst ist (Spalte "Bemerkung": "nicht vorhanden"). Jede Zeile in
    dim_zone_parameter ist bereits zonenspezifisch (Schlüssel BFS + Zone), d.h. die Werte
    gelten exakt für die hier gematchte Zone - "nicht vorhanden" heisst nicht "Daten fehlen",
    sondern dass das Reglement für diesen Parameter in dieser Zone schlicht kein Mass festlegt
    (z.B. kein Waldabstand in einer nicht waldangrenzenden Zone)."""
    records = []
    for label, slug in ZONE_PARAM_TYPES:
        values = {}
        any_value = False
        for variant_slug, variant_label in ZONE_PARAM_VARIANTS:
            val = row.get(f'{slug}_{variant_slug}_value')
            values[variant_label] = val if val not in (None, '') else '–'
            if val not in (None, ''):
                any_value = True
        records.append({'Parameter': label, **values, 'Bemerkung': '' if any_value else 'nicht vorhanden'})
    return records


def parse_max_numeric(value_str):
    """Extrahiert die grösste Zahl aus einem Ausnützungsziffer-Text wie '≤0.8' oder
    '0.45; ≤0.45' oder '1; ≤1.2'. Die Reglementstexte fassen teils mehrere bedingte Werte in
    einem Feld zusammen (Grundwert + gedeckelter Ausnahmewert) - der grösste gefundene Wert
    dient als optimistische Obergrenze für die Flächenschätzung, nicht als Garantie."""
    if not value_str or value_str in ('–', ''):
        return None
    numbers = re.findall(r'\d+(?:[.,]\d+)?', value_str)
    if not numbers:
        return None
    return max(float(n.replace(',', '.')) for n in numbers)


def layout(query=None, **kwargs):
    # Dash übergibt jeden URL-Query-Parameter direkt als Keyword-Argument an layout() -
    # zuverlässiger als der vorherige Umweg über eine client-seitige dcc.Location, deren
    # 'search'-Prop bei einer SPA-Navigation (dcc.Link von der Suche her) nicht immer
    # rechtzeitig gesetzt war und die Adresse dadurch nicht übernahm. Der initiale Wert des
    # Adressfelds löst 'store_parcel_data'/'update_map' beim ersten Rendern ganz natürlich aus
    # (Dash führt jeden Callback einmal mit den initialen Prop-Werten aus).
    initial_address = clean_address(unquote(query)) if query else ''
    return page_shell('/suche/parzellen', 'Parzellen', 'Parzellenfläche, Nutzungszone und Reglementsstatus zu einer Adresse.', [
        dcc.Store(id='parcel_data_store', data={}),
        dcc.Store(id='clicked_coordinates', data={}),
        html.Div([
            section_card('Karte', html.Iframe(id='map', src='', width='100%', height='620px', style={'border': 'none'})),
            section_card('Details', [
                html.Div([
                    dcc.Input(id='address_input', type='text', placeholder='Adresse eingeben', value=initial_address,
                              style={'flex': 1, 'height': '38px', 'padding': '0 12px', 'border': '1px solid var(--border)', 'borderRadius': '6px'}),
                    html.Button('Suchen', id='search_button', n_clicks=0, className='btn-primary'),
                ], style={'display': 'flex', 'gap': '10px', 'marginBottom': '18px'}),
                dcc.Tabs(id='tabs', value='tab-1', children=[
                    dcc.Tab(label='Stammdaten', value='tab-1', className='ris-tab', selected_className='ris-tab--selected'),
                    dcc.Tab(label='Parameter', value='tab-2', className='ris-tab', selected_className='ris-tab--selected'),
                ], className='ris-tabs'),
                html.Div(id='tab-content', style={'marginTop': '16px'}),
            ]),
        ], className='grid-2-1'),
        html.Div(id='municipality-context'),
    ])


@callback(Output('tab-content', 'children'), Input('tabs', 'value'), Input('parcel_data_store', 'data'))
def update_tab_content(active_tab, parcel_data):
    if active_tab == 'tab-2':
        if not parcel_data:
            return html.P('bitte Parzelle wählen')
        candidates = [parcel_data.get('zone_kommunal'), parcel_data.get('zone_detail'), parcel_data.get('zone_category')]
        row = get_zone_parameters(parcel_data.get('bfs'), candidates)
        if not row:
            zone_label = parcel_data.get('zone_kommunal') or parcel_data.get('zone_category') or 'unbekannte Zone'
            return html.P(f"Keine Zonenparameter für diese Gemeinde/Zone in data_hslu260312.csv gefunden ({zone_label}).")
        records = format_zone_parameters_table(row)
        cols = [{'name': c, 'id': c} for c in records[0].keys()]

        return html.Div([
            html.P(f"Zone: {row['zone_clean']} · Basis: {int(row['n_source_projects'])} Projekt(e)", className='kpi-subtitle', style={'marginBottom': '10px'}),
            styled_table(records, cols, page_size=30, sort=True, filter_=False, style_data_conditional=[
                {'if': {'filter_query': '{Bemerkung} = "nicht vorhanden"'}, 'color': COLORS['gray'], 'fontStyle': 'italic'},
            ]),
        ])

    if active_tab != 'tab-1':
        return None

    if not parcel_data:
        return html.Div([info_row('Parzellenfläche', 'bitte Parzelle wählen')])

    na = '–'
    area_text = f"{parcel_data['area']:.2f} m²" if parcel_data.get('area') is not None else na
    # zone_category ist die einzige Angabe, die IMMER verfügbar ist (auch im
    # ch.are.bauzonen-Fallback, der kein zone_kantonal/zone_kommunal liefert) -
    # bisher wurde sie berechnet, aber nirgends angezeigt.
    zone_category_text = parcel_data.get('zone_category') or na
    kantonal_zone_text = parcel_data.get('zone_kantonal') or na
    kommunal_zone_text = parcel_data.get('zone_kommunal') or parcel_data.get('zone_detail') or na
    canton_text = parcel_data.get('canton') or na
    status_text = format_legal_status(parcel_data.get('legal_status')) or na
    published_text = parcel_data.get('published_from') or na
    source_text = parcel_data.get('zone_source') or na
    overlays = parcel_data.get('overlays', [])
    documents = parcel_data.get('documents', [])

    overlay_elements = [html.Div(ov['label'], style={'marginBottom': '4px'}) for ov in overlays[:5]]
    document_elements = []
    for doc in documents[:5]:
        if doc.get('link'):
            document_elements.append(html.A(doc['title'], href=doc['link'], target='_blank',
                                             style={'display': 'block', 'marginBottom': '4px', 'color': 'var(--blue)'}))
        else:
            document_elements.append(html.Div(doc['title'], style={'marginBottom': '4px'}))

    return html.Div([
        info_row('Parzellenfläche', area_text),
        info_row('Nutzungskategorie', zone_category_text),
        info_row('Zone kantonal', kantonal_zone_text),
        info_row('Zone kommunal', kommunal_zone_text),
        info_row('Kanton', canton_text),
        info_row('Rechtsstatus', status_text),
        info_row('Publiziert ab', published_text),
        info_row('Quelle', source_text),
        info_row('Überlagerungen', html.Div(overlay_elements) if overlay_elements else 'noch nicht geladen'),
        info_row('Dokumente', html.Div(document_elements) if document_elements else 'keine Dokumente im Datensatz'),
    ])


@callback(
    Output('parcel_data_store', 'data'), Output('municipality-context', 'children'),
    Input('search_button', 'n_clicks'), Input('address_input', 'n_submit'), Input('clicked_coordinates', 'data'),
    State('address_input', 'value'),
)
def store_parcel_data(n_clicks, n_submit, clicked_coordinates, address):
    if not address:
        return dash.no_update, dash.no_update
    coords = get_coordinates(clean_address(address))
    if not coords:
        return dash.no_update, dash.no_update
    lon, lat = coords
    parcel_id, parcel_name, e, n, area = get_parcel_data(lon, lat)
    if not parcel_id:
        return dash.no_update, dash.no_update
    zone_info = get_zone_data(e, n)
    parcel_data = {'parcel_id': parcel_id, 'parcel_name': parcel_name, 'area': area, **zone_info}
    return parcel_data, build_municipality_context(zone_info.get('bfs'), parcel_data)


def build_municipality_context(bfs, parcel_data=None):
    if not bfs:
        return None
    summary = municipality_summary(bfs)
    if summary.empty:
        return None
    s = summary.iloc[0]
    docs = municipality_documents(bfs)
    sustainability = municipality_sustainability(bfs)

    parcel_kpis = None
    if parcel_data:
        area = parcel_data.get('area')
        candidates = [parcel_data.get('zone_kommunal'), parcel_data.get('zone_detail'), parcel_data.get('zone_category')]
        zone_row = get_zone_parameters(bfs, candidates)
        az_raw = zone_row.get('ausnuetzungsziffer_standard_value') if zone_row else None
        az_value = parse_max_numeric(az_raw)
        parcel_kpis = html.Div([
            kpi('Parzellenfläche', f'{area:,.0f} m²' if area else '–', accent='navy'),
            kpi('Ausnützungsziffer (Standard)', f'{az_value:g}' if az_value else '–',
                f'„{az_raw}“' if az_raw and az_raw != '–' else 'für diese Zone nicht erfasst', accent='blue'),
            kpi('Potenziell bebaubare Fläche (BGF)', f'{area * az_value:,.0f} m²' if area and az_value else '–',
                'Parzellenfläche × Ausnützungsziffer – grobe Schätzung' if area and az_value else '', accent='teal'),
        ], className='grid-3', style={'marginBottom': '20px'})

    kpis = html.Div([
        kpi('Gesamt-Score', f"{s.overall_score:.1f}" if s.overall_score == s.overall_score else '–', accent='navy'),
        kpi('Peer-Rang', f"{s.peer_rank:.0f} / {s.peer_group_size:.0f}" if s.peer_rank == s.peer_rank and s.peer_group_size == s.peer_group_size else '–', accent='blue'),
        kpi('Median Bewilligungsdauer', f"{s.median_duration:.0f} Tage" if s.median_duration == s.median_duration else '–', accent='teal'),
        kpi('Komplexitätsindex', f"{s.complexity_index_raw:.2f}" if s.complexity_index_raw == s.complexity_index_raw else '–', accent='orange'),
    ], className='grid-4')

    doc_links = [html.A(f"Reglement öffnen {d['Ortsteil']} ↗", href=d['canonical_url'], target='_blank',
                         style={'display': 'block', 'marginBottom': '6px', 'color': 'var(--blue)'})
                 for _, d in docs.iterrows() if d.get('canonical_url')]

    tags = []
    if sustainability['supported']:
        tags.append(html.Div([html.Span('Gefördert: ', style={'fontWeight': 600}), ', '.join(sustainability['supported'])],
                              className='kpi-subtitle', style={'marginBottom': '4px'}))
    if sustainability['restricted']:
        tags.append(html.Div([html.Span('Eingeschränkt: ', style={'fontWeight': 600}), ', '.join(sustainability['restricted'])],
                              className='kpi-subtitle'))
    if not tags:
        tags = [html.P('Keine Förder-/Einschränkungshinweise erfasst.', className='kpi-subtitle')]

    return section_card(f"Gemeinde-Kontext: {s.municipality_name} ({s.Kanton})", [
        parcel_kpis,
        kpis,
        html.Div([
            html.Div([html.H4('Reglement', style={'fontSize': '0.9rem', 'marginBottom': '8px'})] +
                     (doc_links or [html.P('Kein Reglement erfasst.', className='kpi-subtitle')]) +
                     [dcc.Link('Gemeindeprofil ansehen →', href=f'/gemeinde?bfs={int(bfs)}', className='btn-primary',
                               style={'textDecoration': 'none', 'display': 'inline-block', 'marginTop': '10px'})]),
            html.Div([html.H4('Nachhaltigkeit (Reglement)', style={'fontSize': '0.9rem', 'marginBottom': '8px'})] + tags),
        ], className='grid-2', style={'marginTop': '20px'}),
    ])


@callback(
    Output('map', 'src'),
    Input('search_button', 'n_clicks'), Input('address_input', 'n_submit'),
    State('address_input', 'value'),
)
def update_map(n_clicks, n_submit, address):
    # Kein ctx.triggered-Guard mehr: beim initialen Rendern mit über ?query= vorbefüllter
    # Adresse (layout(query=...)) ist ctx.triggered leer (Dash-eigenes Verhalten für den
    # "einmaligen Aufruf mit den initialen Prop-Werten"), was den Guard fälschlich auslöste
    # und die Karte nie befüllte - obwohl die Adresse schon da war. `if not address` reicht
    # als Schutz vollkommen aus (identisch zu store_parcel_data unten).
    if not address:
        return ''
    coords = get_coordinates(clean_address(address))
    if not coords:
        return ''
    lon, lat = coords
    parcel_id, parcel_name, e, n, _ = get_parcel_data(lon, lat)
    if not parcel_id:
        return ''
    return (
        'https://map.geo.admin.ch/embed.html?showMap=true&lang=de&bgLayer=void'
        f'&layers=ch.kantone.cadastralwebmap-farbe@features={parcel_id}'
        f'&layers_opacity=1&center={e},{n}&zoom=12.4'
    )
