from database.db import connect

def test_database_connects():
    con=connect(); assert con.execute('select 1').fetchone()[0]==1; con.close()
