"""Bulk-Gebäudedaten (GWR) je ganzer Gemeinde - für pages/gebaeude_analyse.py ("Analyse
Gebäude"). Ergänzt get_building_data() in services/geo.py, das ein einzelnes Gebäude per
Koordinate abfragt (funktioniert national, aber immer nur für EIN Gebäude).

Quelle: der öffentliche Bulk-Export des eidg. Gebäude- und Wohnungsregisters (GWR) über den
MADD-Dienst des BFS - https://www.housing-stat.ch/de/data/supply/public.html. Pro Gemeinde
(BFS-Nummer) steht dort eine eigenständige SQLite-Datenbank bereit
(https://public.madd.bfs.admin.ch/data_{bfs}.sqlite), täglich aktualisiert ("Stand Ende des
Vortages"), mit einer 'building'-Tabelle im selben GWR-Schema wie die Einzelgebäude-Abfrage
in services/geo.py (GSTAT/GKAT/GKLAS/GBAUP-Codes etc. - Decodierung wird von dort übernommen).

Das deckt praktisch jede Schweizer Gemeinde vollständig ab - anders als der find-Endpoint von
api3.geo.admin.ch auf demselben GWR-Layer, der hart bei 201 Treffern deckelt (live verifiziert:
Windisch liefert über diesen Bulk-Export 2360 Gebäude statt der dort gedeckelten 201). Deshalb
wird hier bewusst NICHT mehr auf einzelne kantonale Open-Data-Portale zurückgegriffen.
"""
import logging
import os
import sqlite3
import tempfile
import time

import pandas as pd
import requests
from pyproj import Transformer

from database.db import query_df
from services.geo import GWR_GEBAEUDESTATUS, GWR_GEBAEUDEKATEGORIE, GWR_GEBAEUDEKLASSE, GWR_BAUPERIODE

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60
_CACHE_TTL_SECONDS = 21600  # 6h - Quelle aktualisiert ohnehin nur täglich

_cache = {}  # bfs -> (timestamp, DataFrame)
_LV95_TO_WGS84 = Transformer.from_crs('EPSG:2056', 'EPSG:4326', always_xy=True)


def supported_municipalities():
    """Alle Gemeinden mit BFS-Nummer, für die der Dropdown auf 'Analyse Gebäude' Auswahl bietet.
    Das nationale MADD-Bulk-Register deckt praktisch jede davon ab (siehe get_bulk_buildings())."""
    return query_df('''
        SELECT dm.bfs_number AS bfs, dm.municipality_name AS name, c.canton_code AS canton
        FROM dim_municipality dm LEFT JOIN dim_canton c ON c.canton_id = dm.canton_id
        ORDER BY name
    ''')


def _decode(mapping, code):
    if pd.isna(code):
        return None
    return mapping.get(str(int(code)), str(code))


def get_bulk_buildings(bfs):
    """DataFrame mit einer Zeile je Gebäude für die gegebene Gemeinde (BFS-Nummer), oder None
    wenn die Abfrage fehlschlägt oder die Gemeinde im MADD-Bulk-Register nicht (mehr) existiert."""
    if bfs is None:
        return None
    bfs = int(bfs)

    cached = _cache.get(bfs)
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    url = f'https://public.madd.bfs.admin.ch/data_{bfs}.sqlite'
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.exceptions.RequestException as ex:
        logger.warning('get_bulk_buildings: Abfrage fehlgeschlagen für BFS %s: %s', bfs, ex)
        return None

    # delete=False + manuelles os.remove statt "with": unter Windows hält NamedTemporaryFile die
    # Datei exklusiv offen, solange sie nicht geschlossen ist - sqlite3.connect() auf denselben
    # Pfad scheitert sonst mit "unable to open database file" (live verifiziert).
    tmp = tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False)
    try:
        tmp.write(resp.content)
        tmp.close()
        con = sqlite3.connect(tmp.name)
        try:
            raw = pd.read_sql_query('SELECT * FROM building', con)
        finally:
            con.close()
    finally:
        os.remove(tmp.name)

    if raw.empty:
        df = raw
    else:
        df = pd.DataFrame({
            'egid': raw['EGID'],
            'e': raw['GKODE'], 'n': raw['GKODN'],
            'status': raw['GSTAT'].apply(lambda c: _decode(GWR_GEBAEUDESTATUS, c)),
            'kategorie': raw['GKAT'].apply(lambda c: _decode(GWR_GEBAEUDEKATEGORIE, c)),
            'klasse': raw['GKLAS'].apply(lambda c: _decode(GWR_GEBAEUDEKLASSE, c)),
            'baujahr': pd.to_numeric(raw['GBAUJ'], errors='coerce'),
            'bauperiode': raw['GBAUP'].apply(lambda c: _decode(GWR_BAUPERIODE, c)),
            'geschosse': pd.to_numeric(raw['GASTW'], errors='coerce'),
            'gebaeudeflaeche_m2': pd.to_numeric(raw['GAREA'], errors='coerce'),
            'energiebezugsflaeche_m2': pd.to_numeric(raw['GEBF'], errors='coerce'),
            'anzahl_wohnungen': pd.to_numeric(raw['GANZWHG'], errors='coerce'),
            'bezeichnung': raw['GBEZ'],
        })
        lon, lat = _LV95_TO_WGS84.transform(df['e'].to_numpy(), df['n'].to_numpy())
        df['lon'] = lon
        df['lat'] = lat

    _cache[bfs] = (time.time(), df)
    return df
