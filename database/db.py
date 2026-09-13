import duckdb
from config.settings import DB_PATH

def connect(read_only=False):
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DB_PATH), read_only=read_only)

def query_df(sql, params=None):
    con=connect(read_only=True)
    try: return con.execute(sql, params or []).df()
    finally: con.close()

def table_exists(name):
    con=connect(read_only=True)
    try:
        return bool(con.execute("SELECT count(*) FROM information_schema.tables WHERE table_name=?", [name]).fetchone()[0])
    finally: con.close()
