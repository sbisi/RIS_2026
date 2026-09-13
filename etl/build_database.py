from pathlib import Path
import duckdb
from config.settings import DB_PATH, RAW_DIR
from etl.common import find_file

CSV_OPTS = "header=true, auto_detect=true, sample_size=-1, ignore_errors=true, null_padding=true, all_varchar=false"

def load_csv(con, table, names):
    p=find_file(RAW_DIR,names)
    if not p: print(f'[SKIP] {table}: Datei fehlt'); return False
    con.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM read_csv_auto(?, {CSV_OPTS})", [str(p)])
    print(f'[OK] {table}: {con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]:,} Zeilen')
    return True

def load_excel(con, table, names):
    p=find_file(RAW_DIR,names)
    if not p: print(f'[SKIP] {table}: Datei fehlt'); return False
    import pandas as pd
    xls=pd.ExcelFile(p, engine='openpyxl')
    best=max(xls.sheet_names, key=lambda s: pd.read_excel(p,sheet_name=s,nrows=5,engine='openpyxl').shape[1])
    df=pd.read_excel(p,sheet_name=best,engine='openpyxl')
    con.register('_df',df); con.execute(f'CREATE OR REPLACE TABLE {table} AS SELECT * FROM _df'); con.unregister('_df')
    print(f'[OK] {table}: {len(df):,} Zeilen, Blatt {best}')
    return True

def main():
    DB_PATH.parent.mkdir(parents=True,exist_ok=True)
    con=duckdb.connect(str(DB_PATH))
    load_csv(con,'raw_project',['project_level'])
    load_csv(con,'raw_municipality',['municipality_level'])
    load_csv(con,'lu_devtype',['devtype_lu'])
    load_csv(con,'lu_fsa',['fsa_lu'])
    load_csv(con,'lu_tenure',['tenure_lu'])
    load_csv(con,'lu_cs_code',['cs_code_lu'])
    load_csv(con,'raw_law_manager',['results_law_Manager_260910','results_law_manager'])
    load_excel(con,'raw_ranking',['HSLU_Gemeinderanking_260811','HSLU_Gemeinderanking'])
    load_excel(con,'raw_coordinates',['gemeinden_koordinaten'])
    sql=(Path(__file__).resolve().parents[1]/'database'/'views.sql').read_text(encoding='utf-8')
    con.execute(sql)
    con.execute("CREATE OR REPLACE TABLE etl_metadata AS SELECT current_timestamp run_at, ? raw_dir",[str(RAW_DIR)])
    con.close(); print(f'[FERTIG] {DB_PATH}')
if __name__=='__main__': main()
