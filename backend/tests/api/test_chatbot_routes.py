"""Tests for api/chatbot_routes.py"""

import pytest


class TestChatbotList:
    def test_list_chatbots(self, test_client, sample_chatbot):
        resp = test_client.get("/api/chatbots")
        assert resp.status_code == 200
        bots = resp.json()
        assert isinstance(bots, list)
        assert len(bots) >= 1

    def test_list_excludes_deleted(self, test_client, in_memory_db):
        import database
        database.upsert("chatbots", {"id": "alive", "name": "Alive", "is_deleted": False})
        database.upsert("chatbots", {"id": "dead", "name": "Dead", "is_deleted": True})
        resp = test_client.get("/api/chatbots")
        bots = resp.json()
        ids = [b["id"] for b in bots]
        assert "alive" in ids
        assert "dead" not in ids


class TestChatbotGet:
    def test_get_existing(self, test_client, sample_chatbot):
        resp = test_client.get(f"/api/chatbots/{sample_chatbot['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Test Chatbot"

    def test_get_nonexistent(self, test_client):
        resp = test_client.get("/api/chatbots/nonexistent")
        assert resp.status_code == 200
        assert "error" in resp.json()


class TestChatbotCreate:
    def test_create_chatbot(self, test_client):
        bot = {"name": "New Bot", "description": "test", "source_type": "text", "source_texts": []}
        resp = test_client.post("/api/chatbots", json=bot)
        assert resp.status_code == 200
        assert "response" in resp.json()

    def test_update_chatbot(self, test_client, sample_chatbot):
        sample_chatbot["name"] = "Updated Bot"
        resp = test_client.post("/api/chatbots", json=sample_chatbot)
        assert resp.status_code == 200


class TestChatbotDelete:
    def test_soft_delete(self, test_client, sample_chatbot):
        resp = test_client.delete(f"/api/chatbots/{sample_chatbot['id']}")
        assert resp.status_code == 200
        # Verify soft deleted
        import database
        bot = database.get_by_id("chatbots", sample_chatbot["id"])
        assert bot["is_deleted"] == True


class TestChatbotPermissions:
    def test_regular_user_cannot_create_without_permission(self, regular_user_client):
        bot = {"name": "Blocked", "description": "test", "source_type": "text"}
        resp = regular_user_client.post("/api/chatbots", json=bot)
        assert resp.status_code == 403

    def test_regular_user_cannot_delete(self, regular_user_client, sample_chatbot):
        resp = regular_user_client.delete(f"/api/chatbots/{sample_chatbot['id']}")
        assert resp.status_code == 403


class TestChatHistories:

    def test_list_histories(self, test_client, sample_chatbot):
        resp = test_client.get(f"/api/chatbots/{sample_chatbot['id']}/histories")
        assert resp.status_code == 200

    def test_list_histories_with_data(self, test_client, sample_chatbot):
        import database
        database.upsert("chat_histories", {
            "id": "hist-1",
            "chatbot_id": sample_chatbot["id"],
            "user_id": "admin-id",
            "title": "Test Chat",
            "messages": [{"role": "user", "content": "hello"}],
        })
        resp = test_client.get(f"/api/chatbots/{sample_chatbot['id']}/histories")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_get_specific_history(self, test_client, sample_chatbot):
        import database
        database.upsert("chat_histories", {
            "id": "hist-2",
            "chatbot_id": sample_chatbot["id"],
            "user_id": "admin-id",
            "title": "Specific Chat",
            "messages": [{"role": "user", "content": "test"}],
        })
        resp = test_client.get(f"/api/chatbots/{sample_chatbot['id']}/histories/hist-2")
        assert resp.status_code == 200

    def test_delete_history(self, test_client, sample_chatbot):
        import database
        database.upsert("chat_histories", {
            "id": "hist-3",
            "chatbot_id": sample_chatbot["id"],
            "user_id": "admin-id",
            "title": "Delete Me",
            "messages": [],
        })
        resp = test_client.delete("/api/chatbots/histories/hist-3")
        assert resp.status_code == 200
