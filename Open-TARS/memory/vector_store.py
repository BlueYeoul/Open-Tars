"""Vector memory using Qwen3-VL-Embedding-2B via local API.

Calls http://localhost:1234/api/v1/embeddings with the same format as
the chat client.  Supports text-only and text+image (VL) embeddings.

Stores agent memories as embeddings and retrieves the most relevant
ones at query time via cosine similarity.
"""
from __future__ import annotations

import json
import urllib.request
import urllib.error
from dataclasses import dataclass

import numpy as np

EMBED_URL   = "http://localhost:1234/api/v1/embeddings"
EMBED_MODEL = "qwen3-vl-embedding-2b"


@dataclass
class MemoryEntry:
    key: str
    text: str
    embedding: np.ndarray
    has_image: bool = False


def _call_embed(text: str, image_b64: str | None = None) -> np.ndarray:
    """Call the local embedding API and return a unit-norm vector.

    Payload mirrors the chat API format:
      text-only : {"model": ..., "input": "..."}
      VL        : {"model": ..., "input": [{"type": "image", "data_url": ...},
                                            {"type": "text",  "content": ...}]}
    """
    if image_b64:
        inp = [
            {"type": "image", "data_url": image_b64},
            {"type": "text",  "content": text},
        ]
    else:
        inp = text

    payload = {"model": EMBED_MODEL, "input": inp}
    req = urllib.request.Request(
        EMBED_URL,
        json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    resp = urllib.request.urlopen(req, timeout=60)
    data = json.loads(resp.read().decode())

    # Standard response: {"data": [{"embedding": [...]}]} or {"embedding": [...]}
    if "data" in data:
        emb = np.array(data["data"][0]["embedding"], dtype=np.float32)
    else:
        emb = np.array(data["embedding"], dtype=np.float32)

    norm = np.linalg.norm(emb)
    return emb / norm if norm > 0 else emb


class VectorMemory:
    """Semantic memory store backed by Qwen3-VL-Embedding-2B.

    Usage:
        vmem = VectorMemory()
        vmem.add("login_url", "https://mail.google.com", image_b64=b64)
        results = vmem.search("find the gmail login page", k=3)
    """

    def __init__(self):
        self._entries: list[MemoryEntry] = []

    # ── Public API ─────────────────────────────────────────────────────

    def add(self, key: str, text: str, image_b64: str | None = None):
        """Add or overwrite a memory entry.

        Args:
            key:       Unique identifier (e.g. "login_url", "obs_12").
            text:      The text content to store and embed.
            image_b64: Optional base64 screenshot to embed alongside text.
                       Enables visual retrieval via VL embeddings.
        """
        try:
            emb = _call_embed(text, image_b64)
        except Exception as e:
            print(f"[VectorMemory] Embed failed for '{key}': {e}")
            return

        for entry in self._entries:
            if entry.key == key:
                entry.text      = text
                entry.embedding = emb
                entry.has_image = image_b64 is not None
                return

        self._entries.append(MemoryEntry(
            key=key, text=text, embedding=emb,
            has_image=image_b64 is not None,
        ))

    def search(
        self,
        query: str,
        k: int = 5,
        image_b64: str | None = None,
    ) -> list[dict]:
        """Return top-k entries most relevant to query.

        Args:
            query:     Natural language query or current goal.
            k:         Number of results to return.
            image_b64: Optional screenshot to use as visual query context.

        Returns:
            List of dicts: [{key, text, score}, ...]
        """
        if not self._entries:
            return []
        try:
            q_emb = _call_embed(query, image_b64)
        except Exception as e:
            print(f"[VectorMemory] Search embed failed: {e}")
            return []

        scored = sorted(
            ((float(np.dot(q_emb, e.embedding)), e) for e in self._entries),
            reverse=True,
        )
        return [
            {"key": e.key, "text": e.text, "score": round(s, 3)}
            for s, e in scored[:k]
        ]

    def clear(self):
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)

    def __repr__(self) -> str:
        return f"VectorMemory({len(self._entries)} entries)"
