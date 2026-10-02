"""Amtliche BFS-Zeitreihe 'Neu erstellte Wohnungen' (STAT-TAB, Tabelle px-x-0904030000_107)
als Vergleichsgrösse zu unseren eigenen Baugesuche-Daten auf Analyse Baugesuche (siehe
pages/building_permit.py). Läuft 2013-2024, jährlich aktuell.

Bewusst NICHT die ältere 'Bauvorhaben nach Kanton/Gemeinde'-Tabelle (px-x-0904010000_111-113)
verwendet, die auf den ersten Blick näher am Konzept 'Baugesuch' liegt - diese Erhebung wurde
2012 eingestellt (letzter Jahreswert 2012, live geprüft) und wäre als aktueller Vergleich
irreführend. px-x-0904030000_107 ist die einzige noch laufend aktualisierte Tabelle in dieser
BFS-Kategorie und misst fertiggestellte Neubauwohnungen statt Baugesuche - konzeptionell nicht
identisch (Bewilligung vs. Fertigstellung), aber die einzige lebende amtliche Vergleichsgrösse.
"""
import logging
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 30
_CACHE_TTL_SECONDS = 21600  # 6h

_cache = {}  # code -> (timestamp, DataFrame)
_PX_URL = 'https://www.pxweb.bfs.admin.ch/api/v1/de/px-x-0904030000_107/px-x-0904030000_107.px'
_REGION_DIM = 'Grossregion (<<) / Kanton (-) / Gemeinde (......)'


def get_new_dwellings_yearly(bfs=None, canton_code=None):
    """DataFrame (Jahr, Wohnungen) für 2013-2024 (neu erstellte Wohnungen, alle Gebäudetypen),
    oder None wenn die Abfrage fehlschlägt. bfs hat Vorrang vor canton_code; ohne beides wird
    der nationale Wert ('CH') geliefert."""
    if bfs:
        code = str(int(bfs)).zfill(4)
    elif canton_code:
        code = canton_code
    else:
        code = 'CH'

    cached = _cache.get(code)
    if cached and time.time() - cached[0] < _CACHE_TTL_SECONDS:
        return cached[1]

    body = {
        'query': [
            {'code': _REGION_DIM, 'selection': {'filter': 'item', 'values': [code]}},
            {'code': 'Gebäudetyp', 'selection': {'filter': 'item', 'values': ['0']}},
            {'code': 'Jahr', 'selection': {'filter': 'all', 'values': ['*']}},
        ],
        'response': {'format': 'json-stat2'},
    }
    try:
        resp = requests.post(_PX_URL, json=body, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        data = resp.json()
        years = list(data['dimension']['Jahr']['category']['label'].values())
        values = data['value']
    except (requests.exceptions.RequestException, KeyError, ValueError) as ex:
        logger.warning('get_new_dwellings_yearly: Abfrage fehlgeschlagen für %s: %s', code, ex)
        return None

    df = pd.DataFrame({'Jahr': [int(y) for y in years], 'Wohnungen': values})
    _cache[code] = (time.time(), df)
    return df
