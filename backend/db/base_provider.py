from abc import ABC, abstractmethod


class DatabaseProvider(ABC):
    """Abstract base for all database backends."""

    @abstractmethod
    def init_db(self) -> None:
        """Create tables + run migrations."""

    @abstractmethod
    def upsert(self, table: str, data: dict) -> dict:
        """Insert or update a row by id. Returns the (possibly enriched) data dict."""

    @abstractmethod
    def get_by_id(self, table: str, id: str) -> dict | None:
        """Return a single row as dict, or None."""

    @abstractmethod
    def get_all(self, table: str, where: str = "", params: tuple = (), order_by: str = "") -> list[dict]:
        """Return all matching rows as list of dicts."""

    @abstractmethod
    def delete_by_id(self, table: str, id: str) -> None:
        """Delete a single row by id."""

    @abstractmethod
    def count(self, table: str, where: str = "", params: tuple = ()) -> int:
        """Return COUNT(*) with optional WHERE clause."""

    @abstractmethod
    def query_rows(self, table: str, where: str = "", params: tuple = (),
                   order_by: str = "", limit: int = 0) -> list[dict]:
        """Flexible SELECT returning list[dict] with optional WHERE, ORDER BY, LIMIT."""

    @abstractmethod
    def update_where(self, table: str, set_clause: dict, where: str = "", params: tuple = ()) -> int:
        """UPDATE rows matching WHERE. Returns number of affected rows."""
