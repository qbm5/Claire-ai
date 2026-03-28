"""Tests for db/providers/sqlite_provider.py"""

import pytest
from db.providers.sqlite_provider import SQLiteProvider


@pytest.fixture()
def db(tmp_path):
    provider = SQLiteProvider(str(tmp_path / "test.db"))
    provider.init_db()
    return provider


class TestInitDb:
    def test_creates_tables(self, db):
        # Should be able to insert into known tables without error
        db.upsert("tools", {"id": "t1", "name": "Test"})
        result = db.get_by_id("tools", "t1")
        assert result is not None

    def test_migrations_applied(self, db):
        # pip_dependencies is a migration column
        db.upsert("tools", {"id": "t1", "name": "Test", "pip_dependencies": "[]"})
        result = db.get_by_id("tools", "t1")
        assert "pip_dependencies" in result

    def test_idempotent_init(self, tmp_path):
        provider = SQLiteProvider(str(tmp_path / "test.db"))
        provider.init_db()
        provider.init_db()  # Should not raise
        provider.upsert("tools", {"id": "t1", "name": "Test"})
        assert provider.get_by_id("tools", "t1") is not None


class TestUpsert:
    def test_insert_new(self, db):
        result = db.upsert("tools", {"name": "New Tool"})
        assert result["id"]  # auto-generated
        assert result["created_at"]
        assert result["updated_at"]

    def test_insert_with_id(self, db):
        result = db.upsert("tools", {"id": "custom-id", "name": "Custom"})
        assert result["id"] == "custom-id"

    def test_update_existing(self, db):
        db.upsert("tools", {"id": "t1", "name": "Original"})
        db.upsert("tools", {"id": "t1", "name": "Updated"})
        result = db.get_by_id("tools", "t1")
        assert result["name"] == "Updated"

    def test_preserves_created_at_on_update(self, db):
        r1 = db.upsert("tools", {"id": "t1", "name": "Original", "created_at": "2024-01-01"})
        r2 = db.upsert("tools", {"id": "t1", "name": "Updated", "created_at": "2024-01-01"})
        result = db.get_by_id("tools", "t1")
        assert result["created_at"] == "2024-01-01"

    def test_json_serialization(self, db):
        db.upsert("pipelines", {"id": "p1", "name": "Test", "steps": [{"name": "s1"}], "inputs": [], "edges": []})
        result = db.get_by_id("pipelines", "p1")
        assert isinstance(result["steps"], list)
        assert result["steps"][0]["name"] == "s1"


class TestGetById:
    def test_existing(self, db):
        db.upsert("tools", {"id": "t1", "name": "Test"})
        result = db.get_by_id("tools", "t1")
        assert result["name"] == "Test"

    def test_not_found(self, db):
        result = db.get_by_id("tools", "nonexistent")
        assert result is None

    def test_bool_deserialization(self, db):
        db.upsert("tools", {"id": "t1", "name": "Test", "is_enabled": True})
        result = db.get_by_id("tools", "t1")
        assert result["is_enabled"] is True


class TestGetAll:
    def test_returns_all(self, db):
        db.upsert("tools", {"id": "t1", "name": "A"})
        db.upsert("tools", {"id": "t2", "name": "B"})
        results = db.get_all("tools")
        assert len(results) == 2

    def test_where_clause(self, db):
        db.upsert("tools", {"id": "t1", "name": "A", "tag": "x"})
        db.upsert("tools", {"id": "t2", "name": "B", "tag": "y"})
        results = db.get_all("tools", "tag = ?", ("x",))
        assert len(results) == 1
        assert results[0]["name"] == "A"

    def test_order_by(self, db):
        db.upsert("tools", {"id": "t1", "name": "B"})
        db.upsert("tools", {"id": "t2", "name": "A"})
        results = db.get_all("tools", order_by="name ASC")
        assert results[0]["name"] == "A"

    def test_empty_table(self, db):
        results = db.get_all("tools")
        assert results == []


class TestDeleteById:
    def test_delete_existing(self, db):
        db.upsert("tools", {"id": "t1", "name": "Test"})
        db.delete_by_id("tools", "t1")
        assert db.get_by_id("tools", "t1") is None

    def test_delete_nonexistent_no_error(self, db):
        db.delete_by_id("tools", "nonexistent")  # Should not raise


class TestCount:
    def test_count_all(self, db):
        db.upsert("tools", {"id": "t1", "name": "A"})
        db.upsert("tools", {"id": "t2", "name": "B"})
        assert db.count("tools") == 2

    def test_count_with_where(self, db):
        db.upsert("tools", {"id": "t1", "name": "A", "tag": "x"})
        db.upsert("tools", {"id": "t2", "name": "B", "tag": "y"})
        assert db.count("tools", "tag = ?", ("x",)) == 1

    def test_count_empty(self, db):
        assert db.count("tools") == 0


class TestQueryRows:
    def test_basic_query(self, db):
        db.upsert("tools", {"id": "t1", "name": "A"})
        db.upsert("tools", {"id": "t2", "name": "B"})
        results = db.query_rows("tools")
        assert len(results) == 2

    def test_with_limit(self, db):
        db.upsert("tools", {"id": "t1", "name": "A"})
        db.upsert("tools", {"id": "t2", "name": "B"})
        results = db.query_rows("tools", limit=1)
        assert len(results) == 1

    def test_with_order_by(self, db):
        db.upsert("tools", {"id": "t1", "name": "B"})
        db.upsert("tools", {"id": "t2", "name": "A"})
        results = db.query_rows("tools", order_by="name ASC")
        assert results[0]["name"] == "A"


class TestUpdateWhere:
    def test_update_matching(self, db):
        db.upsert("tools", {"id": "t1", "name": "A", "tag": "old"})
        db.upsert("tools", {"id": "t2", "name": "B", "tag": "old"})
        affected = db.update_where("tools", {"tag": "new"}, "tag = ?", ("old",))
        assert affected == 2
        assert db.get_by_id("tools", "t1")["tag"] == "new"

    def test_update_no_match(self, db):
        db.upsert("tools", {"id": "t1", "name": "A", "tag": "x"})
        affected = db.update_where("tools", {"tag": "new"}, "tag = ?", ("nonexistent",))
        assert affected == 0
