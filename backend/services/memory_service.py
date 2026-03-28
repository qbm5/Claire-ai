"""
Conversation memory service - stores chat history as JSON files.
"""

import os
import json
from config import MEMORY_DIR


def get_memory_path(history_id: str) -> str:
    return os.path.join(MEMORY_DIR, f"{history_id}.json")


def load_memory(history_id: str) -> list[dict]:
    """Load conversation messages for a history."""
    path = get_memory_path(history_id)
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_memory(history_id: str, messages: list[dict]):
    """Save conversation messages."""
    path = get_memory_path(history_id)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(messages, f, ensure_ascii=False, indent=2)


def append_message(history_id: str, role: str, content: str):
    """Append a single message to the conversation memory."""
    messages = load_memory(history_id)
    messages.append({"role": role, "content": content})
    save_memory(history_id, messages)


def clear_memory(history_id: str):
    """Delete a conversation's memory file."""
    path = get_memory_path(history_id)
    if os.path.exists(path):
        os.remove(path)
