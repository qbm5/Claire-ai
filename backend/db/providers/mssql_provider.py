from db.base_provider import DatabaseProvider
from db.helpers import get_uid, now_iso, serialize_row, deserialize_row
from db.schema import TABLES, FOREIGN_KEYS, MIGRATIONS


def _mssql_type(typedef: str, is_fk: bool = False) -> str:
    """Convert portable schema types to MS SQL dialect.

    TEXT PRIMARY KEY  → NVARCHAR(255) PRIMARY KEY  (MAX can't be a PK)
    TEXT (FK col)     → NVARCHAR(255) ...  (must match referenced PK length)
    TEXT ...          → NVARCHAR(MAX) ...
    INTEGER ...       → INT ...
    """
    upper = typedef.upper()
    if upper.startswith("TEXT") and ("PRIMARY KEY" in upper or is_fk):
        return "NVARCHAR(255)" + typedef[4:]
    if upper.startswith("TEXT"):
        return "NVARCHAR(MAX)" + typedef[4:]
    if upper.startswith("INTEGER"):
        return "INT" + typedef[7:]
    return typedef


# Build set of (table, column) pairs that are foreign key columns
_FK_COLUMNS = set()
for _table, _fks in FOREIGN_KEYS.items():
    for child_col, _, _ in _fks:
        _FK_COLUMNS.add((_table, child_col))


class MSSQLProvider(DatabaseProvider):

    def __init__(self, connection_string: str):
        self._conn_str = connection_string

    def _connect(self):
        try:
            import pyodbc
        except ImportError:
            raise RuntimeError("pyodbc is required for MS SQL. Install it with: pip install pyodbc")
        if not self._conn_str:
            raise RuntimeError("MSSQL_CONNECTION_STRING is not set. Configure it in Settings or .env")
        try:
            return pyodbc.connect(self._conn_str, autocommit=False)
        except (pyodbc.InterfaceError, pyodbc.OperationalError) as e:
            raise RuntimeError(
                f"Cannot connect to MS SQL — check that the ODBC driver is installed "
                f"and MSSQL_CONNECTION_STRING is correct: {e}"
            ) from e

    def _row_to_dict(self, cursor, row) -> dict:
        """Convert a pyodbc Row to a dict using cursor.description."""
        return {col[0]: val for col, val in zip(cursor.description, row)}

    # ── init / migrations ────────────────────────────────────────────

    def init_db(self) -> None:
        conn = self._connect()
        cursor = conn.cursor()

        for table_name, columns in TABLES:
            col_defs = ", ".join(
                f"[{name}] {_mssql_type(typedef, is_fk=(table_name, name) in _FK_COLUMNS)}"
                for name, typedef in columns
            )
            fk_clauses = ""
            for child_col, parent_table, parent_col in FOREIGN_KEYS.get(table_name, []):
                fk_clauses += (
                    f", FOREIGN KEY ([{child_col}]) REFERENCES [{parent_table}]([{parent_col}])"
                )
            cursor.execute(
                f"IF NOT EXISTS (SELECT 1 FROM sys.tables WHERE name = ?) "
                f"CREATE TABLE [{table_name}] ({col_defs}{fk_clauses})",
                (table_name,),
            )

        for table, column, col_type in MIGRATIONS:
            mssql_type = _mssql_type(col_type)
            cursor.execute(
                "IF NOT EXISTS ("
                "  SELECT 1 FROM sys.columns"
                "  WHERE object_id = OBJECT_ID(?) AND name = ?"
                f") ALTER TABLE [{table}] ADD [{column}] {mssql_type}",
                (table, column),
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
        source_cols = ", ".join(f"[{c}]" for c in cols)
        placeholders = ", ".join(["?"] * len(cols))
        updates = ", ".join(
            f"target.[{c}] = source.[{c}]" for c in cols if c != "id"
        )
        inserts_cols = ", ".join(f"[{c}]" for c in cols)
        inserts_vals = ", ".join(f"source.[{c}]" for c in cols)

        sql = (
            f"MERGE [{table}] WITH (HOLDLOCK) AS target "
            f"USING (VALUES ({placeholders})) AS source ({source_cols}) "
            f"ON target.[id] = source.[id] "
            f"WHEN MATCHED THEN UPDATE SET {updates} "
            f"WHEN NOT MATCHED THEN INSERT ({inserts_cols}) VALUES ({inserts_vals});"
        )

        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(sql, [data[c] for c in cols])
        conn.commit()
        cursor.close()
        conn.close()
        return data

    def get_by_id(self, table: str, id: str) -> dict | None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(f"SELECT * FROM [{table}] WHERE [id] = ?", (id,))
        row = cursor.fetchone()
        result = self._row_to_dict(cursor, row) if row else None
        cursor.close()
        conn.close()
        if result:
            return deserialize_row(table, result)
        return None

    def get_all(self, table: str, where: str = "", params: tuple = (), order_by: str = "") -> list[dict]:
        conn = self._connect()
        cursor = conn.cursor()
        sql = f"SELECT * FROM [{table}]"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        result = [deserialize_row(table, self._row_to_dict(cursor, r)) for r in rows]
        cursor.close()
        conn.close()
        return result

    def delete_by_id(self, table: str, id: str) -> None:
        conn = self._connect()
        cursor = conn.cursor()
        cursor.execute(f"DELETE FROM [{table}] WHERE [id] = ?", (id,))
        conn.commit()
        cursor.close()
        conn.close()

    # ── New provider-level methods ───────────────────────────────────

    def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        sql = f"SELECT COUNT(*) FROM [{table}]"
        if where:
            sql += f" WHERE {where}"
        cursor.execute(sql, params)
        result = cursor.fetchone()[0]
        cursor.close()
        conn.close()
        return result

    def query_rows(self, table: str, where: str = "", params: tuple = (),
                   order_by: str = "", limit: int = 0) -> list[dict]:
        conn = self._connect()
        cursor = conn.cursor()
        top = f"TOP {int(limit)} " if limit else ""
        sql = f"SELECT {top}* FROM [{table}]"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        cursor.execute(sql, params)
        rows = cursor.fetchall()
        result = [deserialize_row(table, self._row_to_dict(cursor, r)) for r in rows]
        cursor.close()
        conn.close()
        return result

    def update_where(self, table: str, set_clause: dict, where: str = "", params: tuple = ()) -> int:
        conn = self._connect()
        cursor = conn.cursor()
        set_parts = []
        set_values = []
        for col, val in set_clause.items():
            set_parts.append(f"[{col}] = ?")
            set_values.append(val)
        sql = f"UPDATE [{table}] SET {', '.join(set_parts)}"
        if where:
            sql += f" WHERE {where}"
        cursor.execute(sql, tuple(set_values) + tuple(params))
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
        conn.close()
        return affected
