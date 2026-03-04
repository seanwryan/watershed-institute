"""Database connection helper for ETL."""
import psycopg2
from psycopg2.extras import execute_values
from contextlib import contextmanager

from etl.config import DATABASE_URL


@contextmanager
def get_conn():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_lookup(conn, table: str, pk_col: str, key_col: str, value, insert_extra: dict = None) -> int:
    """Get or insert a lookup row; return primary key. Value must be non-empty."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    val = value.strip() if isinstance(value, str) else value
    with conn.cursor() as cur:
        cur.execute(f"SELECT {pk_col} FROM {table} WHERE {key_col} = %s", (val,))
        row = cur.fetchone()
        if row:
            return row[0]
        cols = [key_col] + (list(insert_extra.keys()) if insert_extra else [])
        vals = [val] + (list(insert_extra.values()) if insert_extra else [])
        placeholders = ", ".join(["%s"] * len(cols))
        cur.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({placeholders}) RETURNING {pk_col}", vals)
        return cur.fetchone()[0]
