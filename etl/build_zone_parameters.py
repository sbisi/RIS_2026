"""Extrahiert die Zonenparameter (Ausnützungsziffer, Gebäudehöhe, Grenzabstand usw.) aus
data_hslu260312.csv - der ~269k-zeiligen, projektgranularen Detaildatei (ein Detaillevel
unter project_level.csv) - und aggregiert sie auf Gemeinde+Zone-Ebene.

Wird separat von etl/build_clean_model.py ausgeführt, da diese Rohdatei nicht Teil der
ursprünglichen vier Kern-Dateien war. Ergänzt data/duckdb/hslu_ris.duckdb um:
  - stg_project_zone_parameters (Projekt-Granularität, nur die relevanten Spalten)
  - dim_zone_parameter (aggregiert auf Gemeinde+Zone, für die Parzellen-Seite)

Werte bleiben als Rohtext erhalten (nicht in float geparst): einzelne Zellen enthalten
Mehrfachwerte ("10; 7") oder Vergleichsoperatoren ("≥6", "≤15") - eine numerische
Vereinfachung würde echte regulatorische Nuancen verlieren.
"""
import re
import unicodedata
from pathlib import Path

import duckdb

BASE = Path(__file__).resolve().parents[1]
RAW_FILE = BASE / 'data' / 'raw' / 'data_hslu260312.csv'
DUCKDB_PATH = BASE / 'data' / 'duckdb' / 'hslu_ris.duckdb'
STAGING_DIR = BASE / 'data' / 'staging'
DIM_DIR = BASE / 'data' / 'dimensions'

PARAM_TYPES = [
    'Abstand Strasse', 'Ausnützungsziffer', 'Bachabstand', 'Baumassenziffer', 'Bonus, Ausnützung',
    'Fassadenhöhe: giebelseitig', 'Fassadenhöhe: traufseitig', 'Fassadenhöhe', 'Firsthöhe',
    'Freiflächenziffer', 'Fussgängerwege, Abstand', 'Gebäudeabstand', 'Gebäudebreite',
    'Gebäudehöhe', 'Gebäudelänge', 'Gesamtausnützung', 'Geschossflächenziffer', 'Geschosse',
    'Gestaltungsplanbonus', 'grosser Grenzabstand', 'kleiner Grenzabstand', 'Grenzabstand',
    'Mehrhöhenzuschlag', 'Mehrlängenzuschlag', 'Überbauungsziffer', 'Untergeschosse',
    'Waldabstand', 'Wohnanteil',
]
VARIANTS = ['standard', 'bonus', 'arealüberbauung']


def slugify(name):
    ascii_name = (name.replace('ä', 'ae').replace('ö', 'oe').replace('ü', 'ue').replace('ß', 'ss')
                  .replace('Ä', 'Ae').replace('Ö', 'Oe').replace('Ü', 'Ue'))
    ascii_name = unicodedata.normalize('NFKD', ascii_name).encode('ascii', 'ignore').decode()
    return re.sub(r'[^a-z0-9]+', '_', ascii_name.lower()).strip('_')


def find_param_columns(all_columns):
    """Matched Roh-Spaltennamen den 27 Zonenparameter-Typen zu; längere Präfixe (z.B.
    'grosser Grenzabstand') zuerst, damit sie nicht vom kürzeren 'Grenzabstand' verschluckt werden."""
    mapping = {}
    remaining = set(all_columns)
    for ptype in sorted(PARAM_TYPES, key=len, reverse=True):
        slug = slugify(ptype)
        for variant in VARIANTS:
            value_col = f'{ptype} ({variant})'
            flag_col = f'{ptype} ({variant}) [T/N]'
            if value_col in remaining:
                mapping[value_col] = f'{slug}_{slugify(variant)}_value'
                remaining.discard(value_col)
            if flag_col in remaining:
                mapping[flag_col] = f'{slug}_{slugify(variant)}_flag'
                remaining.discard(flag_col)
    return mapping


def main():
    con = duckdb.connect(':memory:')
    con.execute(f"CREATE VIEW raw_detail AS SELECT * FROM read_csv('{RAW_FILE.as_posix()}', all_varchar=true, header=true, max_line_size=50000000)")
    all_columns = con.execute('DESCRIBE raw_detail').fetchdf()['column_name'].tolist()

    col_map = find_param_columns(all_columns)
    print(f'[INFO] {len(col_map)} Zonenparameter-Spalten gefunden (erwartet: {len(PARAM_TYPES)*6})')

    select_parts = ['PROJID', 'TRY_CAST(BFS AS INTEGER) AS BFS', 'zone_clean', '"Zone Name" AS zone_name']
    for raw_col, clean_col in col_map.items():
        select_parts.append(f'"{raw_col}" AS {clean_col}')

    con.execute(f"""
        CREATE OR REPLACE TABLE stg_project_zone_parameters AS
        SELECT {', '.join(select_parts)}
        FROM raw_detail
        WHERE BFS IS NOT NULL AND zone_clean IS NOT NULL AND trim(zone_clean) <> ''
    """)
    n_staging = con.execute('SELECT count(*) FROM stg_project_zone_parameters').fetchone()[0]
    print(f'[OK] stg_project_zone_parameters: {n_staging:,} Zeilen')

    agg_parts = [f'any_value({c}) AS {c}' for c in col_map.values()]
    con.execute(f"""
        CREATE OR REPLACE TABLE dim_zone_parameter AS
        SELECT
          dense_rank() OVER (ORDER BY BFS, zone_clean) AS zone_parameter_id,
          BFS, zone_clean, any_value(zone_name) AS zone_name,
          count(*) AS n_source_projects,
          {', '.join(agg_parts)}
        FROM stg_project_zone_parameters
        GROUP BY BFS, zone_clean
    """)
    n_dim = con.execute('SELECT count(*) FROM dim_zone_parameter').fetchone()[0]
    print(f'[OK] dim_zone_parameter: {n_dim:,} Zeilen (eindeutige Gemeinde+Zone-Kombinationen)')

    con.execute(f"COPY stg_project_zone_parameters TO '{(STAGING_DIR / 'stg_project_zone_parameters.parquet').as_posix()}' (FORMAT PARQUET)")
    con.execute(f"COPY dim_zone_parameter TO '{(DIM_DIR / 'dim_zone_parameter.parquet').as_posix()}' (FORMAT PARQUET)")

    live = duckdb.connect(str(DUCKDB_PATH))
    live.execute(f"CREATE OR REPLACE TABLE stg_project_zone_parameters AS SELECT * FROM read_parquet('{(STAGING_DIR / 'stg_project_zone_parameters.parquet').as_posix()}')")
    live.execute(f"CREATE OR REPLACE TABLE dim_zone_parameter AS SELECT * FROM read_parquet('{(DIM_DIR / 'dim_zone_parameter.parquet').as_posix()}')")
    live.close()
    print(f'[FERTIG] dim_zone_parameter und stg_project_zone_parameters in {DUCKDB_PATH} aktualisiert')


if __name__ == '__main__':
    main()
