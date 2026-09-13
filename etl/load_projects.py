import duckdb
con=duckdb.connect('data/hslu.duckdb')
con.execute("CREATE OR REPLACE TABLE project_level AS SELECT * FROM read_csv_auto('data/raw/project_level.csv')")