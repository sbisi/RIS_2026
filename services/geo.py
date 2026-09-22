"""Geokodierung, amtliche Vermessung und Nutzungsplanung (geodienste.ch, Fallback eidg.
Bauzonen) - gemeinsam genutzt von pages/parzellen.py und pages/investment_case.py.

Bewusst NICHT in pages/ abgelegt: Dashs Page-Loader (_import_layouts_from_pages) exec'ed
jede Datei im pages-Ordner bedingungslos selbst, unabhängig vom sys.modules-Cache. Ein
`from pages.parzellen import ...` in einer anderen Seite führte dazu, dass parzellen.py
zuerst regulär (via Python-Import) und danach nochmals von Dashs eigenem Loader ausgeführt
wurde - mit doppelt registrierten @callback-Outputs (z.B. "map.src") als Folge. Als
services/-Modul wird diese Datei nur einmal reg­ulär importiert.
"""
import json
import logging
from concurrent.futures import ThreadPoolExecutor

import requests
from pyproj import Transformer
from shapely.geometry import shape, Point

from services.geo_zh import get_zh_zone_info

logger = logging.getLogger(__name__)

GEODIENSTE_CRS = 'http://www.opengis.net/def/crs/EPSG/0/2056'
# Grosszügiger bemessen als für lokale Entwicklung nötig: auf gehosteten Umgebungen (z.B.
# Render) ist die Round-Trip-Zeit zu den Schweizer Bundes-Geodiensten oft spürbar länger als
# von einer lokalen/Schweizer Leitung aus - ein zu knapper Timeout sah dort wie ein "kein
# Ergebnis" aus (still abgefangen), obwohl die Anfrage nur noch unterwegs war.
REQUEST_TIMEOUT = 15


def convert_coordinates(x, y, from_epsg='EPSG:4326', to_epsg='EPSG:2056'):
    transformer = Transformer.from_crs(from_epsg, to_epsg, always_xy=True)
    return transformer.transform(x, y)


def clean_address(address):
    return (address or '').replace('﻿', '').replace('​', '').replace(' ', ' ').strip()


def format_legal_status(status):
    mapping = {
        'inKraft': 'in Kraft',
        'AenderungMitVorwirkung': 'Änderung mit Vorwirkung',
        'AenderungOhneVorwirkung': 'Änderung ohne Vorwirkung',
        'provisorisch': 'provisorisch',
    }
    return mapping.get(status, status or '')


def get_coordinates(address):
    try:
        r = requests.get(
            'https://api3.geo.admin.ch/rest/services/api/SearchServer',
            params={'searchText': address, 'type': 'locations'}, timeout=REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        if not data.get('results'):
            logger.warning('get_coordinates: keine Treffer für Adresse %r', address)
            return None
        attrs = data['results'][0].get('attrs', {})
        lon, lat = attrs.get('lon'), attrs.get('lat')
        return (float(lon), float(lat)) if lon is not None and lat is not None else None
    except requests.exceptions.RequestException as e:
        logger.warning('get_coordinates: Anfrage an api3.geo.admin.ch fehlgeschlagen für %r: %s', address, e)
        return None


def get_parcel_data(lon, lat):
    e, n = convert_coordinates(lon, lat, 'EPSG:4326', 'EPSG:2056')
    url = 'https://api3.geo.admin.ch/rest/services/ech/MapServer/identify'
    params = {
        'geometryType': 'esriGeometryPoint', 'geometry': f'{e},{n}', 'sr': 2056,
        'layers': 'all:ch.swisstopo-vd.amtliche-vermessung', 'tolerance': 0,
        'returnGeometry': True, 'geometryFormat': 'geojson', 'f': 'json',
    }
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        if data.get('results'):
            feature = data['results'][0]
            parcel_id = feature.get('featureId')
            parcel_name = feature.get('properties', {}).get('label', 'Unbekannte Parzelle')
            geom = feature.get('geometry')
            area = None
            if geom and 'coordinates' in geom:
                try:
                    area = shape(geom).area
                except Exception:
                    area = None
            return parcel_id, parcel_name, e, n, area
        logger.warning('get_parcel_data: keine Parzelle an Koordinaten e=%s n=%s (amtliche Vermessung ohne Treffer)', e, n)
    except requests.exceptions.RequestException as ex:
        logger.warning('get_parcel_data: Anfrage an api3.geo.admin.ch fehlgeschlagen für e=%s n=%s: %s', e, n, ex)
    return None, None, None, None, None


def get_bauzonen_info(e, n):
    """Ein einziger Call gegen ch.are.bauzonen liefert Kanton, BFS-Nummer und die
    eidg. Bauzonenkategorie zugleich - wird sowohl für die BFS-Auflösung (immer
    benötigt, für den Zonenparameter-Join) als auch als Zonen-Fallback verwendet."""
    url = 'https://api3.geo.admin.ch/rest/services/ech/MapServer/identify'
    params = {
        'geometryType': 'esriGeometryPoint', 'geometry': f'{e},{n}', 'sr': 2056,
        'layers': 'all:ch.are.bauzonen', 'tolerance': 0, 'returnGeometry': False, 'f': 'json',
    }
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        results = response.json().get('results', [])
        if not results:
            logger.warning('get_bauzonen_info: keine Bauzone an Koordinaten e=%s n=%s', e, n)
            return None
        attrs = results[0].get('attributes', {}) or {}
        zone_category = (attrs.get('ch_bez_d') or attrs.get('ch_bez_f') or attrs.get('typ_bez')
                          or attrs.get('typ_kt') or 'Keine Zone gefunden')
        bfs = attrs.get('bfs_no')
        return {
            'canton': attrs.get('kt_kz'),
            'bfs': int(bfs) if bfs not in (None, '') else None,
            'zone_category': zone_category,
        }
    except requests.exceptions.RequestException as e_:
        logger.warning('get_bauzonen_info: Anfrage an api3.geo.admin.ch fehlgeschlagen für e=%s n=%s: %s', e, n, e_)
        return None


def extract_documents(document_field):
    if not document_field:
        return []
    try:
        doc_data = json.loads(document_field) if isinstance(document_field, str) else document_field
        if not isinstance(doc_data, dict):
            return []
        result = []
        for doc in doc_data.get('Dokumente', []):
            title, link = doc.get('Titel'), doc.get('Link')
            if title or link:
                result.append({'title': title or 'Dokument', 'link': link, 'status': doc.get('Rechtsstatus')})
        return result
    except Exception:
        return []


def _fetch_overlay_collection(collection, minx, miny, maxx, maxy):
    url = f'https://www.geodienste.ch/db/npl_nutzungsplanung_v1_2_0/deu/ogcapi/collections/{collection}/items'
    params = {'f': 'json', 'bbox': f'{minx},{miny},{maxx},{maxy}', 'limit': 20, 'crs': GEODIENSTE_CRS}
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        result = []
        for feature in response.json().get('features', []):
            props = feature.get('properties', {})
            label = (
                props.get('typ_kommunal_bezeichnung') or props.get('typ_kantonal_bezeichnung')
                or props.get('hauptnutzung_bezeichnung') or props.get('typ_kommunal_code')
                or props.get('typ_kantonal_code')
            )
            if label:
                result.append({'collection': collection, 'label': label,
                                'rechtsstatus': props.get('rechtsstatus'), 'publiziertab': props.get('publiziertab')})
        return result
    except requests.exceptions.RequestException as ex:
        logger.warning('get_overlay_data_from_geodienste: Anfrage an geodienste.ch (%s) fehlgeschlagen: %s', collection, ex)
        return []


def get_overlay_data_from_geodienste(e, n):
    lon, lat = convert_coordinates(e, n, 'EPSG:2056', 'EPSG:4326')
    delta = 0.002
    minx, miny, maxx, maxy = lon - delta, lat - delta, lon + delta, lat + delta
    # Collection-Namen bei geodienste.ch umbenannt (verifiziert gegen die aktuelle Collection-
    # Liste) - die alten Namen ('..._flaeche'/'_linie'/'_punkt') gaben nur noch 404 zurück, wurden
    # vom try/except stillschweigend abgefangen (Überlagerungen erschienen dadurch immer leer).
    collections = [
        'ueberlagernde_nutzungsplaninhalte_flaechenbezogene_festlegungen',
        'ueberlagernde_nutzungsplaninhalte_linienbezogene_festlegungen',
        'ueberlagernde_nutzungsplaninhalte_punktbezogene_festlegungen',
    ]
    # Die 3 Collections sind unabhängig voneinander - parallel statt sequenziell abfragen,
    # damit ein einzelner langsamer/zeitüberschreitender Call nicht die anderen blockiert
    # (auf gehosteten Umgebungen mit langsamerer Anbindung an geodienste.ch summierten sich
    # 3 sequenzielle Timeouts sonst zu einer sehr langen Gesamtwartezeit).
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = executor.map(lambda c: _fetch_overlay_collection(c, minx, miny, maxx, maxy), collections)
    overlays = [item for sublist in results for item in sublist]

    seen, unique = set(), []
    for item in overlays:
        key = (item['collection'], item['label'])
        if key not in seen:
            seen.add(key)
            unique.append(item)
    return unique


def get_zone_data_from_geodienste(e, n):
    """Fragt geodienste.ch (föderales Nutzungsplanungs-Harmonisierungsmodell) für die exakte
    kommunale/kantonale Zonenbezeichnung ab.

    WICHTIG: der 'bbox'-Parameter dieser OGC-API filtert EMPIRISCH NICHT präzise nach Geometrie -
    verifiziert an einer echten Testadresse (Windisch AG): unabhängig von Bbox-Grösse (±220m bis
    ±30m) und CRS-Kombination kamen exakt dieselben, teils >1km entfernten Treffer zurück (u.a.
    Wald-Flächen mehrere km entfernt), numberMatched blieb im vierstelligen Bereich (~1855) - die
    API liefert offenbar grob nach einem Index-/Tile-Raster statt nach echter Bbox-Intersektion.
    Die alte Logik ("erstes Feature mit einer Bezeichnung") wählte dadurch de facto eine
    ZUFÄLLIGE Zone aus der Trefferliste, nicht die tatsächlich am Punkt gültige - konkret wurde
    für die Testadresse "Wohnzone 3" gemeldet, während die per Punkt-in-Polygon-Check (gegen ALLE
    1855 Treffer) tatsächlich zutreffende Zone "Wohnzone 2" war.

    Fix: grosszügig abfragen (limit=2000, mehr schafft die API bei diesem Kollektionstyp i.d.R.
    nicht an einem Ort) und die den Punkt TATSÄCHLICH enthaltende Zone per shapely bestimmen -
    exakt das Muster, das get_zh_zone_info() für den Kanton ZH schon nutzt. Falls trotzdem keine
    der geladenen Kandidaten den Punkt exakt enthält (z.B. bei einer noch grösseren Trefferzahl
    als das Limit), wird als bestmögliche Näherung die geometrisch nächstgelegene Zone mit einer
    Bezeichnung verwendet (klar als solche geloggt) statt einer positionsbedingt zufälligen."""
    url = 'https://www.geodienste.ch/db/npl_nutzungsplanung_v1_2_0/deu/ogcapi/collections/grundnutzung/items'
    lon, lat = convert_coordinates(e, n, 'EPSG:2056', 'EPSG:4326')
    delta = 0.002
    minx, miny, maxx, maxy = lon - delta, lat - delta, lon + delta, lat + delta
    params = {'f': 'json', 'bbox': f'{minx},{miny},{maxx},{maxy}', 'limit': 2000, 'crs': GEODIENSTE_CRS}
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        features = data.get('features', [])
        if not features:
            logger.warning('get_zone_data_from_geodienste: keine Nutzungsplan-Features an e=%s n=%s', e, n)
            return None

        point = Point(e, n)
        props = None
        for feature in features:
            try:
                geom = shape(feature['geometry'])
            except Exception:
                continue
            if geom.covers(point):
                props = feature.get('properties', {})
                break

        if props is None:
            logger.warning(
                'get_zone_data_from_geodienste: kein Feature enthält den Punkt e=%s n=%s exakt '
                '(%d Kandidaten geprüft, numberMatched=%s) - verwende nächstgelegenes Feature als Näherung.',
                e, n, len(features), data.get('numberMatched'),
            )
            labeled = [f for f in features if f.get('properties', {}).get('typ_kommunal_bezeichnung')
                       or f.get('properties', {}).get('typ_kantonal_bezeichnung')] or features
            try:
                best = min(labeled, key=lambda f: shape(f['geometry']).distance(point))
                props = best.get('properties', {})
            except Exception:
                props = features[0].get('properties', {})

        kantonal_zone = props.get('typ_kantonal_bezeichnung')
        kommunal_zone = props.get('typ_kommunal_bezeichnung')
        zone_detail = kommunal_zone or kantonal_zone or props.get('typ_kommunal_code') or props.get('typ_kantonal_code')
        zone_category = props.get('hauptnutzung_bezeichnung') or props.get('hauptnutzung_code')

        if zone_detail or zone_category:
            return {
                'canton': props.get('kanton'), 'zone_detail': zone_detail, 'zone_category': zone_category,
                'zone_kantonal': kantonal_zone, 'zone_kommunal': kommunal_zone,
                'legal_status': props.get('rechtsstatus'), 'published_from': props.get('publiziertab'),
                'documents': extract_documents(props.get('dokument')),
                'zone_source': 'geodienste.ch grundnutzung',
            }
    except requests.exceptions.RequestException as ex:
        logger.warning('get_zone_data_from_geodienste: Anfrage an geodienste.ch fehlgeschlagen für e=%s n=%s: %s', e, n, ex)
    return None


def get_zone_data(e, n):
    """1) Detailzone über geodienste.ch, 2) Fallback auf ch.are.bauzonen. Die BFS-Nummer
    kommt in jedem Fall aus ch.are.bauzonen (geodienste.ch liefert keine), daher wird dieser
    Call immer ausgeführt - für den späteren Zonenparameter-Join.

    Die drei zugrundeliegenden Lookups (Bauzonen, Detailzone, Überlagerungen) sind voneinander
    unabhängig - vorher liefen sie sequenziell (inkl. 3 sequenzieller Requests allein für die
    Überlagerungen), was sich auf einer gehosteten Umgebung mit langsamerer/instabilerer
    Anbindung an geo.admin.ch/geodienste.ch zu >50s Gesamtwartezeit summieren konnte. Parallel
    ausgeführt limitiert die Gesamtdauer der langsamste einzelne Call statt deren Summe."""
    with ThreadPoolExecutor(max_workers=3) as executor:
        f_bauzonen = executor.submit(get_bauzonen_info, e, n)
        f_zone = executor.submit(get_zone_data_from_geodienste, e, n)
        f_overlays = executor.submit(get_overlay_data_from_geodienste, e, n)
        bauzonen = f_bauzonen.result() or {}
        detailed_result = f_zone.result()
        overlays = f_overlays.result()

    bfs, canton = bauzonen.get('bfs'), bauzonen.get('canton')

    if detailed_result:
        detailed_result['canton'] = detailed_result.get('canton') or canton
        detailed_result['bfs'] = bfs
        detailed_result['overlays'] = overlays
        return detailed_result

    # geodienste.ch (Bund) führt für gewisse Kantone keine Nutzungsplanungsdaten - sie liefern
    # nicht in das föderale Harmonisierungsmodell ein und betreiben stattdessen ein eigenes
    # Geoportal. Kantonsspezifischer Fallback für die exakte Zonenbezeichnung, bevor wir auf die
    # nicht-matchbare grobe eidg. Bauzonenkategorie zurückfallen. Bisher nur ZH; siehe
    # services/geo_zh.py für den Hintergrund und geeignete Erweiterung um weitere Kantone (u.a.
    # VD, TI sind ebenfalls betroffen, deren kantonale Geoportale sind noch nicht angebunden).
    if canton == 'ZH':
        zh = get_zh_zone_info(e, n)
        if zh and zh.get('zone_name'):
            return {
                'canton': canton, 'bfs': bfs, 'zone_detail': zh['zone_name'],
                'zone_category': bauzonen.get('zone_category', 'Keine Zone gefunden'),
                'zone_kantonal': zh.get('canton_zone_category'), 'zone_kommunal': zh['zone_name'],
                'legal_status': zh.get('legal_status'), 'published_from': zh.get('published_from'),
                'documents': [], 'overlays': overlays, 'zone_source': 'Kanton ZH Geoportal (maps.zh.ch)',
            }

    return {
        'canton': canton, 'bfs': bfs, 'zone_detail': None,
        'zone_category': bauzonen.get('zone_category', 'Keine Zone gefunden'),
        'zone_kantonal': None, 'zone_kommunal': None, 'legal_status': None, 'published_from': None,
        'documents': [], 'overlays': overlays, 'zone_source': 'ch.are.bauzonen' if bauzonen else 'keine Quelle',
    }
