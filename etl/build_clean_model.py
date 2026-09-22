"""Baut das normalisierte Analytics-Datenmodell (dimensions/facts/bridges/audit) aus data/raw.
Rohdaten werden nur gelesen, nie verändert. Alle Outputs werden aus den Rohdaten neu erzeugt
(deterministisch, reproduzierbar) und liegen als Parquet + DuckDB unter data/.
"""
import hashlib
import re
from datetime import datetime
from pathlib import Path

import duckdb
import pandas as pd

BASE = Path(__file__).resolve().parents[1]
RAW = BASE / 'data' / 'raw'
STAGING = BASE / 'data' / 'staging'
DIM = BASE / 'data' / 'dimensions'
FACT = BASE / 'data' / 'facts'
BRIDGE = BASE / 'data' / 'bridges'
AUDIT = BASE / 'data' / 'audit'
DUCKDB_DIR = BASE / 'data' / 'duckdb'
DUCKDB_PATH = DUCKDB_DIR / 'hslu_ris.duckdb'

CANTON_NAMES = {
    'ZH': 'Zürich', 'BE': 'Bern', 'LU': 'Luzern', 'UR': 'Uri', 'SZ': 'Schwyz',
    'OW': 'Obwalden', 'NW': 'Nidwalden', 'GL': 'Glarus', 'ZG': 'Zug', 'FR': 'Fribourg',
    'SO': 'Solothurn', 'BS': 'Basel-Stadt', 'BL': 'Basel-Landschaft', 'SH': 'Schaffhausen',
    'AR': 'Appenzell Ausserrhoden', 'AI': 'Appenzell Innerrhoden', 'SG': 'St. Gallen',
    'GR': 'Graubünden', 'AG': 'Aargau', 'TG': 'Thurgau', 'TI': 'Ticino', 'VD': 'Vaud',
    'VS': 'Valais', 'NE': 'Neuchâtel', 'GE': 'Genève', 'JU': 'Jura',
}

BOOL_TOKENS = {'True', 'False'}


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode('utf-8')).hexdigest()


def normalize_url(url):
    if url is None:
        return None
    u = url.strip()
    if u == '' or u.lower() == 'none':
        return None
    return u.lower()


def setup_dirs():
    for d in (STAGING, DIM, FACT, BRIDGE, AUDIT, DUCKDB_DIR, BASE / 'docs'):
        d.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# STEP 1: RAW laden
# ---------------------------------------------------------------------------

def load_lu_csv(name):
    """cp1252-encoded lookup CSVs (code;descr;). Reading these via DuckDB's UTF-8
    auto_detect + ignore_errors=true silently DROPS every row containing an umlaut
    (confirmed: fsa_lu 112/203 and cs_code_lu 95/129 rows survived under the old
    pipeline). Reading explicitly as cp1252 with pandas recovers all rows."""
    df = pd.read_csv(RAW / f'{name}.csv', sep=';', encoding='cp1252', usecols=[0, 1],
                      names=['code', 'descr'], header=0)
    df['code'] = pd.to_numeric(df['code'], errors='coerce').astype('Int64')
    df['descr'] = df['descr'].str.strip()
    return df.dropna(subset=['code']).drop_duplicates(subset=['code'])


def parse_law_manager_line(fields):
    """Robust, anchor-based parser for one data row of results_law_Manager_260910.csv.

    The file is ';'-delimited, but free-text author names inside METADATA_ORIGINAL /
    METADATA_DOWNLOADEDFILE (e.g. "author: Elsbeth Bott; Martin Fopp") and some LINKDOC
    URLs contain unescaped ';' characters, which breaks a naive positional split for a
    small number of rows. Instead of splitting by position, this anchors on the 5
    boolean flags (LINKDOC_PRESENT..METADATA_EQUAL) that always appear as literal
    'True'/'False' tokens, and reassembles LINKDOC / the two METADATA blobs from
    whatever sits between the anchors - so embedded ';' never shifts a column.
    """
    issue = None
    front = fields[:5]
    if len(front) < 5:
        return None, 'row has fewer than 5 leading fields'
    gdekt, gdenr, gdename, gdeteil, version = front

    rest = fields[5:]
    window = None
    for i in range(len(rest) - 4):
        if all(rest[i + k] in BOOL_TOKENS for k in range(5)):
            window = i
            break
    if window is None:
        return None, 'could not locate LINKDOC_PRESENT..METADATA_EQUAL boolean anchor'

    linkdoc = ';'.join(rest[:window]) or None
    linkdoc_present, downloaded_pdf_valid, municipality_exists, link_valid, metadata_equal = rest[window:window + 5]
    tail_start = window + 5

    if len(rest) - tail_start < 3:
        return None, 'row too short after boolean anchor for HASH_EQUAL/CRAWLED_LINK/CRAWLED_LINK_SAME'
    hash_equal = rest[-3]
    crawled_link = rest[-2]
    crawled_link_same = rest[-1]
    meta_parts = rest[tail_start:-3]

    if len(meta_parts) == 2:
        metadata_original, metadata_downloaded = meta_parts
    elif len(meta_parts) < 2:
        metadata_original = meta_parts[0] if meta_parts else None
        metadata_downloaded = None
        issue = 'metadata block missing expected 2 fields'
    else:
        joined = ';'.join(meta_parts)
        parts = re.split(r';(?=creationDate:)', joined)
        if len(parts) == 2:
            metadata_original, metadata_downloaded = parts
            issue = 'repaired: embedded ";" inside author field split metadata into >2 raw fields'
        else:
            metadata_original, metadata_downloaded = joined, None
            issue = 'metadata block has >2 raw fields and no unambiguous creationDate anchor'

    def clean_none(v):
        if v is None:
            return None
        v = v.strip()
        return None if v == '' or v.lower() == 'none' else v

    row = dict(
        GDEKT=clean_none(gdekt), GDENR=clean_none(gdenr), GDENAME=clean_none(gdename),
        GDETEIL=clean_none(gdeteil), VERSION=clean_none(version), LINKDOC=clean_none(linkdoc),
        LINKDOC_PRESENT=clean_none(linkdoc_present), DOWNLOADED_PDF_VALID=clean_none(downloaded_pdf_valid),
        MUNICIPALITY_EXISTS=clean_none(municipality_exists), LINK_VALID=clean_none(link_valid),
        METADATA_EQUAL=clean_none(metadata_equal), METADATA_ORIGINAL=clean_none(metadata_original),
        METADATA_DOWNLOADEDFILE=clean_none(metadata_downloaded), HASH_EQUAL=clean_none(hash_equal),
        CRAWLED_LINK=clean_none(crawled_link), CRAWLED_LINK_SAME=clean_none(crawled_link_same),
    )
    return row, issue


def load_law_manager():
    path = RAW / 'results_law_Manager_260910.csv'
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    header, data_lines = lines[0], lines[1:]

    rows, issues = [], []
    for line_no, line in enumerate(data_lines, start=2):
        if not line.strip():
            continue
        fields = line.split(';')
        row, issue = parse_law_manager_line(fields)
        if row is None:
            issues.append({'line': line_no, 'raw_line': line, 'issue': issue})
            continue
        row['source_line'] = line_no
        rows.append(row)
        if issue:
            issues.append({'line': line_no, 'raw_line': line, 'issue': issue})
    df = pd.DataFrame(rows)
    issues_df = pd.DataFrame(issues)
    return df, issues_df


METADATA_RE = re.compile(
    r'creationDate:\s*(?P<creation>.*?),\s*modifcationDate:\s*(?P<mod>.*?),\s*author:\s*(?P<author>.*),\s*size:\s*(?P<size>\d+)\s*$'
)


def parse_metadata(raw):
    if raw is None:
        return None, None, None, None
    m = METADATA_RE.match(raw.strip())
    if not m:
        return None, None, None, None
    creation = m.group('creation').strip() or None
    mod = m.group('mod').strip() or None
    author = m.group('author').strip()
    author = None if author.lower() == 'none' else author
    size = int(m.group('size'))
    return creation, mod, author, size


def load_raw(con):
    con.execute(f"CREATE OR REPLACE TABLE stg_project AS SELECT * FROM read_csv_auto('{(RAW / 'project_level.csv').as_posix()}', header=true, sample_size=-1, ignore_errors=true, null_padding=true)")
    con.execute(f"CREATE OR REPLACE TABLE stg_municipality AS SELECT * FROM read_csv_auto('{(RAW / 'municipality_level.csv').as_posix()}', header=true, sample_size=-1, ignore_errors=true, null_padding=true)")

    for sheet, alias in [('Gemeindedaten', 'stg_ranking_base'), ('Scores', 'stg_ranking_scores'), ('Ranking', 'stg_ranking_ranking'), ('Nachhaltigkeit', 'stg_ranking_nachhaltigkeit')]:
        df = pd.read_excel(RAW / 'HSLU_Gemeinderanking_260811.xlsx', sheet_name=sheet, engine='openpyxl')
        con.register(f'_{alias}', df)
        con.execute(f'CREATE OR REPLACE TABLE {alias} AS SELECT * FROM _{alias}')
        con.unregister(f'_{alias}')

    coords = pd.read_excel(RAW / 'gemeinden_koordinaten.xlsx', sheet_name='Tabelle1', engine='openpyxl')
    con.register('_coords', coords)
    con.execute('CREATE OR REPLACE TABLE stg_coordinates AS SELECT * FROM _coords')
    con.unregister('_coords')

    for name in ('fsa_lu', 'devtype_lu', 'tenure_lu', 'cs_code_lu'):
        df = load_lu_csv(name)
        con.register(f'_{name}', df)
        con.execute(f'CREATE OR REPLACE TABLE stg_{name} AS SELECT * FROM _{name}')
        con.unregister(f'_{name}')

    law_df, law_issues_df = load_law_manager()
    con.register('_law', law_df)
    con.execute('CREATE OR REPLACE TABLE stg_law_manager AS SELECT * FROM _law')
    con.unregister('_law')
    return law_issues_df


# ---------------------------------------------------------------------------
# STEP 2: Deduplizieren
# ---------------------------------------------------------------------------

def dedupe_report(con):
    proj_dupes = con.execute('SELECT PROJID, count(*) n FROM stg_project GROUP BY PROJID HAVING count(*)>1').fetchdf()
    exact_dupes = con.execute('SELECT count(*) - count(DISTINCT stg_project) AS n FROM stg_project').fetchone()[0]
    law_dupes = con.execute('SELECT GDENR, GDETEIL, LINKDOC, count(*) n FROM stg_law_manager GROUP BY 1,2,3 HAVING count(*)>1').fetchdf()

    rows = []
    for _, r in proj_dupes.iterrows():
        rows.append({'table': 'stg_project', 'key': f"PROJID={r['PROJID']}", 'row_count': r['n'], 'type': 'duplicate_PROJID'})
    if exact_dupes:
        rows.append({'table': 'stg_project', 'key': 'ALL_COLUMNS', 'row_count': exact_dupes, 'type': 'exact_duplicate_rows'})
    for _, r in law_dupes.iterrows():
        rows.append({'table': 'stg_law_manager', 'key': f"GDENR={r['GDENR']},GDETEIL={r['GDETEIL']},LINKDOC={r['LINKDOC']}", 'row_count': r['n'], 'type': 'duplicate_law_row'})
    if not rows:
        rows.append({'table': 'ALL', 'key': None, 'row_count': 0, 'type': 'NO_DUPLICATES_FOUND'})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# STEP 3-5: Normalisieren, Dimensionen, Fakten
# ---------------------------------------------------------------------------

def build_dim_municipality(con):
    con.execute("""
        CREATE OR REPLACE TABLE _bfs_union AS
        SELECT DISTINCT TRY_CAST(BFS AS INTEGER) bfs FROM stg_project WHERE BFS IS NOT NULL
        UNION SELECT DISTINCT TRY_CAST(BFS AS INTEGER) FROM stg_municipality WHERE BFS IS NOT NULL
        UNION SELECT DISTINCT TRY_CAST(BFS AS INTEGER) FROM stg_ranking_base WHERE BFS IS NOT NULL
        UNION SELECT DISTINCT TRY_CAST(BFS AS INTEGER) FROM stg_coordinates WHERE BFS IS NOT NULL
        UNION SELECT DISTINCT TRY_CAST(GDENR AS INTEGER) FROM stg_law_manager WHERE GDENR IS NOT NULL
    """)
    con.execute("""
        CREATE OR REPLACE TABLE dim_municipality AS
        SELECT
          dense_rank() OVER (ORDER BY u.bfs) AS municipality_id,
          u.bfs AS bfs_number,
          COALESCE(r.Gemeindename, c.Gemeindename, lm.gdename, 'UNKNOWN') AS municipality_name,
          COALESCE(r.Kanton, c.Kanton, lm.gdekt) AS canton_code
        FROM _bfs_union u
        LEFT JOIN (SELECT DISTINCT BFS, Gemeindename, Kanton FROM stg_ranking_base) r ON r.BFS=u.bfs
        LEFT JOIN (SELECT DISTINCT BFS, Gemeindename, Kanton FROM stg_coordinates) c ON c.BFS=u.bfs
        LEFT JOIN (SELECT DISTINCT GDENR, first(GDENAME) AS gdename, first(GDEKT) AS gdekt FROM stg_law_manager WHERE GDENR IS NOT NULL GROUP BY GDENR) lm ON lm.GDENR=u.bfs
    """)


def build_dim_canton(con):
    codes = con.execute('SELECT DISTINCT canton_code FROM dim_municipality WHERE canton_code IS NOT NULL ORDER BY canton_code').fetchdf()['canton_code'].tolist()
    df = pd.DataFrame({'canton_code': codes})
    df['canton_name'] = df['canton_code'].map(CANTON_NAMES)
    df.insert(0, 'canton_id', range(1, len(df) + 1))
    con.register('_dim_canton', df)
    con.execute('CREATE OR REPLACE TABLE dim_canton AS SELECT * FROM _dim_canton')
    con.unregister('_dim_canton')
    con.execute("""
        CREATE OR REPLACE TABLE dim_municipality AS
        SELECT m.municipality_id, m.bfs_number, m.municipality_name, c.canton_id
        FROM dim_municipality m LEFT JOIN dim_canton c ON c.canton_code = m.canton_code
    """)


def build_dim_municipality_part(con):
    con.execute("""
        CREATE OR REPLACE TABLE dim_municipality_part AS
        SELECT
          dense_rank() OVER (ORDER BY m.municipality_id, p.gdeteil) AS municipality_part_id,
          m.municipality_id,
          p.gdeteil AS municipality_part_name
        FROM (
          SELECT DISTINCT TRY_CAST(GDENR AS INTEGER) bfs, GDETEIL AS gdeteil
          FROM stg_law_manager WHERE GDETEIL IS NOT NULL AND trim(GDETEIL) <> ''
        ) p
        JOIN dim_municipality m ON m.bfs_number = p.bfs
    """)


def build_dim_zone(con):
    con.execute("""
        CREATE OR REPLACE TABLE dim_zone (
          zone_id INTEGER, municipality_id INTEGER, zone_name VARCHAR,
          zone_area_m2 DOUBLE, zone_geometry VARCHAR
        )
    """)


def build_dim_fsa(con):
    con.execute("""
        CREATE OR REPLACE TABLE dim_fsa AS
        SELECT code AS fsa_code, descr AS fsa_description FROM stg_fsa_lu
    """)


def build_dim_devtype(con):
    con.execute("""
        CREATE OR REPLACE TABLE dim_devtype AS
        SELECT code AS devtype_code, descr AS devtype_description FROM stg_devtype_lu
    """)


def build_law_documents(con):
    df = con.execute('SELECT * FROM stg_law_manager').fetchdf()
    df['normalized_url'] = df['LINKDOC'].apply(normalize_url)
    df['VERSION_DATE'] = pd.to_datetime(df['VERSION'], format='%Y%m%d', errors='coerce')

    docs = df.dropna(subset=['normalized_url']).groupby('normalized_url').agg(
        canonical_url=('normalized_url', 'first'),
        first_seen_at=('VERSION_DATE', 'min'),
        last_seen_at=('VERSION_DATE', 'max'),
    ).reset_index(drop=True)
    docs['law_document_id'] = docs['canonical_url'].apply(sha256_hex)
    docs['source_system'] = 'law_manager'
    docs = docs[['law_document_id', 'canonical_url', 'source_system', 'first_seen_at', 'last_seen_at']]
    con.register('_dim_law_document', docs)
    con.execute('CREATE OR REPLACE TABLE dim_law_document AS SELECT * FROM _dim_law_document')
    con.unregister('_dim_law_document')

    df['law_document_id'] = df['normalized_url'].apply(lambda u: sha256_hex(u) if u else None)
    df['document_version_id'] = df.apply(
        lambda r: sha256_hex(f"{r['law_document_id']}|{r['VERSION']}") if r['law_document_id'] and r['VERSION'] else None, axis=1)

    parsed_orig = df['METADATA_ORIGINAL'].apply(parse_metadata)
    parsed_dl = df['METADATA_DOWNLOADEDFILE'].apply(parse_metadata)
    df[['original_creation_date', 'original_modification_date', 'original_author', 'original_file_size']] = pd.DataFrame(parsed_orig.tolist(), index=df.index)
    df[['downloaded_creation_date', 'downloaded_modification_date', 'downloaded_author', 'downloaded_file_size']] = pd.DataFrame(parsed_dl.tolist(), index=df.index)

    versions = df.dropna(subset=['document_version_id']).drop_duplicates(subset=['document_version_id'])[[
        'document_version_id', 'law_document_id', 'VERSION',
        'original_creation_date', 'original_modification_date', 'original_author', 'original_file_size',
        'downloaded_creation_date', 'downloaded_modification_date', 'downloaded_author', 'downloaded_file_size',
        'METADATA_ORIGINAL', 'METADATA_DOWNLOADEDFILE',
    ]].rename(columns={'VERSION': 'source_version', 'METADATA_ORIGINAL': 'original_metadata_raw', 'METADATA_DOWNLOADEDFILE': 'downloaded_metadata_raw'})
    con.register('_dim_document_version', versions)
    con.execute('CREATE OR REPLACE TABLE dim_document_version AS SELECT * FROM _dim_document_version')
    con.unregister('_dim_document_version')
    return df


def classify_validation_status(row):
    def b(v):
        return None if pd.isna(v) else (v == 'True')
    municipality_exists = b(row['MUNICIPALITY_EXISTS'])
    linkdoc_present = b(row['LINKDOC_PRESENT'])
    link_valid = b(row['LINK_VALID'])
    pdf_valid = b(row['DOWNLOADED_PDF_VALID'])
    crawled_same = b(row['CRAWLED_LINK_SAME'])
    crawled_link = row['CRAWLED_LINK']
    hash_equal = b(row['HASH_EQUAL'])
    metadata_equal = b(row['METADATA_EQUAL'])

    if municipality_exists is False:
        return 'MUNICIPALITY_MISMATCH'
    if linkdoc_present is False or link_valid is False:
        return 'INVALID_LINK'
    if pdf_valid is False:
        return 'INVALID_PDF'
    # CRAWLED_LINK_SAME=False is only meaningful when a crawled_link was actually
    # recorded; in this dataset CRAWLED_LINK is always empty, so a bare False there
    # is a "not compared" placeholder, not a detected redirect.
    if pd.notna(crawled_link) and crawled_same is False:
        return 'CRAWLER_REDIRECT'
    if hash_equal is False:
        return 'CONTENT_CHANGED'
    if metadata_equal is False:
        return 'METADATA_CHANGED'
    if any(v is None for v in (municipality_exists, linkdoc_present, link_valid, pdf_valid, hash_equal, metadata_equal)):
        return 'REVIEW_REQUIRED'
    return 'VALID'


def build_fact_document_validation(con, law_df):
    dim_m = con.execute('SELECT municipality_id, bfs_number FROM dim_municipality').fetchdf()
    dim_p = con.execute('SELECT municipality_part_id, municipality_id, municipality_part_name FROM dim_municipality_part').fetchdf()

    df = law_df.copy()
    df['bfs'] = pd.to_numeric(df['GDENR'], errors='coerce')
    df = df.merge(dim_m, left_on='bfs', right_on='bfs_number', how='left')
    df = df.merge(dim_p.rename(columns={'municipality_part_name': 'GDETEIL'}), on=['municipality_id', 'GDETEIL'], how='left')

    df['validation_status'] = df.apply(classify_validation_status, axis=1)
    df['validation_id'] = range(1, len(df) + 1)

    out = df[['validation_id', 'document_version_id', 'municipality_id', 'municipality_part_id',
              'LINKDOC_PRESENT', 'DOWNLOADED_PDF_VALID', 'MUNICIPALITY_EXISTS', 'LINK_VALID',
              'METADATA_EQUAL', 'HASH_EQUAL', 'CRAWLED_LINK_SAME', 'CRAWLED_LINK', 'validation_status']].rename(columns={
        'LINKDOC_PRESENT': 'linkdoc_present', 'DOWNLOADED_PDF_VALID': 'downloaded_pdf_valid',
        'MUNICIPALITY_EXISTS': 'municipality_exists', 'LINK_VALID': 'link_valid',
        'METADATA_EQUAL': 'metadata_equal', 'HASH_EQUAL': 'hash_equal',
        'CRAWLED_LINK_SAME': 'crawled_link_same', 'CRAWLED_LINK': 'crawled_link',
    })
    for c in ('linkdoc_present', 'downloaded_pdf_valid', 'municipality_exists', 'link_valid', 'metadata_equal', 'hash_equal', 'crawled_link_same'):
        out[c] = out[c].map({'True': True, 'False': False})

    con.register('_fact_document_validation', out)
    con.execute('CREATE OR REPLACE TABLE fact_document_validation AS SELECT * FROM _fact_document_validation')
    con.unregister('_fact_document_validation')
    return df


def build_bridge_municipality_law(con, law_df):
    df = law_df.dropna(subset=['law_document_id']).copy()

    bridge = df[['municipality_id', 'municipality_part_id', 'law_document_id', 'document_version_id']].drop_duplicates().reset_index(drop=True)
    bridge.insert(0, 'municipality_law_id', range(1, len(bridge) + 1))
    con.register('_bridge_municipality_law', bridge)
    con.execute('CREATE OR REPLACE TABLE bridge_municipality_law AS SELECT * FROM _bridge_municipality_law')
    con.unregister('_bridge_municipality_law')


def build_fact_project(con):
    con.execute("""
        CREATE OR REPLACE TABLE fact_project AS
        SELECT
          TRY_CAST(PROJID AS BIGINT) AS PROJID,
          TRY_CAST(BFS AS INTEGER) AS BFS,
          TRY_CAST(EGID AS BIGINT) AS EGID,
          TRY_CAST(PLANNING_APPLICATION AS DATE) AS applied_date,
          TRY_CAST(PLANS_APPROVED AS DATE) AS approved_date,
          TRY_CAST(processing_days AS DOUBLE) AS processing_days,
          CAST(NULL AS DOUBLE) AS apartments,
          CAST(NULL AS DOUBLE) AS storeys,
          CAST(NULL AS DOUBLE) AS floorarea,
          CAST(NULL AS DOUBLE) AS volume,
          CAST(NULL AS VARCHAR) AS project_name,
          CAST(NULL AS VARCHAR) AS town
        FROM stg_project
    """)


def build_fact_municipality(con):
    con.execute("""
        CREATE OR REPLACE TABLE fact_municipality AS
        SELECT
          m.municipality_id,
          r.n_projects_2021_2024 AS n_projects,
          r.mean_duration, r.median_duration, r.sd_duration,
          r.share_gt_180, r.share_gt_365,
          ml.complexity_index_raw, ml.build_density
        FROM dim_municipality m
        LEFT JOIN stg_ranking_base r ON r.BFS = m.bfs_number
        LEFT JOIN stg_municipality ml ON TRY_CAST(ml.BFS AS INTEGER) = m.bfs_number
    """)


def build_fact_ranking(con):
    con.execute("""
        CREATE OR REPLACE TABLE fact_ranking AS
        SELECT
          m.municipality_id,
          rk.rank_gesamt_peer AS peer_rank,
          rk.score_prozess AS process_score,
          rk.score_reglement_complexity AS regulation_score,
          rk.score_markt AS market_score,
          rk.score_gesamt_weighted AS overall_score
        FROM dim_municipality m
        JOIN stg_ranking_ranking rk ON rk.BFS = m.bfs_number
    """)


def build_fact_regulation(con):
    con.execute("""
        CREATE OR REPLACE TABLE _current_doc_version AS
        SELECT municipality_id, document_version_id FROM (
          SELECT bl.municipality_id, bl.document_version_id,
                 row_number() OVER (PARTITION BY bl.municipality_id ORDER BY dv.source_version DESC) rn
          FROM bridge_municipality_law bl
          JOIN dim_document_version dv ON dv.document_version_id = bl.document_version_id
          WHERE bl.municipality_part_id IS NULL
        ) WHERE rn = 1
    """)
    con.execute("""
        CREATE OR REPLACE TABLE fact_regulation AS
        SELECT
          m.municipality_id,
          CAST(NULL AS INTEGER) AS municipality_part_id,
          cdv.document_version_id,
          ml.complexity_index_raw,
          r.Intervention_count AS intervention_count,
          r.Architektur_count AS architecture_count,
          r.Wohnen_count AS housing_count,
          r.Verdichtung_count AS densification_count,
          -- Sub-Kategorien (Stichwort-Häufigkeiten im Reglementstext, siehe RIS_Data
          -- Dictionary_260910.docx) - summieren sich exakt zu Verdichtung_count/Wohnen_count,
          -- bisher ungenutzt im Modell, jetzt für die Detailaufschlüsselung pro Gemeinde ergänzt.
          r.Verdichtung_leitbild_count AS densification_leitbild_count,
          r.Verdichtung_aktivierung_count AS densification_aktivierung_count,
          r.Verdichtung_mindest_count AS densification_mindest_count,
          r.Verdichtung_bonus_count AS densification_bonus_count,
          r.Verdichtung_auflagen_count AS densification_auflagen_count,
          r.Wohnen_bezahlbarkeit_count AS housing_bezahlbarkeit_count,
          r.Wohnen_nutzung_count AS housing_nutzung_count,
          r.Wohnen_erschliessung_count AS housing_erschliessung_count,
          r.document_age_2024 AS document_age
        FROM dim_municipality m
        LEFT JOIN stg_ranking_base r ON r.BFS = m.bfs_number
        LEFT JOIN stg_municipality ml ON TRY_CAST(ml.BFS AS INTEGER) = m.bfs_number
        LEFT JOIN _current_doc_version cdv ON cdv.municipality_id = m.municipality_id
        WHERE r.BFS IS NOT NULL
    """)


def build_bridges_fsa_devtype(con):
    fsa_cols = ", ".join(f"CAST(FSACODE_{i} AS VARCHAR) FSACODE_{i}" for i in range(1, 13))
    con.execute(f"""
        CREATE OR REPLACE TABLE bridge_project_fsa AS
        SELECT TRY_CAST(PROJID AS BIGINT) PROJID, TRY_CAST(code AS INTEGER) FSA_CODE,
               TRY_CAST(regexp_extract(source_column,'[0-9]+') AS INTEGER) "POSITION",
               (regexp_extract(source_column,'[0-9]+')='1') AS IS_PRIMARY
        FROM (UNPIVOT (SELECT PROJID, {fsa_cols} FROM stg_project) ON COLUMNS(c -> c LIKE 'FSACODE_%') INTO NAME source_column VALUE code)
        WHERE code IS NOT NULL
    """)
    con.execute("""
        CREATE OR REPLACE TABLE bridge_project_devtype AS
        SELECT TRY_CAST(PROJID AS BIGINT) PROJID, TRY_CAST(code AS INTEGER) DEVTYPE,
               TRY_CAST(regexp_extract(source_column,'[0-9]+') AS INTEGER) "POSITION",
               (regexp_extract(source_column,'[0-9]+')='1') AS IS_PRIMARY
        FROM (UNPIVOT (SELECT PROJID, CAST(DEVTYPE_1 AS VARCHAR) DEVTYPE_1 FROM stg_project) ON COLUMNS(c -> c LIKE 'DEVTYPE_%') INTO NAME source_column VALUE code)
        WHERE code IS NOT NULL
    """)


def build_bridge_project_zone(con):
    con.execute("""
        CREATE OR REPLACE TABLE bridge_project_zone (PROJID BIGINT, ZONE_ID INTEGER)
    """)


# ---------------------------------------------------------------------------
# STEP 6-7: Audit
# ---------------------------------------------------------------------------

def build_audit_files(con, law_issues_df, dup_df):
    dup_df.to_csv(AUDIT / 'duplicate_register.csv', index=False)
    law_issues_df.to_csv(AUDIT / 'law_document_issues.csv', index=False)

    orphan_bfs_project = con.execute("""
        SELECT DISTINCT TRY_CAST(p.BFS AS INTEGER) bfs FROM stg_project p
        LEFT JOIN dim_municipality m ON m.bfs_number = TRY_CAST(p.BFS AS INTEGER)
        WHERE m.municipality_id IS NULL AND p.BFS IS NOT NULL
    """).fetchdf()
    canton_unmapped = con.execute("""
        SELECT canton_code FROM dim_canton WHERE canton_name IS NULL
    """).fetchdf()
    mapping_rows = []
    for _, r in orphan_bfs_project.iterrows():
        mapping_rows.append({'issue': 'orphan_bfs_in_project', 'value': r['bfs']})
    for _, r in canton_unmapped.iterrows():
        mapping_rows.append({'issue': 'unmapped_canton_code', 'value': r['canton_code']})
    pd.DataFrame(mapping_rows).to_csv(AUDIT / 'municipality_mapping_issues.csv', index=False)

    shared_docs = con.execute("""
        SELECT law_document_id, count(DISTINCT municipality_id) n_municipalities, count(*) n_refs
        FROM bridge_municipality_law GROUP BY law_document_id HAVING count(DISTINCT municipality_id) > 1
        ORDER BY n_municipalities DESC
    """).fetchdf()
    multi_version = con.execute("""
        SELECT law_document_id, count(*) n_versions FROM dim_document_version
        GROUP BY law_document_id HAVING count(*) > 1
    """).fetchdf()
    conflicts = con.execute("""
        SELECT dv.document_version_id, dv.law_document_id
        FROM fact_document_validation v JOIN dim_document_version dv ON dv.document_version_id = v.document_version_id
        WHERE v.metadata_equal = false OR v.hash_equal = false
    """).fetchdf()
    conf_rows = []
    for _, r in shared_docs.iterrows():
        conf_rows.append({'type': 'document_shared_across_municipalities', 'law_document_id': r['law_document_id'], 'detail': f"{r['n_municipalities']} municipalities, {r['n_refs']} references"})
    for _, r in multi_version.iterrows():
        conf_rows.append({'type': 'multiple_document_versions', 'law_document_id': r['law_document_id'], 'detail': f"{r['n_versions']} versions"})
    for _, r in conflicts.iterrows():
        conf_rows.append({'type': 'metadata_or_hash_conflict', 'law_document_id': r['law_document_id'], 'detail': f"document_version_id={r['document_version_id']}"})
    pd.DataFrame(conf_rows).to_csv(AUDIT / 'document_version_conflicts.csv', index=False)

    build_quality_report(con, law_issues_df)


def build_quality_report(con, law_issues_df):
    nulls_project = con.execute("SELECT sum(CASE WHEN BFS IS NULL THEN 1 ELSE 0 END) null_bfs, sum(CASE WHEN PLANS_APPROVED IS NULL THEN 1 ELSE 0 END) null_approved, count(*) n FROM stg_project").fetchdf()
    invalid_links = con.execute("SELECT count(*) n FROM fact_document_validation WHERE link_valid = false").fetchdf()
    invalid_pdfs = con.execute("SELECT count(*) n FROM fact_document_validation WHERE downloaded_pdf_valid = false").fetchdf()
    metadata_conflicts = con.execute("SELECT count(*) n FROM fact_document_validation WHERE metadata_equal = false").fetchdf()
    hash_conflicts = con.execute("SELECT count(*) n FROM fact_document_validation WHERE hash_equal = false").fetchdf()
    shared_docs = con.execute("SELECT count(*) n FROM (SELECT law_document_id FROM bridge_municipality_law GROUP BY law_document_id HAVING count(DISTINCT municipality_id)>1)").fetchdf()
    identical_urls = con.execute("SELECT count(*) n FROM dim_law_document").fetchdf()
    multi_url_per_muni = con.execute("SELECT count(*) n FROM (SELECT municipality_id FROM bridge_municipality_law GROUP BY municipality_id HAVING count(DISTINCT law_document_id)>1)").fetchdf()
    multi_versions = con.execute("SELECT count(*) n FROM (SELECT law_document_id FROM dim_document_version GROUP BY law_document_id HAVING count(*)>1)").fetchdf()
    unparseable = len(law_issues_df)
    status_counts = con.execute("SELECT validation_status, count(*) n FROM fact_document_validation GROUP BY 1 ORDER BY 2 DESC").fetchdf()

    summary = pd.DataFrame([
        {'metric': 'project rows total', 'value': int(nulls_project['n'][0])},
        {'metric': 'project rows with NULL BFS', 'value': int(nulls_project['null_bfs'][0])},
        {'metric': 'project rows with NULL approved_date', 'value': int(nulls_project['null_approved'][0])},
        {'metric': 'invalid links', 'value': int(invalid_links['n'][0])},
        {'metric': 'invalid PDFs', 'value': int(invalid_pdfs['n'][0])},
        {'metric': 'metadata conflicts (METADATA_EQUAL=False)', 'value': int(metadata_conflicts['n'][0])},
        {'metric': 'hash conflicts (HASH_EQUAL=False, informational)', 'value': int(hash_conflicts['n'][0])},
        {'metric': 'documents shared across >=2 municipalities', 'value': int(shared_docs['n'][0])},
        {'metric': 'distinct documents (identical URLs deduplicated)', 'value': int(identical_urls['n'][0])},
        {'metric': 'municipalities with >1 distinct document URL', 'value': int(multi_url_per_muni['n'][0])},
        {'metric': 'documents with >1 version', 'value': int(multi_versions['n'][0])},
        {'metric': 'law_manager rows with unparseable/repaired metadata', 'value': unparseable},
    ])
    with pd.ExcelWriter(AUDIT / 'data_quality_report.xlsx', engine='openpyxl') as writer:
        summary.to_excel(writer, sheet_name='Summary', index=False)
        status_counts.to_excel(writer, sheet_name='ValidationStatus', index=False)
        law_issues_df.to_excel(writer, sheet_name='UnparseableRows', index=False)


# ---------------------------------------------------------------------------
# STEP 9: Views
# ---------------------------------------------------------------------------

def create_views(con):
    con.execute("""
        CREATE OR REPLACE VIEW vw_project_municipality AS
        SELECT p.*, m.municipality_name, m.canton_id
        FROM fact_project p LEFT JOIN dim_municipality m ON m.bfs_number = p.BFS
    """)
    con.execute("""
        CREATE OR REPLACE VIEW vw_municipality_regulation AS
        SELECT m.municipality_id, m.municipality_name, fr.*
        FROM dim_municipality m LEFT JOIN fact_regulation fr USING (municipality_id)
    """)
    con.execute("""
        CREATE OR REPLACE VIEW vw_project_municipality_regulation AS
        SELECT pm.*, mr.complexity_index_raw, mr.intervention_count, mr.architecture_count,
               mr.housing_count, mr.densification_count, mr.document_age
        FROM vw_project_municipality pm
        LEFT JOIN (SELECT m.bfs_number, fr.* FROM dim_municipality m JOIN fact_regulation fr USING (municipality_id)) mr
          ON mr.bfs_number = pm.BFS
    """)
    con.execute("""
        CREATE OR REPLACE VIEW vw_current_law_document AS
        SELECT bl.municipality_id, bl.municipality_part_id, dv.document_version_id, dv.law_document_id,
               ld.canonical_url, dv.source_version
        FROM bridge_municipality_law bl
        JOIN dim_document_version dv ON dv.document_version_id = bl.document_version_id
        JOIN dim_law_document ld ON ld.law_document_id = dv.law_document_id
        QUALIFY row_number() OVER (PARTITION BY bl.municipality_id, bl.municipality_part_id ORDER BY dv.source_version DESC) = 1
    """)
    con.execute("""
        CREATE OR REPLACE VIEW vw_document_validation_issues AS
        SELECT * FROM fact_document_validation WHERE validation_status NOT IN ('VALID')
    """)
    con.execute("""
        CREATE OR REPLACE VIEW vw_regulation_quality AS
        SELECT fr.*, dvi.validation_status
        FROM fact_regulation fr
        LEFT JOIN fact_document_validation dvi ON dvi.document_version_id = fr.document_version_id
    """)


# ---------------------------------------------------------------------------
# STEP 10: Parquet export
# ---------------------------------------------------------------------------

TABLE_TARGETS = {
    'staging': ['stg_project', 'stg_municipality', 'stg_ranking_base', 'stg_ranking_scores', 'stg_ranking_ranking',
                'stg_ranking_nachhaltigkeit', 'stg_coordinates', 'stg_fsa_lu', 'stg_devtype_lu', 'stg_tenure_lu',
                'stg_cs_code_lu', 'stg_law_manager'],
    'dimensions': ['dim_canton', 'dim_municipality', 'dim_municipality_part', 'dim_zone', 'dim_fsa', 'dim_devtype',
                   'dim_law_document', 'dim_document_version'],
    'facts': ['fact_project', 'fact_municipality', 'fact_ranking', 'fact_regulation', 'fact_document_validation'],
    'bridges': ['bridge_project_fsa', 'bridge_project_devtype', 'bridge_project_zone', 'bridge_municipality_law'],
}
DIR_FOR = {'staging': STAGING, 'dimensions': DIM, 'facts': FACT, 'bridges': BRIDGE}


def export_parquet(con):
    for group, tables in TABLE_TARGETS.items():
        out_dir = DIR_FOR[group]
        for t in tables:
            con.execute(f"COPY {t} TO '{(out_dir / (t + '.parquet')).as_posix()}' (FORMAT PARQUET)")


def main():
    setup_dirs()
    con = duckdb.connect(str(DUCKDB_PATH))

    law_issues_df = load_raw(con)
    dup_df = dedupe_report(con)

    build_dim_municipality(con)
    build_dim_canton(con)
    build_dim_municipality_part(con)
    build_dim_zone(con)
    build_dim_fsa(con)
    build_dim_devtype(con)

    law_df = build_law_documents(con)
    law_df = build_fact_document_validation(con, law_df)
    build_bridge_municipality_law(con, law_df)

    build_fact_project(con)
    build_fact_municipality(con)
    build_fact_ranking(con)
    build_fact_regulation(con)

    build_bridges_fsa_devtype(con)
    build_bridge_project_zone(con)

    build_audit_files(con, law_issues_df, dup_df)
    create_views(con)
    con.execute('DROP TABLE IF EXISTS _bfs_union')
    con.execute('DROP TABLE IF EXISTS _current_doc_version')
    export_parquet(con)

    con.execute("CREATE OR REPLACE TABLE etl_metadata AS SELECT current_timestamp run_at, ? raw_dir", [str(RAW)])
    con.close()
    print(f'[FERTIG] {DUCKDB_PATH}')


if __name__ == '__main__':
    main()
