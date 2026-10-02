#!/usr/bin/env python3
"""
BZO-Crawler: Versucht, für alle Schweizer Gemeinden die aktuelle
Bau- und Zonenordnung (BZO) als PDF zu finden und herunterzuladen.

WICHTIG / Realitätscheck:
- Es gibt keine einheitliche nationale Quelle für BZO-Dokumente.
  Jede Gemeinde bzw. jeder Kanton veröffentlicht das anders (eigene
  Gemeinde-Website, kantonales Geoportal, teils nur auf Anfrage).
- Dieses Skript sucht deshalb PRO GEMEINDE per Suchmaschine nach einem
  passenden PDF. Die Trefferquote wird nie 100% sein. Alles wird in
  einer CSV protokolliert (gefunden / nicht gefunden / Fehler), damit
  du die Lücken gezielt manuell nachbearbeiten kannst.
- Suchbegriffe sind sprachabhängig (Deutsch/Französisch/Italienisch je
  Kanton, siehe CANTON_LANGUAGE) und decken 18+ bekannte Bezeichnungen ab.
- Offensichtliches Rauschen (Flyer, Gerichtsentscheide, Sitzungsprotokolle
  usw., die das Suchwort nur zufällig enthalten) wird anhand des Titels
  gefiltert (siehe NOISE_TITLE_KEYWORDS) - kein Allheilmittel, reduziert
  aber den offensichtlichsten Teil der Fehltreffer.
- Nicht-PDF-Suchtreffer (Gemeinde-Landingpages) werden einmal nachgeladen
  und auf PDF-Links durchsucht, statt komplett verworfen zu werden.
- CANTON_FALLBACK_SOURCES ist ein Erweiterungspunkt für kantonale
  Geoportale/Register als Zweitquelle - aktuell LEER (siehe Kommentar
  dort: keine unverifizierten Endpunkte, die stillschweigend nichts
  liefern würden).
- Bitte robots.txt und Nutzungsbedingungen der jeweiligen Websites
  beachten und die Rate (SLEEP_SECONDS) nicht zu aggressiv setzen.
- Läuft separat vom Dashboard (nicht Teil des deployten Web-Apps) - die
  Dashboard-Seite "Update Reglemente" (/update-reglement) liest nur das
  Ergebnis-CSV dieses Skripts, startet es aber nicht selbst.

Installation (nur lokal, nicht Teil von requirements.txt der App):
    pip install ddgs

Nutzung (aus dem Projekt-Root, z.B. dashboard/):
    python scripts/bzo_crawler.py --limit 20   # Testlauf mit 20 Gemeinden
    python scripts/bzo_crawler.py              # alle Gemeinden (mehrere Stunden!)
    python scripts/bzo_crawler.py --canton ZH  # nur Kanton Zürich
    python scripts/bzo_crawler.py --canton FR --sleep 10 --query-sleep 6  # noch vorsichtiger

Fortsetzen nach Abbruch (Rechner-Standby, Absturz, manueller Stopp):
    Einfach denselben Befehl nochmal ausführen - bereits in der Ergebnis-CSV vorhandene
    Gemeinden werden automatisch übersprungen. Für einen komplett neuen Durchlauf trotz
    vorhandener CSV: --restart anhängen (oder die CSV vorher löschen).
"""

import argparse
import csv
import io
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse, urljoin

import requests

try:
    from ddgs import DDGS  # neues Paket (Nachfolger von duckduckgo_search)
except ImportError:
    from duckduckgo_search import DDGS  # Fallback altes Paket

# Pfade relativ zum Projekt-Root (Elternordner von scripts/), unabhängig vom
# aktuellen Arbeitsverzeichnis beim Aufruf - data/audit/ ist der Ort, den die
# Dashboard-Seite "Update Reglemente" (pages/reglement_update.py) erwartet.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_DIR = PROJECT_ROOT / "data" / "audit" / "bzo_downloads"
LOG_CSV = PROJECT_ROOT / "data" / "audit" / "bzo_ergebnisse.csv"
# Bereits vorhandenes lokales Reglement-Archiv (Dateiname-Konvention "{KANTON}_{Gemeinde}.pdf",
# z.B. "AG_BeinwilAmSee.pdf", teils mit "_Zusatz1"/"_Zusatz2"-Ergänzungsdokumenten) - noch nicht
# ans übrige System angebunden, hier nur zum Abgleich "haben wir das schon / ist unsere Version
# aktuell?" genutzt.
REGLEMENTE_DIR = PROJECT_ROOT / "data" / "Reglemente"
# Mehrere Testläufe zeigten: die Trefferquote schwankt extrem zwischen Läufen (44.5% -> 63.0% ->
# 3.4% -> 9.2% -> 16.0%/18.8%+0.9%), auch unabhängig von Code-Änderungen - starkes Indiz für
# serverseitiges Rate-Limiting/Drosselung durch DuckDuckGo bei zu dichter Anfragefolge (die
# inoffizielle ddgs-Bibliothek scrapt die Weboberfläche, keine offizielle API mit garantierten
# Kontingenten). Ein Testlauf mit stark erhöhten Pausen (8s/4s) brach die Drosselung aber NICHT
# zuverlässig, kostete dafür ~30h für den Volllauf - schlechter Tausch. Deshalb wieder auf einen
# moderateren Wert gesenkt; die eigentliche Absicherung gegen Drosselungs-Lücken ist jetzt
# --retry-not-found (gezieltes Nacherfassen statt pauschal längerer Pausen, siehe unten).
SLEEP_SECONDS = 4.0  # Pause zwischen Gemeinden
QUERY_SLEEP_SECONDS = 2.0  # Pause zwischen den DDG-Suchanfragen innerhalb einer Gemeinde
TIMEOUT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; BZO-Research-Bot/1.0)"}

# Alle bekannten Bezeichnungen für das gesuchte Dokument, in Gruppen mit OR verknüpft statt
# einzelner Suchanfragen pro Begriff - hält die Anzahl der DDG-Requests pro Gemeinde klein (kein
# zusätzliches Rate-Limit-Risiko), deckt aber viele kantonale Namenskonventionen ab (z.B. AG
# "Bau- und Nutzungsordnung (BNO)" statt ZH "BZO"). Sprachabhängig, siehe CANTON_LANGUAGE unten -
# Deutschschweiz sucht diese 18 deutschen Begriffe, die welschen/tessiner Kantone die
# französischen/italienischen Pendants.
_SEARCH_TERM_GROUPS_DE = [
    ['Bau- und Zonenordnung', 'BZO', 'Bau- und Nutzungsordnung', 'BNO', 'Baureglement', 'Bauordnung'],
    ['Zonenordnung', 'Zonenreglement', 'Bau- und Zonenreglement', 'Bau- und Planungsreglement',
     'Bau- und Nutzungsreglement', 'Gemeindebaureglement', 'kommunales Baureglement'],
    ['Nutzungsreglement', 'Nutzungsordnung', 'Nutzungsplanung', 'Rahmennutzungsplan',
     'Rahmennutzungsplanung', 'Zonenvorschriften', 'Nutzungsvorschriften'],
]
# Auf dieselbe Breite wie Deutsch (18 Begriffe/3 Gruppen) erweitert - der erste FR-Testlauf mit
# der ursprünglich schmaleren Liste (2 Gruppen/~9 Begriffe) zeigte zwar schon eine gute Quote
# (63%), aber GE/VD/NE/JU/TI blieben in der Gesamtauswertung schwächer; zusätzliche regionale
# Bezeichnungen (v.a. Genf: PAL/PLQ) sollen das weiter verbessern.
_SEARCH_TERM_GROUPS_FR = [
    ['Règlement communal des constructions', 'RCC', 'Règlement de construction',
     "Règlement communal d'urbanisme", 'RCU', "Règlement d'application"],
    ["Plan général d'affectation", 'PGA', "Plan d'affectation communal",
     "Plan d'affectation des zones", 'PAZ', "Règlement du plan d'affectation"],
    ["Plan d'aménagement local", 'PAL', "Plan localisé de quartier", 'PLQ',
     "Règlement de construction et d'aménagement", 'Zone à bâtir'],
]
_SEARCH_TERM_GROUPS_IT = [
    ['Piano regolatore', 'PR', 'Regolamento edilizio', 'REC', 'Regolamento comunale delle costruzioni'],
    ['Norme di attuazione del piano regolatore', 'NAPR', 'Piano regolatore generale', 'PRG',
     'Norme edilizie', 'Zona edificabile'],
]


def _build_queries(term_groups):
    # Gemeindename bewusst NICHT in Anführungszeichen: das war ein Versuch (siehe Git-Historie),
    # um Cross-Gemeinde-Verwechslungen zu reduzieren (z.B. "Kerzers" bekam ein Reglement von
    # Conthey statt dem eigenen) - hat sich aber live als klar schlechter erwiesen. Testlauf
    # Kanton FR mit Quotes: Recall brach von 53/119 (44.5%) auf 4/119 (3.4%) ein, DDG scheint bei
    # einer derart langen Query (Pflicht-Phrase-Name PLUS 5-7 OR-verknüpfte Pflicht-Phrasen-Begriffe)
    # fast komplett leerzulaufen statt präziser zu werden. Der Recall-Verlust wiegt schwerer als
    # die (kleinere) Cross-Gemeinde-Verwechslungsrate, daher zurückgesetzt.
    return [
        '{name} {canton} (' + ' OR '.join(f'"{term}"' for term in group) + ') filetype:pdf'
        for group in term_groups
    ]


SEARCH_QUERIES_DE = _build_queries(_SEARCH_TERM_GROUPS_DE)
SEARCH_QUERIES_FR = _build_queries(_SEARCH_TERM_GROUPS_FR)
SEARCH_QUERIES_IT = _build_queries(_SEARCH_TERM_GROUPS_IT)

# Mehrheitssprache je Kanton für die Suchbegriffe - bewusste Vereinfachung: mehrsprachige
# Kantone (z.B. deutschsprachige Gemeinden in FR/VS) bekommen nur die Mehrheitssprache, statt
# für ALLE Kantone doppelt so viele Requests zu machen (Rate-Limit-Risiko). Nicht gelistete
# Kantone (inkl. BE, GR trotz kleiner nicht-deutscher Minderheiten) bleiben Deutsch.
CANTON_LANGUAGE = {
    'VD': 'fr', 'GE': 'fr', 'NE': 'fr', 'JU': 'fr', 'FR': 'fr', 'VS': 'fr',
    'TI': 'it',
}


def queries_for_canton(canton: str) -> list[str]:
    lang = CANTON_LANGUAGE.get((canton or '').upper())
    if lang == 'fr':
        return SEARCH_QUERIES_FR
    if lang == 'it':
        return SEARCH_QUERIES_IT
    return SEARCH_QUERIES_DE


# Titel-Stichwörter, die auf offensichtliches Rauschen hindeuten statt auf das Reglement selbst -
# im Testlauf beobachtet (z.B. ein Einladungs-Flyer oder ein Bundesgerichtsentscheid, die das
# Suchwort nur zufällig im Text enthalten). Kein Allheilmittel, filtert aber die offensichtlichsten
# Fehltreffer bereits vor dem Download heraus. Bewusst SPRACHUNABHÄNGIG eine einzige Liste (statt
# pro Kanton eine eigene) - die Prüfung läuft für jeden Treffer immer über alle Sprachen, war
# aber bisher nur Deutsch: im FR-Testlauf rutschte z.B. "RAPT DE GESTION 2023" (= Rapport de
# gestion, Geschäftsbericht) durch, weil kein französisches Äquivalent in der Liste stand.
NOISE_TITLE_KEYWORDS = [
    # Deutsch
    'flyer', 'einladung', 'medienmitteilung', 'pressemitteilung', 'newsletter',
    'traktandenliste', 'protokoll', 'jahresbericht', 'geschäftsbericht',
    'bundesgerichtsentscheid', 'gerichtsentscheid', 'wegleitung', 'merkblatt',
    'infobroschüre', 'informationsbroschüre', 'abstimmungsvorlage', 'vernehmlassung',
    'einwendungsbericht', 'agenda',
    # Französisch
    'invitation', 'communiqué de presse', 'ordre du jour', 'procès-verbal',
    "rapport de gestion", "rapport d'activité", 'brochure', 'préavis',
    # Italienisch
    'invito', 'comunicato stampa', "rapporto di gestione", 'rapporto annuale',
    'verbale', 'ordine del giorno', 'opuscolo',
]


def _looks_like_noise(title: str) -> bool:
    if not title:
        return False
    text = title.lower()
    return any(kw in text for kw in NOISE_TITLE_KEYWORDS)


# Analyse des ersten Volllaufs (2110 Gemeinden, siehe data/audit/bzo_ergebnisse.csv) zeigte: von
# 905 als "ok" markierten Downloads waren nur 639 (70%) überhaupt auf einer .ch/.swiss-Domain -
# der Rest war komplett fachfremdes Rauschen (u.a. ein Bank-of-America-Marketing-PDF, OpenAI- und
# Microsoft-CDN-Dateien, eine US-Behördenseite, eine ungarische Werbeagentur, mehrfach ein
# Duke-University-Gesundheitspolitik-PDF) - der OR-verknüpfte Boolean-Query-String wird vom
# DDG-Backend offenbar nicht zuverlässig als Phrasen-Filter respektiert, sondern degeneriert
# teils zu einer laxen "irgendeines der Wörter"-Suche über den gesamten Web-Index. Diese Domain-
# Einschränkung ist der wirksamste einzelne Hebel gegen dieses Rauschen: kein einziger echter
# Treffer im Testlauf lag ausserhalb .ch/.swiss, das Risiko einen echten Treffer zu verlieren ist
# also sehr gering, während es einen grossen Teil der MAX_CANDIDATES_PER_GEMEINDE-Slots freimacht,
# die sonst mit irrelevanten Fremd-PDFs verschwendet wurden.
ALLOWED_TLDS = ('.ch', '.swiss')


def _is_swiss_domain(url: str) -> bool:
    try:
        domain = urlparse(url).netloc.lower()
    except Exception:
        return False
    return domain.endswith(ALLOWED_TLDS)


# Erweiterungspunkt für kantonale Geoportale/Register als Zweitquelle (zuverlässiger als freie
# Websuche, siehe services/geo_zh.py für ein Beispiel bei Zonenparametern). AKTUELL LEER: eine
# echte Integration braucht pro Kanton eine verifizierte, stabile API/URL-Struktur - das wurde für
# dieses Skript (noch) nicht recherchiert, um keinen unverifizierten Endpunkt einzubauen, der im
# Ernstfall einfach stillschweigend nichts liefert. Erweitern per:
#   CANTON_FALLBACK_SOURCES['XX'] = lambda name, canton: [{'title': ..., 'url': ...}, ...]
# Wird in find_pdf_candidates() nur versucht, wenn die Suchmaschinen-Recherche NICHTS gefunden hat.
CANTON_FALLBACK_SOURCES: dict = {}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("bzo_crawler")


def get_gemeinden(canton_filter: str | None = None) -> list[dict]:
    """
    Lädt die aktuelle amtliche Gemeindeliste vom Bundesamt für Statistik (BFS).
    Offizielle REST-Schnittstelle liefert eine 3-stufige Hierarchie OHNE eigene
    Kanton-Spalte: Level 1 = Kanton, Level 2 = Bezirk (bzw. bei Kantonen ohne
    Bezirksunterteilung ein Platzhalter-Eintrag "Kanton ohne Bezirksunterteilung"),
    Level 3 = Gemeinde. Der Kantonscode einer Gemeinde ergibt sich erst über die
    Parent-Kette Gemeinde -> Bezirk -> Kanton (verifiziert gegen die reale API-Antwort:
    26 Kantone, 2121 Gemeinden, 0 unaufgelöste Kantone).
    """
    url = "https://www.agvchapp.bfs.admin.ch/api/communes/snapshot"
    params = {"date": time.strftime("%d-%m-%Y"), "useBfsCode": "true"}
    log.info("Lade aktuelle Gemeindeliste vom BFS...")
    # Kritischer Einstiegspunkt - ohne diese Liste kann der ganze Lauf nicht starten. Bei einer
    # kurzzeitigen serverseitigen Störung (5xx, z.B. 503 "Service Unavailable" - live beobachtet)
    # mit steigender Wartezeit erneut versuchen statt sofort abzubrechen; 4xx-Fehler (z.B. falsche
    # URL) werden NICHT wiederholt, da ein erneuter Versuch dort nichts ändern würde.
    resp = None
    for attempt in range(1, 4):
        try:
            resp = requests.get(url, params=params, headers=HEADERS, timeout=TIMEOUT)
            resp.raise_for_status()
            break
        except requests.exceptions.HTTPError as e:
            if resp is not None and resp.status_code < 500 or attempt == 3:
                raise
            wait = 30 * attempt
            log.warning("BFS-API meldet %s (Versuch %d/3) - warte %ds und versuche erneut.", e, attempt, wait)
            time.sleep(wait)
        except requests.exceptions.RequestException as e:
            if attempt == 3:
                raise
            wait = 30 * attempt
            log.warning("BFS-API nicht erreichbar (Versuch %d/3): %s - warte %ds und versuche erneut.", attempt, e, wait)
            time.sleep(wait)
    # Antwort ist CSV (semikolon- oder komma-separiert, BFS liefert i.d.R. ';')
    text = resp.content.decode("utf-8-sig")
    delimiter = ";" if text.count(";") > text.count(",") else ","
    rows = list(csv.DictReader(io.StringIO(text), delimiter=delimiter))

    canton_short_by_code = {r["HistoricalCode"]: r["ShortName"] for r in rows if r.get("Level") == "1"}
    canton_code_by_bezirk = {r["HistoricalCode"]: r["Parent"] for r in rows if r.get("Level") == "2"}

    gemeinden = []
    for row in rows:
        if row.get("Level") != "3":
            continue
        name = row.get("Name")
        bfs_nr = row.get("BfsCode")
        if not name:
            continue
        kanton_hist_code = canton_code_by_bezirk.get(row.get("Parent"))
        canton = canton_short_by_code.get(kanton_hist_code, "")
        if canton_filter and canton.upper() != canton_filter.upper():
            continue
        gemeinden.append({"name": name.strip(), "canton": canton, "bfs_nr": bfs_nr})
    log.info("Gefunden: %d Gemeinden", len(gemeinden))
    return gemeinden


def _normalize_name(name: str) -> str:
    """Normalisiert Gemeinde-/Dateinamen für den Abgleich: Klammerzusätze (Kantonskürzel bei
    mehrdeutigen Namen, z.B. 'Rickenbach (ZH)') entfernen, dann alles ausser Buchstaben/Zahlen
    weglassen und kleinschreiben - robust gegen Leerzeichen, Bindestriche, Slashes ('Biel/Bienne')
    und die CamelCase-Schreibweise der lokalen Dateinamen (z.B. 'BeinwilAmSee.pdf' für
    'Beinwil am See'). Verifiziert gegen das reale Archiv (1573 Dateien, 21 Kantone)."""
    name = re.sub(r"\([^)]*\)", "", name)
    return re.sub(r"[^0-9A-Za-zÀ-ÿ]", "", name).lower()


def build_local_reglemente_index() -> dict:
    """Scannt data/Reglemente/ und baut einen Lookup (Kanton, normalisierter Gemeindename) ->
    neuestes lokales File. Bei mehreren Dateien pro Gemeinde (Basis + '_ZusatzN'-Ergänzungen)
    zählt für den Datumsvergleich die zuletzt geänderte Datei."""
    index = {}
    if not REGLEMENTE_DIR.exists():
        log.warning("Lokales Reglemente-Archiv nicht gefunden unter %s - Abgleich wird übersprungen.", REGLEMENTE_DIR)
        return index
    for path in REGLEMENTE_DIR.glob("*.pdf"):
        m = re.match(r"^([A-Za-z]{2})_(.+?)(?:_Zusatz\d+)?$", path.stem)
        if not m:
            continue
        canton, rest = m.group(1).upper(), m.group(2)
        key = (canton, _normalize_name(rest))
        current = index.get(key)
        if current is None or path.stat().st_mtime > current.stat().st_mtime:
            index[key] = path
    log.info("Lokales Reglemente-Archiv: %d Gemeinden indexiert.", len(index))
    return index


def compare_with_local(pdf_url: str, local_path: Path) -> str:
    """Vergleicht das Änderungsdatum der Online-Quelle (HTTP HEAD, Last-Modified-Header) mit dem
    lokalen Dateidatum. Realitätscheck: viele Gemeinde-Websites liefern gar keinen Last-Modified-
    Header oder leiten mehrfach um (getestet an echten URLs) - in diesen Fällen 'unbekannt' statt
    einer geratenen Aussage. Liefert 'online_neuer', 'lokal_aktuell' oder 'unbekannt'."""
    try:
        resp = requests.head(pdf_url, headers=HEADERS, timeout=TIMEOUT, allow_redirects=True)
        last_mod = resp.headers.get("Last-Modified")
        if not last_mod:
            return "unbekannt"
        remote_dt = parsedate_to_datetime(last_mod)
        local_dt = datetime.fromtimestamp(local_path.stat().st_mtime, tz=timezone.utc)
        return "online_neuer" if remote_dt > local_dt else "lokal_aktuell"
    except Exception as e:
        log.warning("Last-Modified-Check fehlgeschlagen für %s: %s", pdf_url, e)
        return "unbekannt"


def classify_local_match(local_path: Path | None, pdf_url: str | None) -> str:
    """Fasst den Abgleich mit dem lokalen Archiv in eine der vier Kategorien:
    'kein_online_treffer' (lokal vorhanden, Crawler hat online nichts gefunden),
    'neu_online_gefunden' (lokal noch nichts vorhanden, aber Online-Kandidat gefunden - prüfenswert),
    oder (bei beidem vorhanden) das Ergebnis von compare_with_local()."""
    if local_path and pdf_url:
        return compare_with_local(pdf_url, local_path)
    if local_path and not pdf_url:
        return "kein_online_treffer"
    if not local_path and pdf_url:
        return "neu_online_gefunden"
    return ""


MAX_CANDIDATES_PER_GEMEINDE = 5  # Obergrenze für Downloads/Zeilen pro Gemeinde, gegen Ausreisser
MAX_LANDING_PAGES_PER_GEMEINDE = 3  # Obergrenze für zusätzliche GET-Requests auf Nicht-PDF-Treffer


def _extract_pdf_links_from_html(page_url: str, html_text: str, limit: int = 2) -> list[str]:
    """Extrahiert PDF-Links aus einer HTML-Seite per Regex (kein zusätzlicher bs4-Dependency
    nötig - echtes DOM-Parsing ist für den Zweck nicht nötig). Relative Links werden gegen die
    Seiten-URL aufgelöst."""
    links = []
    for m in re.finditer(r'href=["\']([^"\'#]+?\.pdf)(?:[?#][^"\']*)?["\']', html_text, re.IGNORECASE):
        abs_url = urljoin(page_url, m.group(1))
        if abs_url not in links:
            links.append(abs_url)
        if len(links) >= limit:
            break
    return links


def _fetch_pdf_links_from_page(page_url: str) -> list[str]:
    """Folgt einer Nicht-PDF-Suchtrefferseite (z.B. eine Gemeinde-'Bauverwaltung'-Seite) und
    sucht dort nach direkten PDF-Links - viele echte Reglemente liegen nur einen Klick von der
    Suchtrefferseite entfernt, statt direkt in den Suchergebnissen verlinkt zu sein."""
    try:
        resp = requests.get(page_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        return _extract_pdf_links_from_html(page_url, resp.text)
    except Exception as e:
        log.warning("Landingpage-Abruf fehlgeschlagen für %s: %s", page_url, e)
        return []


def find_pdf_candidates(name: str, canton: str, query_sleep: float = QUERY_SLEEP_SECONDS) -> list[dict]:
    """Sucht per DuckDuckGo nach PDF-Kandidaten für die Gemeinde - über ALLE Suchgruppen (siehe
    queries_for_canton()) hinweg, nicht nur bis zum ersten Treffer, dedupliziert nach URL. Eine
    Gemeinde kann mehrere relevante Dokumente haben (z.B. Baureglement + separater Zonenplan +
    Nachtrag) - die Tabelle in der Dashboard-Seite zeigt dann entsprechend mehrere Zeilen je
    Gemeinde. Nicht-PDF-Treffer werden einmal als Landingpage nachgeladen (siehe
    _fetch_pdf_links_from_page); offensichtliches Rauschen (siehe NOISE_TITLE_KEYWORDS) wird
    verworfen. Liefert je Treffer {'title': <Dokumentname>, 'url': <PDF-URL>}."""
    seen_urls = set()
    candidates = []
    landing_pages_tried = 0
    queries = queries_for_canton(canton)
    with DDGS() as ddgs:
        for query_tpl in queries:
            if len(candidates) >= MAX_CANDIDATES_PER_GEMEINDE:
                break
            query = query_tpl.format(name=name, canton=canton)
            try:
                results = list(ddgs.text(query, max_results=5))
            except Exception as e:
                log.warning("Suche fehlgeschlagen für '%s': %s", query, e)
                continue
            for r in results:
                if len(candidates) >= MAX_CANDIDATES_PER_GEMEINDE:
                    break
                href = r.get("href") or r.get("link") or ""
                title = (r.get("title") or "").strip()
                if not href or href in seen_urls or _looks_like_noise(title) or not _is_swiss_domain(href):
                    continue
                if href.lower().endswith(".pdf"):
                    seen_urls.add(href)
                    # Titel des Suchergebnisses als menschenlesbarer Dokumentname - fällt auf den
                    # Dateinamen aus der URL zurück, falls die Suche keinen Titel liefert.
                    candidates.append({"title": title or Path(urlparse(href).path).stem, "url": href})
                    continue
                # Nicht-PDF-Treffer: als Landingpage versuchen, PDF-Links darauf zu finden -
                # begrenzt, um die Anzahl zusätzlicher Requests pro Gemeinde zu beschränken.
                if landing_pages_tried >= MAX_LANDING_PAGES_PER_GEMEINDE:
                    continue
                landing_pages_tried += 1
                for pdf_url in _fetch_pdf_links_from_page(href):
                    if pdf_url in seen_urls or len(candidates) >= MAX_CANDIDATES_PER_GEMEINDE or not _is_swiss_domain(pdf_url):
                        continue
                    seen_urls.add(pdf_url)
                    candidates.append({"title": title or Path(urlparse(pdf_url).path).stem, "url": pdf_url})
            time.sleep(query_sleep)

    # Kantonaler Geoportal-Fallback nur, wenn die Suchmaschinen-Recherche NICHTS gefunden hat -
    # aktuell für keinen Kanton registriert (siehe CANTON_FALLBACK_SOURCES weiter oben).
    if not candidates:
        fallback = CANTON_FALLBACK_SOURCES.get((canton or '').upper())
        if fallback:
            try:
                for item in fallback(name, canton):
                    if item['url'] not in seen_urls:
                        seen_urls.add(item['url'])
                        candidates.append(item)
            except Exception as e:
                log.warning("Kantonaler Fallback fehlgeschlagen für %s (%s): %s", name, canton, e)

    return candidates


def safe_filename(name: str, url: str, index: int = 1) -> str:
    ext = Path(urlparse(url).path).suffix or ".pdf"
    clean_name = re.sub(r"[^\w\-]+", "_", name).strip("_")
    suffix = "" if index == 1 else f"_{index}"
    return f"{clean_name}{suffix}{ext}"


def download_pdf(url: str, dest: Path) -> bool:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT, stream=True)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "pdf" not in content_type.lower() and not url.lower().endswith(".pdf"):
            log.warning("Kein PDF-Content-Type bei %s (%s)", url, content_type)
        dest.write_bytes(resp.content)
        return True
    except Exception as e:
        log.warning("Download fehlgeschlagen für %s: %s", url, e)
        return False


def _already_processed_bfs(csv_path: Path) -> set:
    """Liest die BFS-Nummern, die bereits in einem früheren (evtl. abgebrochenen) Lauf in der
    Ergebnis-CSV stehen - damit ein erneuter Aufruf nach einem Abbruch (Rechner-Standby, Absturz,
    manueller Stopp) dort fortsetzen kann statt komplett von vorne zu beginnen."""
    if not csv_path.exists():
        return set()
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            return {row["bfs_nr"] for row in csv.DictReader(f) if row.get("bfs_nr")}
    except Exception as e:
        log.warning("Konnte bereits verarbeitete Gemeinden nicht aus %s lesen: %s", csv_path, e)
        return set()


def _not_found_only_bfs(csv_path: Path) -> set:
    """BFS-Nummern, für die es in der CSV AUSSCHLIESSLICH 'not_found'-Zeilen gibt (kein einziger
    Treffer/Downloadversuch) - Kandidaten für --retry-not-found, z.B. nach einer vermuteten
    DDG-Drosselungsphase, in der ganze Gemeinde-Blöcke fälschlich als 'nichts gefunden' endeten."""
    if not csv_path.exists():
        return set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    by_bfs: dict = {}
    for r in rows:
        by_bfs.setdefault(r.get("bfs_nr"), []).append(r.get("status"))
    return {bfs for bfs, statuses in by_bfs.items() if bfs and all(s == "not_found" for s in statuses)}


def _remove_rows_for_bfs(csv_path: Path, bfs_set: set, fieldnames: list) -> None:
    """Entfernt alle Zeilen für die gegebenen BFS-Nummern aus der Ergebnis-CSV (schreibt die Datei
    neu) - genutzt von --retry-not-found, damit die alten 'not_found'-Zeilen nicht neben den neu
    erfassten Zeilen derselben Gemeinde stehen bleiben."""
    if not csv_path.exists() or not bfs_set:
        return
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    kept = [r for r in rows if r.get("bfs_nr") not in bfs_set]
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(kept)


def main():
    parser = argparse.ArgumentParser(description="BZO-Crawler für Schweizer Gemeinden")
    parser.add_argument("--limit", type=int, default=None, help="Nur die ersten N Gemeinden bearbeiten (Testlauf)")
    parser.add_argument("--canton", type=str, default=None, help="Nur diesen Kanton bearbeiten, z.B. ZH")
    parser.add_argument("--sleep", type=float, default=SLEEP_SECONDS, help="Pause zwischen Gemeinden in Sekunden")
    parser.add_argument("--query-sleep", type=float, default=QUERY_SLEEP_SECONDS,
                         help="Pause zwischen den DDG-Suchanfragen innerhalb einer Gemeinde in Sekunden")
    parser.add_argument("--restart", action="store_true",
                         help="Nicht fortsetzen, sondern ALLE Gemeinden erneut bearbeiten - Standard ist Fortsetzen: "
                              "bereits in der Ergebnis-CSV vorhandene Gemeinden werden übersprungen.")
    parser.add_argument("--retry-not-found", action="store_true",
                         help="Nur Gemeinden erneut versuchen, für die es AUSSCHLIESSLICH 'not_found'-Zeilen gibt "
                              "(z.B. nach einer vermuteten DDG-Drosselungsphase) - deren alte Zeilen werden vorher "
                              "entfernt. Ignoriert --restart; --limit/--canton schränken die Zielmenge zusätzlich ein.")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    # document_title: der Name des Dokuments (Suchergebnis-Titel) - pro Gemeinde können mehrere
    # Zeilen entstehen, wenn mehrere passende PDFs gefunden wurden (siehe find_pdf_candidates()).
    fieldnames = ["bfs_nr", "name", "canton", "document_title", "status", "pdf_url", "local_file",
                  "local_reglement_path", "local_comparison"]

    gemeinden = get_gemeinden(canton_filter=args.canton)
    if args.limit:
        gemeinden = gemeinden[: args.limit]

    if args.retry_not_found:
        target_bfs = _not_found_only_bfs(LOG_CSV)
        before = len(gemeinden)
        gemeinden = [g for g in gemeinden if str(g["bfs_nr"]) in target_bfs]
        log.info("Nur Nacherfassung: %d von %d Gemeinden hatten bisher ausschliesslich 'not_found' (%d treffen "
                 "zusätzlich auf --canton/--limit zu). Ihre alten Zeilen werden entfernt und neu versucht.",
                 len(target_bfs), before, len(gemeinden))
        _remove_rows_for_bfs(LOG_CSV, {str(g["bfs_nr"]) for g in gemeinden}, fieldnames)
    elif not args.restart:
        done_bfs = _already_processed_bfs(LOG_CSV)
        if done_bfs:
            before = len(gemeinden)
            gemeinden = [g for g in gemeinden if str(g["bfs_nr"]) not in done_bfs]
            log.info(
                "Fortsetzen: %d von %d Gemeinden bereits in %s vorhanden, werden übersprungen (%d verbleiben). "
                "Mit --restart stattdessen alle erneut bearbeiten.",
                before - len(gemeinden), before, LOG_CSV, len(gemeinden),
            )

    local_index = build_local_reglemente_index()

    file_exists = LOG_CSV.exists()
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()

        for i, g in enumerate(gemeinden, 1):
            candidates = find_pdf_candidates(g["name"], g["canton"], query_sleep=args.query_sleep)
            log.info("[%d/%d] %s (%s) - %d Kandidat(en)", i, len(gemeinden), g["name"], g["canton"], len(candidates))
            local_match = local_index.get((g["canton"], _normalize_name(g["name"])))
            local_path_str = str(local_match) if local_match else ""

            if not candidates:
                writer.writerow({
                    "bfs_nr": g["bfs_nr"], "name": g["name"], "canton": g["canton"],
                    "document_title": "", "status": "not_found", "pdf_url": "", "local_file": "",
                    "local_reglement_path": local_path_str,
                    "local_comparison": classify_local_match(local_match, None),
                })
            else:
                for idx, cand in enumerate(candidates, 1):
                    row = {"bfs_nr": g["bfs_nr"], "name": g["name"], "canton": g["canton"],
                           "document_title": cand["title"], "status": "", "pdf_url": cand["url"], "local_file": "",
                           "local_reglement_path": local_path_str,
                           "local_comparison": classify_local_match(local_match, cand["url"])}
                    fname = safe_filename(g["name"], cand["url"], index=idx)
                    dest = OUTPUT_DIR / fname
                    if download_pdf(cand["url"], dest):
                        row["status"] = "ok"
                        row["local_file"] = str(dest)
                    else:
                        row["status"] = "download_failed"
                    writer.writerow(row)
                    f.flush()

            f.flush()
            time.sleep(args.sleep)

    log.info("Fertig. Ergebnisse in %s, PDFs in %s/", LOG_CSV, OUTPUT_DIR)


if __name__ == "__main__":
    main()
