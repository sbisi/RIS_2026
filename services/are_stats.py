"""Bauzonenstatistik Schweiz 2022 (ARE, Bundesamt für Raumentwicklung) - unüberbaute
(unbebaute) Bauzonenfläche je Gemeinde, als Potenzial-Indikator auf Gemeinde-Ebene (siehe
pages/municipality.py, Abschnitt "Potenzial-Ranking").

Dies ist bewusst eine Gemeinde-Ebene, keine Parzellen-Ebene: eine echte gesamtschweizerische
Parzellen-Rangliste ist mit den verfügbaren Quellen nicht berechenbar - es gibt keine
Bulk-Parzellendatenbank (Parzellen werden nur live pro Adresse/Koordinate abgefragt, siehe
services/geo.py) und selbst dort, wo das ginge, ist die Ausnützungsziffer nur für ~26% der
Gemeinden erfasst (siehe ausnuetzungsziffer_coverage_map() in services/data.py). Die ARE-
Bauzonenstatistik ist dagegen die einzige national vollständige, amtliche Quelle für
unausgeschöpftes Bauland - Stand 2022, wird nur alle paar Jahre neu erhoben."""
import io
import logging
import time

import pandas as pd
import requests

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60
_CACHE_TTL_SECONDS = 86400  # 24h - die Quelle selbst aktualisiert sich ohnehin nur alle paar Jahre
_cache = {'timestamp': 0.0, 'df': None}

_XLSX_URL = 'https://www.are.admin.ch/dam/fr/sd-web/7cEPibyb2l-3/bauzonenstatistik_schweiz_2022_gemeinden.xlsx'
# HN 11-19 = alle 9 Hauptnutzungs-Kategorien innerhalb der Bauzone (Gesamtbauzonenfläche).
_HN_COLS = ['HN_11', 'HN_12', 'HN_13', 'HN_14', 'HN_15', 'HN_16', 'HN_17', 'HN_18', 'HN_19']
# Unüberbaute Fläche wird laut ARE nur für HN 11-14 (Wohn-/Arbeits-/Misch-/Zentrumszonen)
# ausgewiesen - HN 15-19 gelten definitionsgemäss als zu 100% überbaut (siehe Légende-Blatt
# der Originaldatei). "Supposition 1" ist die erste der beiden von ARE verwendeten
# geoanalytischen Abgrenzungsmethoden für "unüberbaut" (Supposition 2 fällt tendenziell
# etwas enger aus) - hier bewusst die erste, breitere Abgrenzung gewählt.
_UNUEB_COLS = ['Unüb1_11', 'Unüb1_12', 'Unüb1_13', 'Unüb1_14']


def get_bauzonenreserven():
    """DataFrame (BFS, Name, Kanton, Gesamtbauzone_ha, Unueberbaut_ha, Anteil_unueberbaut) für
    rund 2'139 Gemeinden mit Bauzonenfläche > 0, oder None bei Fehler."""
    now = time.time()
    if _cache['df'] is not None and now - _cache['timestamp'] < _CACHE_TTL_SECONDS:
        return _cache['df']
    try:
        resp = requests.get(_XLSX_URL, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        buf = io.BytesIO(resp.content)
        haupt = pd.read_excel(buf, sheet_name='Statistique aff. principales', engine='openpyxl')
        buf.seek(0)
        unbebaut = pd.read_excel(buf, sheet_name='Analyse non construit supp. 1', engine='openpyxl')
    except Exception as ex:
        logger.warning('get_bauzonenreserven: Abfrage/Parsing fehlgeschlagen: %s', ex)
        return None

    haupt = haupt.copy()
    unbebaut = unbebaut.copy()
    haupt['Gesamtbauzone_ha'] = haupt[_HN_COLS].sum(axis=1, skipna=True)
    unbebaut['Unueberbaut_ha'] = unbebaut[_UNUEB_COLS].sum(axis=1, skipna=True)

    df = haupt[['Gem_No', 'Name', 'Kt_Kz', 'Gesamtbauzone_ha']].merge(
        unbebaut[['Gem_No', 'Unueberbaut_ha']], on='Gem_No', how='left'
    )
    df = df.rename(columns={'Gem_No': 'BFS', 'Kt_Kz': 'Kanton'})
    df = df[df['Gesamtbauzone_ha'] > 0].copy()
    df['Anteil_unueberbaut'] = df['Unueberbaut_ha'] / df['Gesamtbauzone_ha']

    _cache['df'] = df
    _cache['timestamp'] = now
    return df
