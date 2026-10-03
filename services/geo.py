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


# BFS-Codelisten für die GWR-Felder unten - verifiziert gegen die offizielle, mit Klartext-
# Bezeichnungen ausgelieferte GWR-Kopie des Kantons Basel-Stadt (data.bs.ch, Datensatz
# "Gebäude (Gebäude- und Wohnungsregister GWR)", Export mit use_labels=true). Das GWR-Schema ist
# national einheitlich - die Codes gelten unabhängig vom Kanton der abgefragten Adresse.
GWR_GEBAEUDESTATUS = {
    '1001': 'projektiert', '1002': 'bewilligt', '1003': 'im Bau', '1004': 'bestehend',
    '1005': 'nicht nutzbar', '1007': 'abgebrochen', '1008': 'nicht realisiert',
}
GWR_GEBAEUDEKATEGORIE = {
    '1010': 'Provisorische Unterkunft', '1020': 'Gebäude mit ausschliesslicher Wohnnutzung',
    '1030': 'Andere Wohngebäude (mit Nebennutzung)', '1040': 'Gebäude mit teilweiser Wohnnutzung',
    '1060': 'Gebäude ohne Wohnnutzung', '1080': 'Sonderbau',
}
GWR_GEBAEUDEKLASSE = {
    '1110': 'Gebäude mit einer Wohnung', '1121': 'Gebäude mit zwei Wohnungen',
    '1122': 'Gebäude mit drei oder mehr Wohnungen', '1130': 'Wohngebäude für Gemeinschaften',
    '1211': 'Hotelgebäude', '1212': 'Andere Gebäude für kurzfristige Beherbergung',
    '1220': 'Bürogebäude', '1230': 'Gross-/Einzelhandelsgebäude',
    '1241': 'Gebäude des Verkehrs-/Nachrichtenwesens (ohne Garagen)', '1242': 'Garagengebäude',
    '1251': 'Industriegebäude', '1252': 'Behälter, Silos und Lagergebäude',
    '1261': 'Gebäude für Kultur- und Freizeitzwecke', '1262': 'Museen und Bibliotheken',
    '1263': 'Schul-/Hochschulgebäude, Forschungseinrichtungen',
    '1264': 'Krankenhäuser und Facheinrichtungen des Gesundheitswesens', '1265': 'Sporthallen',
    '1271': 'Landwirtschaftliche Betriebsgebäude', '1272': 'Kirchen und sonstige Kultgebäude',
    '1273': 'Denkmäler / unter Denkmalschutz stehende Bauwerke',
    '1274': 'Sonstige Hochbauten (anderweitig nicht genannt)', '1277': 'Gebäude für den Pflanzenbau',
}
GWR_BAUPERIODE = {
    '8011': 'vor 1919', '8012': '1919–1945', '8013': '1946–1960', '8014': '1961–1970',
    '8015': '1971–1980', '8016': '1981–1985', '8017': '1986–1990', '8018': '1991–1995',
    '8019': '1996–2000', '8020': '2001–2005', '8021': '2006–2010', '8022': '2011–2015',
    '8023': 'nach 2015',
}

# geodienste.ch liefert bis zu ~15 verschiedene Hauptnutzungs-Kategorien pro Gemeinde (amtliche
# npl_nutzungsplanung-Klassifikation) - zu viele, um sie z.B. farblich alle unterscheidbar zu
# machen oder einzeln filterbar anzubieten. Feste, gemeinde-unabhängige Gruppierung auf die 4
# für eine Baupotenzial-Analyse wichtigsten Kategorien + "Andere" - gemeinsam genutzt von der
# Zonenkarte und dem Hauptnutzungs-Filter der Parzellen-Rangliste (pages/municipality.py,
# services/parcel_ranking.py), damit dieselbe Zone überall gleich eingeordnet wird.
HAUPTNUTZUNG_GROUPS = {
    'Wohnzonen': 'Wohnzonen',
    'Mischzonen': 'Zentrums- und Mischzonen',
    'Zentrumszonen': 'Zentrums- und Mischzonen',
    'Arbeitszonen': 'Arbeitszonen',
    'allgemeine Landwirtschaftszonen': 'Landwirtschaftszonen',
    'weitere Landwirtschaftszonen': 'Landwirtschaftszonen',
}
HAUPTNUTZUNG_ORDER = ['Wohnzonen', 'Zentrums- und Mischzonen', 'Arbeitszonen', 'Landwirtschaftszonen', 'Andere']


def get_building_data(e, n):
    """Eidg. Gebäude- und Wohnungsregister (GWR, BFS): Baujahr, Kategorie/Klasse, Geschosse,
    Wohnungen usw. für das Gebäude an der gegebenen Koordinate - "was ist auf der Parzelle schon
    gebaut".

    Zwei Schritte, da der GWR-Layer selbst (ch.bfs.gebaeude_wohnungs_register) KEIN punktbasiertes
    identify unterstützt (live getestet: liefert dafür immer 0 Treffer, unabhängig von Toleranz -
    vermutlich als WMTS statt als abfragbarer Vektor-Layer eingerichtet). Stattdessen über das
    amtliche Gebäudeadressverzeichnis auf die EGID auflösen, dann das GWR-Feature direkt per ID
    abrufen (Muster 'ch.bfs.gebaeude_wohnungs_register/{egid}_0' - identisch zu dem, was auch die
    normale Adresssuche selbst intern verlinkt)."""
    url = 'https://api3.geo.admin.ch/rest/services/ech/MapServer/identify'
    params = {
        'geometryType': 'esriGeometryPoint', 'geometry': f'{e},{n}', 'sr': 2056,
        'layers': 'all:ch.swisstopo.amtliches-gebaeudeadressverzeichnis', 'tolerance': 10,
        # Ohne mapExtent/imageDisplay liefert dieser WMS-basierte Layer 0 Treffer (live getestet) -
        # anders als die übrigen (Feature-Server-basierten) Layer in dieser Datei.
        'mapExtent': f'{e - 500},{n - 500},{e + 500},{n + 500}', 'imageDisplay': '800,800,96',
        'returnGeometry': False, 'f': 'json',
    }
    try:
        response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        results = response.json().get('results', [])
        if not results:
            logger.warning('get_building_data: kein Gebäude an Koordinaten e=%s n=%s', e, n)
            return None
        egid = results[0].get('attributes', {}).get('bdg_egid')
        if not egid:
            return None
    except requests.exceptions.RequestException as ex:
        logger.warning('get_building_data: Adressverzeichnis-Abfrage fehlgeschlagen für e=%s n=%s: %s', e, n, ex)
        return None

    try:
        feature_url = f'https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bfs.gebaeude_wohnungs_register/{egid}_0'
        response = requests.get(feature_url, params={'sr': 2056, 'f': 'json'}, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        attrs = response.json().get('feature', {}).get('attributes', {})
        if not attrs:
            return None
    except requests.exceptions.RequestException as ex:
        logger.warning('get_building_data: GWR-Abfrage fehlgeschlagen für EGID %s: %s', egid, ex)
        return None

    baujahr = attrs.get('gbauj')
    dwelling_baujahre = sorted({j for j in (attrs.get('wbauj') or []) if j})
    dwelling_flaechen = sorted({f for f in (attrs.get('warea') or []) if f})

    return {
        'egid': egid,
        'egrid': attrs.get('egrid'),
        'status': GWR_GEBAEUDESTATUS.get(str(attrs.get('gstat')), attrs.get('gstat')),
        'kategorie': GWR_GEBAEUDEKATEGORIE.get(str(attrs.get('gkat')), attrs.get('gkat')),
        'klasse': GWR_GEBAEUDEKLASSE.get(str(attrs.get('gklas')), attrs.get('gklas')),
        'baujahr': int(baujahr) if baujahr else None,
        'bauperiode': None if baujahr else GWR_BAUPERIODE.get(str(attrs.get('gbaup')), attrs.get('gbaup')),
        'geschosse': attrs.get('gastw'),
        'gebaeudeflaeche_m2': attrs.get('garea'),
        'anzahl_wohnungen': attrs.get('ganzwhg'),
        'wohnung_baujahr': f'{dwelling_baujahre[0]}–{dwelling_baujahre[-1]}' if len(dwelling_baujahre) > 1
                           else (str(dwelling_baujahre[0]) if dwelling_baujahre else None),
        'wohnung_flaeche_m2': f'{dwelling_flaechen[0]:g}–{dwelling_flaechen[-1]:g}' if len(dwelling_flaechen) > 1
                              else (f'{dwelling_flaechen[0]:g}' if dwelling_flaechen else None),
    }


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


_LV95_TO_WGS84 = Transformer.from_crs('EPSG:2056', 'EPSG:4326', always_xy=True)


def _reproject_ring(ring):
    return [list(_LV95_TO_WGS84.transform(x, y)) for x, y, *_ in ring]


def _reproject_geometry(geometry):
    gtype = geometry.get('type')
    coords = geometry.get('coordinates')
    if gtype == 'Polygon':
        new_coords = [_reproject_ring(ring) for ring in coords]
    elif gtype == 'MultiPolygon':
        new_coords = [[_reproject_ring(ring) for ring in poly] for poly in coords]
    else:
        return geometry
    return {'type': gtype, 'coordinates': new_coords}


def _get_with_retries(url, params, context, retries=2):
    """requests.get mit kurzen Retries bei Timeout/5xx - api3.geo.admin.ch und geodienste.ch
    antworten gelegentlich einzelne Male langsam/fehlerhaft unter Last (live beobachtet: ein
    einzelner Read-Timeout bei 15s für eine Gemeinde, beim nächsten Versuch sofort wieder
    normal) - ohne Retry wurde ein solcher Ausreisser sonst als dauerhafter Fehler behandelt."""
    last_exc = None
    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response
        except requests.exceptions.RequestException as ex:
            last_exc = ex
            if attempt < retries:
                logger.warning('%s: Versuch %d/%d fehlgeschlagen (%s) - erneuter Versuch.',
                                context, attempt + 1, retries + 1, ex)
    raise last_exc


def get_municipality_boundary(bfs):
    """Aktuelle Gemeindegrenze (swissBOUNDARIES3D, geo.admin.ch) als shapely-Polygon (LV95) +
    Bbox (LV95), oder None - Grundlage für get_zones_for_municipality(). Der find-Endpoint
    liefert pro Gemeinde mehrere historische Jahres-Stände (eine Zeile je Jahr seit ca. 1850,
    live verifiziert an Windisch: 177 Treffer) - is_current_jahr filtert auf den aktuellen."""
    url = 'https://api3.geo.admin.ch/rest/services/api/MapServer/find'
    params = {
        'layer': 'ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill',
        'searchField': 'gde_nr', 'searchText': str(int(bfs)), 'searchType': 'exact',
        'returnGeometry': True, 'sr': 2056, 'geometryFormat': 'geojson',
    }
    try:
        response = _get_with_retries(url, params, 'get_municipality_boundary')
        current = [f for f in response.json().get('results', []) if f.get('properties', {}).get('is_current_jahr')]
        if not current:
            return None
        feature = current[0]
        return shape(feature['geometry']), feature['bbox']
    except requests.exceptions.RequestException as ex:
        logger.warning('get_municipality_boundary: Abfrage fehlgeschlagen für BFS %s: %s', bfs, ex)
        return None


def get_zones_for_municipality(bfs):
    """Alle Nutzungszonen (geodienste.ch) innerhalb der Gemeindegrenze - für die Zonenkarte auf
    Analyse Gemeinden. geodienste.ch's bbox-Parameter filtert NICHT präzise (siehe
    get_zone_data_from_geodienste) - hier zusätzlich verschärft, weil für eine ganze Gemeinde
    auch mit grossem Bbox weit mehr als die eigenen Zonen zurückkommen (live verifiziert an
    Windisch: numberMatched=3942 für eine ~3x3.6km-Bbox). Fix: alle Seiten der Trefferliste
    laden (OGC-API-Pagination über offset) und serverseitig NICHT vertrauen, sondern jede
    Geometrie per shapely gegen die echte Gemeindegrenze (swissBOUNDARIES3D) filtern - nur
    Zonen, deren Zentroid innerhalb der Grenze liegt, gelten als "zu dieser Gemeinde gehörig"."""
    boundary = get_municipality_boundary(bfs)
    if boundary is None:
        return None
    polygon, bbox_lv95 = boundary
    minx, miny, maxx, maxy = bbox_lv95
    lon1, lat1 = convert_coordinates(minx, miny, 'EPSG:2056', 'EPSG:4326')
    lon2, lat2 = convert_coordinates(maxx, maxy, 'EPSG:2056', 'EPSG:4326')

    url = 'https://www.geodienste.ch/db/npl_nutzungsplanung_v1_2_0/deu/ogcapi/collections/grundnutzung/items'
    all_features, offset, max_pages = [], 0, 4  # 4 Seiten x 2000 = 8000 Features Obergrenze
    for _ in range(max_pages):
        params = {'f': 'json', 'bbox': f'{lon1},{lat1},{lon2},{lat2}', 'limit': 2000, 'offset': offset,
                   'crs': GEODIENSTE_CRS}
        try:
            response = _get_with_retries(url, params, 'get_zones_for_municipality')
            data = response.json()
        except requests.exceptions.RequestException as ex:
            logger.warning('get_zones_for_municipality: Abfrage fehlgeschlagen für BFS %s: %s', bfs, ex)
            break
        feats = data.get('features', [])
        all_features.extend(feats)
        if len(feats) < 2000 or len(all_features) >= (data.get('numberMatched') or 0):
            break
        offset += 2000

    zones = []
    for idx, feature in enumerate(all_features):
        try:
            geom = shape(feature['geometry'])
        except Exception:
            continue
        if not geom.centroid.within(polygon):
            continue
        props = feature.get('properties', {})
        zone = props.get('typ_kommunal_bezeichnung') or props.get('typ_kantonal_bezeichnung')
        hauptnutzung = props.get('hauptnutzung_bezeichnung')
        if not zone and not hauptnutzung:
            continue
        zones.append({
            'id': idx,
            'geometry': _reproject_geometry(feature['geometry']),
            'zone': zone or hauptnutzung,
            'hauptnutzung': hauptnutzung or 'Unbekannt',
            'rechtsstatus': props.get('rechtsstatus'),
        })
    return zones


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
