"""Parzellen mit dem grössten Ausbaupotenzial je Gemeinde - orchestriert services/geo.py
(Zonenpolygone, Parzellenfläche per Koordinate), services/geo_buildings.py (Bulk-Gebäude/
-Adressen, MADD) und dim_zone_parameter (Ausnützungsziffer). Siehe pages/municipality.py,
Abschnitt "Rangliste: Parzellen mit grösstem Ausbaupotenzial".

Nur für eine EINZELNE gewählte Gemeinde berechenbar, nicht für die ganze Schweiz auf einen
Schlag: die Parzellenfläche gibt es nur per Live-Koordinatenabfrage (keine Bulk-Parzellen-
datenbank - siehe services/are_stats.py Moduldoc für die ausführliche Begründung), ein Request
pro Gebäude gegen api3.geo.admin.ch. Live gemessen: ca. 3-4 Requests/s, UNABHÄNGIG von der
Parallelität unseres ThreadPoolExecutors (serverseitiges Limit dort, nicht unseres - mehr
Worker bringen nichts). Deshalb FETCH_CAP: nur eine Zufallsstichprobe von maximal FETCH_CAP
AZ-Kandidaten einer Gemeinde wird tatsächlich abgefragt - bei grossen Gemeinden mit mehr
Kandidaten ist das Ergebnis dadurch eine Annäherung ans echte Top-N, kein exaktes Ranking über
alle Gebäude (wird dem Nutzer explizit angezeigt, siehe meta['n_candidates_total'])."""
import logging
import re
from concurrent.futures import ThreadPoolExecutor

from shapely.geometry import shape, Point

from database.db import query_df
from services.geo import get_zones_for_municipality, get_parcel_data, HAUPTNUTZUNG_GROUPS
from services.geo_buildings import get_bulk_buildings, get_bulk_addresses

logger = logging.getLogger(__name__)

FETCH_CAP = 150  # bei ~3-4 Requests/s (serverseitiges Limit) ca. 40-50s Wartezeit
PARCEL_FETCH_WORKERS = 20


def _parse_max_numeric(value_str):
    """Dieselbe Logik wie parse_max_numeric() in pages/parzellen.py, hier dupliziert statt
    importiert (services/ darf nicht aus pages/ importieren, siehe services/geo.py)."""
    if not value_str or value_str in ('–', ''):
        return None
    numbers = re.findall(r'\d+(?:[.,]\d+)?', str(value_str))
    if not numbers:
        return None
    return max(float(n.replace(',', '.')) for n in numbers)


def _zone_az_map(bfs):
    zp = query_df('''
        SELECT zone_clean, ausnuetzungsziffer_standard_value FROM dim_zone_parameter WHERE BFS=?
    ''', [int(bfs)])
    zp['zone_clean_norm'] = zp['zone_clean'].str.strip().str.lower()
    zp['az_numeric'] = zp['ausnuetzungsziffer_standard_value'].apply(_parse_max_numeric)
    zp = zp.dropna(subset=['az_numeric'])
    return dict(zip(zp['zone_clean_norm'], zp['az_numeric']))


def get_parcel_potential_ranking(bfs, top_n=25, hauptnutzung_filter=None):
    """(DataFrame, meta) mit den top_n Gebäuden/Parzellen mit dem grössten geschätzten
    Ausbaupotenzial dieser Gemeinde. hauptnutzung_filter: einer der Werte aus
    services.geo.HAUPTNUTZUNG_ORDER (z.B. "Wohnzonen") oder None für alle. DataFrame ist None,
    wenn nichts berechenbar ist - meta enthält dann 'reason' (einer von: keine_az,
    keine_gebaeude, keine_zonen, keine_kandidaten). Spalten bei Erfolg: egid, adresse, zone,
    hauptnutzung, az, parzellenflaeche_m2, nutzungsflaeche_aktuell_m2, bgf_potenzial_m2,
    ausbaupotenzial_m2, lat, lon."""
    az_map = _zone_az_map(bfs)
    if not az_map:
        return None, {'reason': 'keine_az'}

    buildings = get_bulk_buildings(bfs)
    if buildings is None or buildings.empty:
        return None, {'reason': 'keine_gebaeude'}

    zones = get_zones_for_municipality(bfs)
    if not zones:
        return None, {'reason': 'keine_zonen'}
    zone_polys = [(shape(z['geometry']), z['zone'].strip().lower(),
                   HAUPTNUTZUNG_GROUPS.get(z['hauptnutzung'], 'Andere')) for z in zones]

    existing = buildings[buildings['status'] == 'bestehend'].dropna(subset=['gebaeudeflaeche_m2', 'geschosse']).copy()

    def match_zone_az(lon, lat):
        pt = Point(lon, lat)
        for poly, zname, hauptnutzung in zone_polys:
            if poly.covers(pt):
                return zname, az_map.get(zname), hauptnutzung
        return None, None, None

    matches = [match_zone_az(r.lon, r.lat) for r in existing.itertuples()]
    existing['zone'] = [m[0] for m in matches]
    existing['az'] = [m[1] for m in matches]
    existing['hauptnutzung'] = [m[2] for m in matches]
    candidates = existing.dropna(subset=['az']).copy()
    if hauptnutzung_filter:
        candidates = candidates[candidates['hauptnutzung'] == hauptnutzung_filter]
    n_candidates_total = len(candidates)
    if n_candidates_total == 0:
        return None, {'reason': 'keine_kandidaten'}

    if n_candidates_total > FETCH_CAP:
        candidates = candidates.sample(FETCH_CAP, random_state=0)
    n_fetched = len(candidates)

    def fetch_parcel_area(row):
        try:
            _, _, _, _, area = get_parcel_data(row.lon, row.lat)
            return area
        except Exception as ex:
            logger.warning('get_parcel_potential_ranking: Parzellenabfrage fehlgeschlagen für EGID %s: %s', row.egid, ex)
            return None

    with ThreadPoolExecutor(max_workers=PARCEL_FETCH_WORKERS) as ex:
        areas = list(ex.map(fetch_parcel_area, candidates.itertuples()))
    candidates['parzellenflaeche_m2'] = areas
    candidates = candidates.dropna(subset=['parzellenflaeche_m2'])

    candidates['nutzungsflaeche_aktuell_m2'] = candidates['gebaeudeflaeche_m2'] * candidates['geschosse']
    candidates['bgf_potenzial_m2'] = candidates['parzellenflaeche_m2'] * candidates['az']
    candidates['ausbaupotenzial_m2'] = candidates['bgf_potenzial_m2'] - candidates['nutzungsflaeche_aktuell_m2']

    addresses = get_bulk_addresses(bfs)
    candidates = candidates.merge(addresses, on='egid', how='left')

    top = candidates.sort_values('ausbaupotenzial_m2', ascending=False).head(top_n)
    meta = {'reason': None, 'n_candidates_total': n_candidates_total, 'n_fetched': n_fetched, 'cap': FETCH_CAP}
    return top, meta
