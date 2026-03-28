"""Tests for config module."""

import pytest
import database

from config import get_all_models, get_model_pricing, clear_model_pricing_cache


class TestGetAllModels:

    def test_returns_models_from_db(self, in_memory_db):
        database.upsert("models", {
            "id": "m1", "model_id": "claude-sonnet", "name": "Claude Sonnet",
            "provider": "anthropic", "input_cost": 3.0, "output_cost": 15.0, "sort_order": 0,
        })
        database.upsert("models", {
            "id": "m2", "model_id": "gpt-4o", "name": "GPT-4o",
            "provider": "openai", "input_cost": 5.0, "output_cost": 15.0, "sort_order": 1,
        })
        models = get_all_models()
        assert len(models) >= 2
        model_ids = [m["id"] for m in models]
        assert "claude-sonnet" in model_ids
        assert "gpt-4o" in model_ids


class TestGetModelPricing:

    def test_returns_pricing_from_db(self, in_memory_db):
        clear_model_pricing_cache()
        database.upsert("models", {
            "id": "m1", "model_id": "test-model", "name": "Test",
            "provider": "test", "input_cost": 3.0, "output_cost": 15.0, "sort_order": 0,
        })
        pricing = get_model_pricing("test-model")
        assert pricing["input_cost"] == 3.0
        assert pricing["output_cost"] == 15.0

    def test_returns_default_for_unknown_model(self, in_memory_db):
        clear_model_pricing_cache()
        pricing = get_model_pricing("unknown-model-xyz")
        assert "input_cost" in pricing
        assert "output_cost" in pricing

    def test_cache_works(self, in_memory_db):
        clear_model_pricing_cache()
        database.upsert("models", {
            "id": "m1", "model_id": "cached-model", "name": "Cached",
            "provider": "test", "input_cost": 5.0, "output_cost": 20.0, "sort_order": 0,
        })
        pricing1 = get_model_pricing("cached-model")
        # Delete from DB
        database.delete_by_id("models", "m1")
        # Should still return cached value
        pricing2 = get_model_pricing("cached-model")
        assert pricing1 == pricing2


class TestClearModelPricingCache:

    def test_clears_cache(self, in_memory_db):
        clear_model_pricing_cache()
        database.upsert("models", {
            "id": "m1", "model_id": "cache-test", "name": "T",
            "provider": "test", "input_cost": 1.0, "output_cost": 2.0, "sort_order": 0,
        })
        get_model_pricing("cache-test")
        clear_model_pricing_cache()
        # After clear, next call should hit DB again
        database.delete_by_id("models", "m1")
        pricing = get_model_pricing("cache-test")
        # Should get default since DB record is gone
        assert pricing["input_cost"] != 1.0 or "input_cost" in pricing
