"""
RAG service - local sentence-transformers embeddings + FAISS vector store.
Uses BAAI/bge-large-en-v1.5 for GPU-accelerated embedding.
"""

import os
import json
import numpy as np
import faiss
from config import INDEX_DIR
from event_bus import broadcast

_model = None


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        _model = SentenceTransformer("BAAI/bge-large-en-v1.5")
    return _model


DIMENSIONS = 1024
CHUNK_SIZE = 512
CHUNK_OVERLAP = 50


def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks by character count."""
    if len(text) <= chunk_size:
        return [text]
    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size
        chunks.append(text[start:end])
        start = end - overlap
    return chunks


def embed_texts(texts: list[str], chatbot_id: str = "") -> np.ndarray:
    """Embed a list of texts using local model (document mode)."""
    model = _get_model()
    batch_size = 64
    all_embeddings = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        emb = model.encode(batch, normalize_embeddings=True, show_progress_bar=False)
        all_embeddings.append(emb)
        if chatbot_id:
            broadcast("index_progress", {
                "chatbot_id": chatbot_id,
                "current": min(i + batch_size, len(texts)),
                "total": len(texts),
            })
    return np.vstack(all_embeddings).astype(np.float32)


def embed_query(query: str) -> np.ndarray:
    """Embed a single query using local model."""
    model = _get_model()
    # bge models recommend prefixing queries for better retrieval
    embedding = model.encode(["Represent this sentence for searching relevant passages: " + query],
                             normalize_embeddings=True, show_progress_bar=False)
    return np.array(embedding, dtype=np.float32).reshape(1, -1)


def build_index(chatbot_id: str, documents: list[dict]) -> int:
    """Build a FAISS index from documents.

    documents: list of {"text": str, "source": str}
    Returns number of chunks indexed.
    """
    index_dir = os.path.join(INDEX_DIR, chatbot_id)
    os.makedirs(index_dir, exist_ok=True)

    all_chunks = []
    chunk_metadata = []
    for doc in documents:
        chunks = chunk_text(doc["text"])
        for chunk in chunks:
            all_chunks.append(chunk)
            chunk_metadata.append({"source": doc.get("source", ""), "text": chunk})

    if not all_chunks:
        return 0

    broadcast("index_progress", {
        "chatbot_id": chatbot_id,
        "current": 0,
        "total": len(all_chunks),
        "status": "embedding",
    })

    embeddings = embed_texts(all_chunks, chatbot_id)
    index = faiss.IndexFlatIP(DIMENSIONS)
    index.add(embeddings)

    faiss.write_index(index, os.path.join(index_dir, "index.faiss"))
    with open(os.path.join(index_dir, "metadata.json"), "w", encoding="utf-8") as f:
        json.dump(chunk_metadata, f, ensure_ascii=False)

    return len(all_chunks)


def query_index(chatbot_id: str, query_text: str, top_k: int = 6) -> list[dict]:
    """Query a FAISS index. Returns list of {"text": str, "source": str, "score": float}."""
    index_dir = os.path.join(INDEX_DIR, chatbot_id)
    index_path = os.path.join(index_dir, "index.faiss")
    meta_path = os.path.join(index_dir, "metadata.json")

    if not os.path.exists(index_path):
        return []

    index = faiss.read_index(index_path)
    with open(meta_path, "r", encoding="utf-8") as f:
        metadata = json.load(f)

    query_vec = embed_query(query_text)
    scores, indices = index.search(query_vec, min(top_k, index.ntotal))

    results = []
    for i, idx in enumerate(indices[0]):
        if idx < 0 or idx >= len(metadata):
            continue
        results.append({
            **metadata[idx],
            "score": float(scores[0][i]),
        })
    return results


def delete_index(chatbot_id: str):
    """Remove a chatbot's index files."""
    import shutil
    index_dir = os.path.join(INDEX_DIR, chatbot_id)
    if os.path.isdir(index_dir):
        shutil.rmtree(index_dir)
