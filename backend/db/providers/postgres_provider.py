from db.base_provider import DatabaseProvider
from db.helpers import get_uid, now_iso, serialize_row, deserialize_row
from db.schema import TABLES, FOREIGN_KEYS, MIGRATIONS

## Not tested
def _pg_type(typedef: str) -> str:
    """Convert portable schema types to PostgreSQL dialect.

    TEXT PRIMARY KEY  → VARCHAR(255) PRIMARY KEY
    TEXT ...          → TEXT ...  (native)
    INTEGER ...       → INTEGER ...  (native)
    """
    upper = typedef.upper()
    if upper.startswith("TEXT") and "PRIMARY KEY" in upper:
        return "VARCHAR(255)" + typedef[4:]
    return typedef


def _rewrite_placeholders(sql: str) -> str:
    """Convert ? placeholders to %s for psycopg2."""
    return sql.replace("?", "%s")


class PostgresProvider(DatabaseProvider):

    def __init__(self, connection_string: str):
        self._conn_str = connection_string
        self._psycopg2 = None

    def _import(self):
        if self._psycopg2 is None:
            try:
                import psycopg2
                import psycopg2.extras
                self._psycopg2 = psycopg2
            except ImportError:
                raise RuntimeError("psycopg2 is required for PostgreSQL. Install it with: pip install psycopg2-binary")
        return self._psycopg2

    def _connect(self):
        pg = self._import()
        if not self._conn_str:
            raise RuntimeError("POSTGRES_CONNECTION_STRING is not set. Configure it in Settings or .env")
        try:
            return pg.connect(self._conn_str)
        except pg.OperationalError as e:
            raise RuntimeError(
                f"Cannot connect to PostgreSQL — check that the server is running "
                f"and POSTGRES_CONNECTION_STRING is correct: {e}"
            ) from e

    def _dict_cursor(self, conn):
        pg = self._import()
        return conn.cursor(cursor_factory=pg.extras.RealDictCursor)

    # ── init / migrations ────────────────────────────────────────────

    def init_db(self) -> None:
        conn = self._connect()
        cursor = conn.cursor()

        for table_name, columns in TABLES:
            col_defs = ", ".join(
                f"{name} {_pg_type(typedef)}" for name, typedef in columns
            )
            fk_clauses = ""
            for child_col, parent_table, parent_col in FOREIGN_KEYS.get(table_name, []):
                fk_clauses += (
                    f", FOREIGN KEY ({child_col}) REFERENCES {parent_table}({parent_col})"
                )
            cursor.execute(
                f"CREATE TABLE IF NOT EXISTS {table_name} ({col_defs}{fk_clauses})"
            )

        for table, column, col_type in MIGRATIONS:
            pg_type = _pg_type(col_type)
            cursor.execute(
                f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {pg_type}"
            )

        conn.commit()
        cursor.close()
        conn.close()

    # ── CRUD ─────────────────────────────────────────────────────────

    def upsert(self, table: str, data: dict) -> dict:
        data = serialize_row(table, data)
        if not data.get("id"):
            data["id"] = get_uid()
        ts = now_iso()
        if not data.get("created_at"):
            data["created_at"] = ts
        data["updated_at"] = ts

        cols = list(data.keys())
        placeholders = ", ".join(["%s"] * len(cols))
        col_names = ", ".join(cols)
        updates = ", ".join(f"{c}=EXCLUDED.{c}" for c in cols if c != "id")

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            [data[c] for c in cols],
        )
        conn.commit()
        cursor.close()
        conn.close()
        return data

    def get_by_id(self, table: str, id: str) -> dict | None:
        conn = self._connect()
        cursor = self._dict_cursor(conn)
        cursor.execute(f"SELECT * FROM {table} WHERE id = %s", (id,))
        row = cursor.fetchone()
        cursor.close()
        conn.close()
        if row:
            return deserialize_row(table, dict(row))
        return None

    def get_all(self, table: str, where: str = "", params: tuple = (), order_by: str = "") -> list[dict]:
        conn = self._connect()
        cursor = self._dict_cursor(conn)
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {_rewrite_placeholders(where)}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [deserialize_row(table, dict(r)) for r in rows]

    def delete_by_id(self, table: str, id: str) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM {table} WHERE id = %s", (id,))
        conn.commit()
        cursor.close()
        conn.close()

    # ── New provider-level methods ───────────────────────────────────

    def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {_rewrite_placeholders(where)}"
        cursor.execute(sql, params)
        result = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return result

    def query_rows(self, table: str, where: str = "", params: tuple = (),
                   order_by: str = "", limit: int = 0) -> list[dict]:
        conn = self._connect()
        cursor = self._dict_cursor(conn)
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {_rewrite_placeholders(where)}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        cursor.close()
        conn.close()
        return [deserialize_row(table, dict(r)) for r in rows]

    def update_where(self, table: str, set_clause: dict, where: str = "", params: tuple = ()) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        set_parts = []
        set_values = []
        for col, val in set_clause.items():
            set_parts.append(f"{col} = %s")
            set_values.append(val)
        sql = f"UPDATE {table} SET {', '.join(set_parts)}"
        if where:
            sql += f" WHERE {_rewrite_placeholders(where)}"
        cursor.execute(sql, tuple(set_values) + tuple(params))
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        conn.close()
        return affected
