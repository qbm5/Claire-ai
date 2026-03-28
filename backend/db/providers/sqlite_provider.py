import sqlite3
from db.base_provider import DatabaseProvider
from db.helpers import get_uid, now_iso, serialize_row, deserialize_row
from db.schema import TABLES, FOREIGN_KEYS, MIGRATIONS


class SQLiteProvider(DatabaseProvider):

    def __init__(self, db_path: str):
        self._db_path = db_path

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ── init / migrations ────────────────────────────────────────────

    def init_db(self) -> None:
        conn = self._connect()

        for table_name, columns in TABLES:
            col_defs = ", ".join(f"{name} {typedef}" for name, typedef in columns)
            fk_clauses = ""
            for child_col, parent_table, parent_col in FOREIGN_KEYS.get(table_name, []):
                fk_clauses += f", FOREIGN KEY ({child_col}) REFERENCES {parent_table}({parent_col})"
            conn.execute(f"CREATE TABLE IF NOT EXISTS {table_name} ({col_defs}{fk_clauses})")

        for table, column, col_type in MIGRATIONS:
            try:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            except sqlite3.OperationalError:
                pass  # column already exists

        conn.commit()
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
        placeholders = ", ".join(["?"] * len(cols))
        col_names = ", ".join(cols)
        updates = ", ".join(f"{c}=excluded.{c}" for c in cols if c != "id")

        conn = self._connect()
        conn.execute(
            f"INSERT INTO {table} ({col_names}) VALUES ({placeholders}) "
            f"ON CONFLICT(id) DO UPDATE SET {updates}",
            [data[c] for c in cols],
        )
        conn.commit()
        conn.close()
        return data

    def get_by_id(self, table: str, id: str) -> dict | None:
        conn = self._connect()
        row = conn.execute(f"SELECT * FROM {table} WHERE id=?", (id,)).fetchone()
        conn.close()
        if row:
            return deserialize_row(table, dict(row))
        return None

    def get_all(self, table: str, where: str = "", params: tuple = (), order_by: str = "") -> list[dict]:
        conn = self._connect()
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [deserialize_row(table, dict(r)) for r in rows]

    def delete_by_id(self, table: str, id: str) -> None:
        conn = self._connect()
        conn.execute(f"DELETE FROM {table} WHERE id=?", (id,))
        conn.commit()
        conn.close()

    # ── New provider-level methods ───────────────────────────────────

    def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        conn = self._connect()
        sql = f"SELECT COUNT(*) FROM {table}"
        if where:
            sql += f" WHERE {where}"
        result = conn.execute(sql, params).fetchone()[0]
        conn.close()
        return result

    def query_rows(self, table: str, where: str = "", params: tuple = (),
                   order_by: str = "", limit: int = 0) -> list[dict]:
        conn = self._connect()
        sql = f"SELECT * FROM {table}"
        if where:
            sql += f" WHERE {where}"
        if order_by:
            sql += f" ORDER BY {order_by}"
        if limit:
            sql += f" LIMIT {int(limit)}"
        rows = conn.execute(sql, params).fetchall()
        conn.close()
        return [deserialize_row(table, dict(r)) for r in rows]

    def update_where(self, table: str, set_clause: dict, where: str = "", params: tuple = ()) -> int:
        conn = self._connect()
        set_parts = []
        set_values = []
        for col, val in set_clause.items():
            set_parts.append(f"{col} = ?")
            set_values.append(val)
        sql = f"UPDATE {table} SET {', '.join(set_parts)}"
        if where:
            sql += f" WHERE {where}"
        cursor = conn.execute(sql, tuple(set_values) + tuple(params))
        conn.commit()
        affected = cursor.rowcount
        conn.close()
        return affected
