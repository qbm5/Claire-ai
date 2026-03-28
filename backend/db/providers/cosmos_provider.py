import logging
import math
import re
from datetime import datetime, date
from db.base_provider import DatabaseProvider
from db.helpers import get_uid, now_iso, BOOL_COLS

logger = logging.getLogger(__name__)

# Cosmos system properties to strip from returned items
_SYSTEM_KEYS = {"_rid", "_self", "_etag", "_attachments", "_ts"}

_SQL_KEYWORDS = frozenset({
    "AND", "OR", "NOT", "IN", "LIKE", "IS", "NULL", "BETWEEN",
    "EXISTS", "TRUE", "FALSE", "ASC", "DESC",
    "SELECT", "FROM", "WHERE", "ORDER", "BY", "TOP", "VALUE",
    "COUNT", "SUM", "AVG", "MIN", "MAX", "OFFSET", "LIMIT",
    "JOIN", "AS", "DISTINCT", "GROUP", "HAVING",
})


def _rewrite_query(where: str, params: tuple) -> tuple[str, list[dict]]:
    """Convert SQL-style WHERE to Cosmos DB parameterized query.

    1. Prefix bare column names with ``c.``
    2. Replace ``?`` placeholders with ``@p0``, ``@p1``, ...
    """
    if not where:
        return "", []

    # Step 1 — prefix columns (before inserting @pN tokens)
    def _prefix(m: re.Match) -> str:
        word = m.group(0)
        return word if word.upper() in _SQL_KEYWORDS else f"c.{word}"

    cosmos_where = re.sub(r"\b[a-zA-Z_]\w*\b", _prefix, where)

    # Step 2 — replace ? with @pN
    idx = [0]

    def _next_param(_: re.Match) -> str:
        name = f"@p{idx[0]}"
        idx[0] += 1
        return name

    cosmos_where = re.sub(r"\?", _next_param, cosmos_where)

    # Step 3 — build parameter list
    cosmos_params = [{"name": f"@p{i}", "value": v} for i, v in enumerate(params)]
    return cosmos_where, cosmos_params


def _prefix_order_by(order_by: str) -> str:
    """Prefix column names in an ORDER BY clause with ``c.``."""
    if not order_by:
        return ""

    def _prefix(m: re.Match) -> str:
        word = m.group(0)
        return word if word.upper() in _SQL_KEYWORDS else f"c.{word}"

    return re.sub(r"\b[a-zA-Z_]\w*\b", _prefix, order_by)


def _sanitize_value(obj):
    """Recursively sanitize a value for Cosmos DB JSON compliance.

    Handles: system keys, NaN/Inf, datetime, bytes, sets, non-string dict keys.
    """
    if obj is None:
        return None
    if isinstance(obj, dict):
        return {
            str(k): _sanitize_value(v)
            for k, v in obj.items()
            if k not in _SYSTEM_KEYS and k != ""
        }
    if isinstance(obj, (list, tuple)):
        return [_sanitize_value(v) for v in obj]
    if isinstance(obj, set):
        return [_sanitize_value(v) for v in sorted(obj, key=str)]
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return obj
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")
    if isinstance(obj, (str, int, bool)):
        return obj
    # Fallback — convert to string to avoid serialization errors
    return str(obj)


def _sanitize_for_write(data: dict) -> dict:
    """Sanitize a top-level document before writing to Cosmos DB."""
    doc = _sanitize_value(data)
    # Ensure id is a non-empty string (Cosmos requirement)
    if "id" in doc:
        doc["id"] = str(doc["id"]) if doc["id"] else get_uid()
    return doc


class CosmosProvider(DatabaseProvider):
    """Azure Cosmos DB (NoSQL API) provider.

    Each schema table maps to a Cosmos container with ``/id`` partition key.
    JSON columns are stored as native JSON (no string serialization).
    """

    def __init__(self, endpoint: str, key: str, database_name: str = "sourcechat"):
        self._endpoint = endpoint
        self._key = key
        self._db_name = database_name
        self._client = None
        self._database = None
        self._containers: dict = {}

    def _ensure_client(self):
        if self._client is not None:
            return
        try:
            from azure.cosmos import CosmosClient  # noqa: F811
        except ImportError:
            raise RuntimeError(
                "azure-cosmos is required for Cosmos DB. "
                "Install it with: pip install azure-cosmos"
            )
        if not self._endpoint or not self._key:
            raise RuntimeError(
                "COSMOS_ENDPOINT and COSMOS_KEY must both be set. "
                "Configure them in Settings or .env"
            )
        self._client = CosmosClient(self._endpoint, credential=self._key)

    def _get_database(self):
        self._ensure_client()
        if self._database is None:
            self._database = self._client.get_database_client(self._db_name)
        return self._database

    def _get_container(self, table: str):
        if table not in self._containers:
            self._containers[table] = self._get_database().get_container_client(table)
        return self._containers[table]

    def _clean_item(self, table: str, item: dict) -> dict:
        """Strip Cosmos system properties and convert bool columns."""
        d = {k: v for k, v in item.items() if k not in _SYSTEM_KEYS}
        for col in BOOL_COLS.get(table, []):
            if col in d:
                d[col] = bool(d[col])
        return d

    # ── init ─────────────────────────────────────────────────────────

    def init_db(self) -> None:
        from azure.cosmos import PartitionKey
        from db.schema import TABLES

        self._ensure_client()
        self._client.create_database_if_not_exists(self._db_name)
        self._database = self._client.get_database_client(self._db_name)

        for table_name, _ in TABLES:
            self._database.create_container_if_not_exists(
                id=table_name,
                partition_key=PartitionKey(path="/id"),
            )
            self._containers[table_name] = self._database.get_container_client(table_name)

    # ── CRUD ─────────────────────────────────────────────────────────

    def upsert(self, table: str, data: dict) -> dict:
        data = dict(data)  # don't mutate caller
        if not data.get("id"):
            data["id"] = get_uid()
        ts = now_iso()
        if not data.get("created_at"):
            data["created_at"] = ts
        data["updated_at"] = ts

        doc = _sanitize_for_write(data)
        try:
            self._get_container(table).upsert_item(doc)
        except Exception as e:
            import json
            size = len(json.dumps(doc, default=str))
            logger.error(
                "Cosmos upsert failed on table=%s id=%s size=%d: %s",
                table, doc.get("id"), size, e,
            )
            raise
        return data

    def get_by_id(self, table: str, id: str) -> dict | None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            item = self._get_container(table).read_item(item=id, partition_key=id)
            return self._clean_item(table, item)
        except CosmosResourceNotFoundError:
            return None

    def get_all(self, table: str, where: str = "", params: tuple = (),
                order_by: str = "") -> list[dict]:
        query = "SELECT * FROM c"
        cosmos_params: list[dict] = []
        if where:
            w, cosmos_params = _rewrite_query(where, params)
            query += f" WHERE {w}"
        if order_by:
            query += f" ORDER BY {_prefix_order_by(order_by)}"

        items = list(self._get_container(table).query_items(
            query=query,
            parameters=cosmos_params or None,
            enable_cross_partition_query=True,
        ))
        return [self._clean_item(table, i) for i in items]

    def delete_by_id(self, table: str, id: str) -> None:
        from azure.cosmos.exceptions import CosmosResourceNotFoundError

        try:
            self._get_container(table).delete_item(item=id, partition_key=id)
        except CosmosResourceNotFoundError:
            pass

    # ── Extended methods ─────────────────────────────────────────────

    def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        query = "SELECT VALUE COUNT(1) FROM c"
        cosmos_params: list[dict] = []
        if where:
            w, cosmos_params = _rewrite_query(where, params)
            query += f" WHERE {w}"

        results = list(self._get_container(table).query_items(
            query=query,
            parameters=cosmos_params or None,
            enable_cross_partition_query=True,
        ))
        return results[0] if results else 0

    def query_rows(self, table: str, where: str = "", params: tuple = (),
                   order_by: str = "", limit: int = 0) -> list[dict]:
        top = f"TOP {int(limit)} " if limit else ""
        query = f"SELECT {top}* FROM c"
        cosmos_params: list[dict] = []
        if where:
            w, cosmos_params = _rewrite_query(where, params)
            query += f" WHERE {w}"
        if order_by:
            query += f" ORDER BY {_prefix_order_by(order_by)}"

        items = list(self._get_container(table).query_items(
            query=query,
            parameters=cosmos_params or None,
            enable_cross_partition_query=True,
        ))
        return [self._clean_item(table, i) for i in items]

    def update_where(self, table: str, set_clause: dict, where: str = "",
                     params: tuple = ()) -> int:
        # Cosmos has no UPDATE — read matching docs, modify, upsert back
        matching = self.query_rows(table, where, params)
        container = self._get_container(table)
        ts = now_iso()
        for item in matching:
            item.update(set_clause)
            item["updated_at"] = ts
            doc = _sanitize_for_write(item)
            try:
                container.upsert_item(doc)
            except Exception as e:
                import json
                size = len(json.dumps(doc, default=str))
                logger.error(
                    "Cosmos update_where failed on table=%s id=%s size=%d: %s",
                    table, doc.get("id"), size, e,
                )
                raise
        return len(matching)
