"""
Database facade — delegates to the configured provider.

All consumer code imports from here; the provider is swapped via config.DB_TYPE.
"""
from db.helpers import get_uid, now_iso, JSON_COLS, BOOL_COLS  # re-export

_provider = None


def _get_provider():
    global _provider
    if _provider is None:
        from config import DB_TYPE, DB_PATH
        if DB_TYPE == "sqlite":
            from db.providers.sqlite_provider import SQLiteProvider
            _provider = SQLiteProvider(DB_PATH)
        elif DB_TYPE == "mssql":
            from config import MSSQL_CONNECTION_STRING
            from db.providers.mssql_provider import MSSQLProvider
            _provider = MSSQLProvider(MSSQL_CONNECTION_STRING)
        elif DB_TYPE == "postgres":
            from config import POSTGRES_CONNECTION_STRING
            from db.providers.postgres_provider import PostgresProvider
            _provider = PostgresProvider(POSTGRES_CONNECTION_STRING)
        elif DB_TYPE == "cosmos":
            from config import COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE
            from db.providers.cosmos_provider import CosmosProvider
            _provider = CosmosProvider(COSMOS_ENDPOINT, COSMOS_KEY, COSMOS_DATABASE)
        else:
            raise ValueError(f"Unknown DB_TYPE: {DB_TYPE}")
    return _provider


def init_db():
    _get_provider().init_db()


def upsert(table: str, data: dict) -> dict:
    return _get_provider().upsert(table, data)


def get_by_id(table: str, id: str) -> dict | None:
    return _get_provider().get_by_id(table, id)


def get_all(table: str, where: str = "", params: tuple = (), order_by: str = "") -> list[dict]:
    return _get_provider().get_all(table, where, params, order_by)


def delete_by_id(table: str, id: str) -> None:
    _get_provider().delete_by_id(table, id)


def count(table: str, where: str = "", params: tuple = ()) -> int:
    return _get_provider().count(table, where, params)


def query_rows(table: str, where: str = "", params: tuple = (),
               order_by: str = "", limit: int = 0) -> list[dict]:
    return _get_provider().query_rows(table, where, params, order_by, limit)


def update_where(table: str, set_clause: dict, where: str = "", params: tuple = ()) -> int:
    return _get_provider().update_where(table, set_clause, where, params)
