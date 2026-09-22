"""Kanton Zürich: eigenes Geoportal (OGDZHWFS) als Fallback für die exakte Zonenbezeichnung.
Hintergrund: geodienste.ch (das föderale Harmonisierungsmodell, siehe services/geo.py) führt
für Kanton ZH keine Nutzungsplanungsdaten - ZH betreibt ein eigenes, unabhängiges Geoportal
(maps.zh.ch) und speist (Stand heute) nicht in das Bundesmodell ein. Ohne diesen Fallback
liefert get_zone_data() für ZH-Parzellen nur die grobe eidg. Bauzonenkategorie (z.B.
"Wohnzonen"), die nie auf eine der oft mehreren gleichnamigen kommunalen Zonen (z.B.
"Wohnzone 2/1.00" bis "Wohnzone 2/1.75") gematcht werden kann.

Layer ogd-0156_arv_basis_np_gn_zonenflaeche_f liefert die exakte kommunale Zonenbezeichnung
(typ_gde_bezeichnung, z.B. "Wohnzone 3-geschossig 2.75") passgenau für den Punkt - diese
Bezeichnung lässt sich danach unverändert über get_zone_parameters() gegen dim_zone_parameter
matchen, ohne dass an der bestehenden Parameter-Pipeline etwas geändert werden muss. Der Layer
führt zusätzlich einige Masszahlen direkt numerisch (ausnuetzungsziffer_min/max usw.) - diese
werden hier mitgeliefert, aber aktuell nicht separat angezeigt (dim_zone_parameter bleibt die
primäre Quelle für die Parameter-Tabelle)."""
import logging

import requests
from shapely.geometry import shape, Point

logger = logging.getLogger(__name__)

ZH_WFS_URL = 'https://maps.zh.ch/wfs/OGDZHWFS'
ZH_ZONE_LAYER = 'ms:ogd-0156_arv_basis_np_gn_zonenflaeche_f'
REQUEST_TIMEOUT = 15


def get_zh_zone_info(e, n):
    """Punktgenaue Zonenabfrage (LV95) gegen das ZH-Geoportal: kleine BBOX um den Punkt holen,
    dann per shapely das tatsächlich den Punkt enthaltende Polygon bestimmen (die MapServer-WFS
    dieses Dienstes unterstützt keinen einfachen GET-Intersects-Filter, daher client-seitig)."""
    delta = 30
    params = {
        'SERVICE': 'WFS', 'VERSION': '2.0.0', 'REQUEST': 'GetFeature',
        'TYPENAME': ZH_ZONE_LAYER,
        'BBOX': f'{e - delta},{n - delta},{e + delta},{n + delta},urn:ogc:def:crs:EPSG::2056',
        'OUTPUTFORMAT': 'geojson', 'COUNT': 20,
    }
    try:
        r = requests.get(ZH_WFS_URL, params=params, timeout=REQUEST_TIMEOUT, headers={'User-Agent': 'Mozilla/5.0'})
        r.raise_for_status()
        data = r.json()
    except (requests.exceptions.RequestException, ValueError) as ex:
        logger.warning('get_zh_zone_info: Anfrage an maps.zh.ch fehlgeschlagen für e=%s n=%s: %s', e, n, ex)
        return None

    point = Point(e, n)
    features = data.get('features', [])
    for feature in features:
        try:
            geom = shape(feature['geometry'])
        except Exception:
            continue
        if not geom.contains(point):
            continue
        props = feature.get('properties', {})
        return {
            'zone_name': props.get('typ_gde_bezeichnung') or props.get('typ_zh_bezeichnung'),
            'canton_zone_category': props.get('typ_zh_bezeichnung'),
            'legal_status': props.get('rechtsstatus'),
            'published_from': (props.get('publiziertab') or '')[:10] or None,
            'document_url': props.get('dokument') or None,
            'ausnuetzungsziffer_min': props.get('ausnuetzungsziffer_min'),
            'ausnuetzungsziffer_max': props.get('ausnuetzungsziffer_max'),
            'baumassenziffer_min': props.get('baumassenziffer_min'),
            'baumassenziffer_max': props.get('baumassenziffer_max'),
            'ueberbauungsziffer_min': props.get('ueberbauungsziffer_min'),
            'ueberbauungsziffer_max': props.get('ueberbauungsziffer_max'),
            'vollgeschosse_max': props.get('vollgeschosse_max'),
            'untergeschosse_max': props.get('untergeschosse_max'),
            'gebaeudehoehe_max': props.get('gebaeudehoehe_max'),
            'firsthoehe_max': props.get('firsthoehe_max'),
            'wohnanteil_min': props.get('wohnanteil_min'),
            'wohnanteil_max': props.get('wohnanteil_max'),
            'freiflaechenziffer_min': props.get('freiflaechenziffer_min'),
            'fassadenhoehe': props.get('fassadenhoehe'),
            'fassadenhoehe_traufseitig': props.get('fassadenhoehe_traufseitig'),
            'fassadenhoehe_giebelseitig': props.get('fassadenhoehe_giebelseitig'),
        }
    logger.warning('get_zh_zone_info: kein Feature enthält den Punkt e=%s n=%s (%d Kandidaten geprüft)', e, n, len(features))
    return None
